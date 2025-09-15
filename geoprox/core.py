# geoprox/core.py
from __future__ import annotations

# ---------- stdlib ----------
import os
import re
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

# ---------- third-party ----------
import requests
import pandas as pd
import folium

# PDF (ReportLab)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet


# ---------- Defaults / constants ----------
DEFAULT_USER = "Contractor A - Streetworks coordinator"

USER_AGENT = "GlidePath-GeoProx-API/1.0"
HTTP_TIMEOUT = 25.0  # seconds per Overpass attempt
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Categories → list of OSM filters (each filter is either `key`, `key=value` or `key=*`)
OSM_FILTERS: Dict[str, List[str]] = {
    "manufacturing": ["industrial", "man_made=works", "landuse=industrial", "factory=*"],
    "gas_holding": ["man_made=gasometer", "storage=tank", "gas=storage"],
    "mines": ["landuse=quarry", "man_made=mineshaft", "mine=*", "quarry=*"],
    "petrol_stations": ["amenity=fuel"],
    "sewage_treatment": ["man_made=wastewater_plant", "water=wastewater"],
    "substations": ["power=substation"],
    "landfills": ["landuse=landfill", "amenity=waste_disposal"],
    "scrapyards": ["landuse=scrap_yard", "amenity=scrapyard"],
    "waste_disposal": ["amenity=recycling", "amenity=waste_transfer_station", "amenity=waste_disposal"],
}


# ---------- Basic helpers ----------
def compute_outcome(summary_bins: Dict[str, Dict[str, int]]) -> str:
    """HIGH if any category has <10 m, MEDIUM if any 10–25 m, else LOW."""
    has10 = any(b.get("<10m", 0) > 0 for b in summary_bins.values())
    if has10:
        return "HIGH"
    has25 = any(b.get("10–25m", 0) > 0 for b in summary_bins.values())
    if has25:
        return "MEDIUM"
    return "LOW"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_latlon(raw: str) -> Tuple[float, float]:
    """Extract first two floats from a string."""
    s = (raw or "").replace("\uFEFF", "").replace("\u200B", "").strip()
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
    if len(nums) < 2:
        raise ValueError("Location must contain lat and lon, e.g. '54.5973,-5.9301'.")
    lat = float(nums[0])
    lon = float(nums[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude/longitude out of range.")
    return lat, lon


def geocode_location_flex(loc: str, w3w_key: Optional[str]) -> Tuple[float, float, str]:
    """
    Accepts either:
      - plain coordinates 'lat,lon'
      - what3words '///word.word.word' (requires WHAT3WORDS_API_KEY)
    Returns (lat, lon, display_string)
    """
    loc = (loc or "").strip()
    if loc.startswith("///"):
        if not w3w_key:
            raise ValueError("No what3words API key configured. Set WHAT3WORDS_API_KEY.")
        words = loc.lstrip("/ ")
        url = "https://api.what3words.com/v3/convert-to-coordinates"
        r = requests.get(url, params={"words": words, "key": w3w_key}, timeout=15)
        if r.status_code != 200:
            raise ValueError(f"what3words error: HTTP {r.status_code}")
        data = r.json()
        lat = float(data["coordinates"]["lat"])
        lon = float(data["coordinates"]["lng"])
        return lat, lon, f"{words} → {lat:.6f}, {lon:.6f}"
    # else: treat as lat,lon
    lat, lon = parse_latlon(loc)
    return lat, lon, f"{lat:.6f}, {lon:.6f}"


def _ovf(token: str) -> str:
    """token like 'key', 'key=value', or 'key=*' → Overpass tag filter snippet."""
    if "=" in token:
        k, v = token.split("=", 1)
        k = k.strip()
        v = v.strip()
        if v == "*":
            return f'["{k}"]'
        return f'["{k}"="{v}"]'
    return f'["{token.strip()}"]'


@dataclass
class QueryInput:
    lat: float
    lon: float
    radius_m: int
    selected_categories: List[str]


def build_overpass_query_flat(q: QueryInput, cat_subset: Optional[List[str]] = None) -> str:
    cats = cat_subset or q.selected_categories or list(OSM_FILTERS.keys())
    cats = [c for c in cats if c in OSM_FILTERS]
    if not cats:
        raise ValueError("No valid categories to query.")

    parts: List[str] = []
    for key in cats:
        for tok in OSM_FILTERS[key]:
            flt = _ovf(tok)
            parts += [
                f"node{flt}(around:{q.radius_m},{q.lat},{q.lon});",
                f"way{flt}(around:{q.radius_m},{q.lat},{q.lon});",
                f"relation{flt}(around:{q.radius_m},{q.lat},{q.lon});",
            ]
    body = "\n".join(parts)
    return "[out:json][timeout:180];\n(\n" + body + "\n);\n" "out center tags;\n"


def _http_post(url: str, data: Dict[str, Any]) -> requests.Response:
    return requests.post(url, data=data, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)


def run_overpass_resilient(qi: QueryInput, abort_cb: Optional[callable] = None) -> Dict[str, Any]:
    query_all = build_overpass_query_flat(qi)
    last_err: Optional[str] = None
    for ep in OVERPASS_ENDPOINTS:
        try:
            r = _http_post(ep, {"data": query_all})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
            last_err = f"HTTP {r.status_code} from {ep}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(1.0)
    raise RuntimeError(f"Overpass request failed: {last_err}")


def osm_elements_to_df(data: Dict[str, Any]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for el in data.get("elements", []):
        el_type = el.get("type")
        tags = el.get("tags", {}) or {}
        name = tags.get("name") or "(unnamed)"
        if el_type == "node":
            lat = el.get("lat")
            lon = el.get("lon")
        else:
            c = el.get("center") or {}
            lat = c.get("lat")
            lon = c.get("lon")
        rows.append({"type": el_type, "name": name, "lat": lat, "lon": lon, "tags": tags})
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["type", "name", "lat", "lon", "tags"])
    return df


def summarise_by_bins(df: pd.DataFrame, origin: Tuple[float, float]) -> Dict[str, Dict[str, int]]:
    lat0, lon0 = origin
    out: Dict[str, Dict[str, int]] = {}

    def dist_m(row: pd.Series) -> float:
        try:
            return _haversine_m(lat0, lon0, float(row["lat"]), float(row["lon"]))
        except Exception:
            return float("inf")

    bins_template = {"<10m": 0, "10–25m": 0, "25–100m": 0, ">100m / not found": 0}

    # empty → produce all zeros for the report
    if df.empty:
        for label in [
            "Industrial / Manufacturing",
            "Gas holder stations",
            "Mining (coal, metalliferous)",
            "Petrol stations / Garages",
            "Sewage Treatment Works",
            "Sub-Stations",
            "Waste Site – Landfill & Treatment / Disposal",
            "Waste Site – Scrapyard / Metal Recycling",
            "Waste Site – Other",
        ]:
            out[label] = dict(bins_template)
        return out

    dfe = df.copy()
    dfe["distance_m"] = dfe.apply(dist_m, axis=1)

    cat_map = {
        "Industrial / Manufacturing": lambda t: ("industrial" in t)
        or (t.get("man_made") == "works")
        or (t.get("landuse") == "industrial")
        or ("factory" in t),
        "Gas holder stations": lambda t: (t.get("man_made") == "gasometer")
        or (t.get("storage") == "tank")
        or (t.get("gas") == "storage"),
        "Mining (coal, metalliferous)": lambda t: (t.get("landuse") == "quarry")
        or ("quarry" in t)
        or (t.get("man_made") == "mineshaft")
        or ("mine" in t),
        "Petrol stations / Garages": lambda t: (t.get("amenity") == "fuel"),
        "Sewage Treatment Works": lambda t: (t.get("man_made") == "wastewater_plant")
        or (t.get("water") == "wastewater"),
        "Sub-Stations": lambda t: (t.get("power") == "substation"),
        "Waste Site – Landfill & Treatment / Disposal": lambda t: (t.get("landuse") == "landfill")
        or (t.get("amenity") in {"waste_disposal", "waste_transfer_station"}),
        "Waste Site – Scrapyard / Metal Recycling": lambda t: (t.get("landuse") == "scrap_yard")
        or (t.get("amenity") == "scrapyard"),
        "Waste Site – Other": lambda t: (t.get("amenity") in {"recycling"}) and (t.get("landuse") != "scrap_yard"),
    }

    for disp, pred in cat_map.items():
        dfi = dfe[dfe["tags"].apply(lambda t: pred(t or {}))]
        b = dict(bins_template)
        if not dfi.empty:
            d10 = (dfi["distance_m"] < 10).sum()
            d25 = ((dfi["distance_m"] >= 10) & (dfi["distance_m"] < 25)).sum()
            d100 = ((dfi["distance_m"] >= 25) & (dfi["distance_m"] <= 100)).sum()
            rest = len(dfi) - (d10 + d25 + d100)
            b["<10m"] = int(d10)
            b["10–25m"] = int(d25)
            b["25–100m"] = int(d100)
            b[">100m / not found"] = int(rest)
        out[disp] = b
    return out


def _display_category(tags: Dict[str, Any]) -> str:
    t = tags or {}
    if (t.get("amenity") == "fuel"):
        return "Petrol stations / Garages"
    if (t.get("power") == "substation"):
        return "Sub-Stations"
    if (t.get("man_made") == "wastewater_plant") or (t.get("water") == "wastewater"):
        return "Sewage Treatment Works"
    if (t.get("landuse") == "quarry") or ("quarry" in t) or (t.get("man_made") == "mineshaft"):
        return "Mining (coal, metalliferous)"
    if (t.get("landuse") == "industrial") or (t.get("man_made") == "works") or ("factory" in t):
        return "Industrial / Manufacturing"
    if (t.get("landuse") == "landfill") or (t.get("amenity") in {"waste_disposal", "waste_transfer_station"}):
        return "Waste Site – Landfill & Treatment / Disposal"
    if (t.get("landuse") == "scrap_yard") or (t.get("amenity") == "scrapyard"):
        return "Waste Site – Scrapyard / Metal Recycling"
    if (t.get("amenity") == "recycling"):
        return "Waste Site – Other"
    if (t.get("man_made") == "gasometer") or (t.get("storage") == "tank"):
        return "Gas holder stations"
    return "Other"


def build_details_rows(df: pd.DataFrame, origin: Tuple[float, float]) -> List[Tuple[Any, ...]]:
    """Return rows for the ≤100 m table, nearest → farthest."""
    if df.empty:
        return []
    lat0, lon0 = origin

    def dist_m(row: pd.Series) -> float:
        try:
            return _haversine_m(lat0, lon0, float(row["lat"]), float(row["lon"]))
        except Exception:
            return float("inf")

    dfe = df.copy()
    dfe["distance_m"] = dfe.apply(dist_m, axis=1)
    dfe = dfe[dfe["distance_m"] <= 100].sort_values("distance_m")

    rows: List[Tuple[Any, ...]] = []
    for _, r in dfe.iterrows():
        rows.append(
            (
                int(round(r["distance_m"])),
                _display_category(r.get("tags") or {}),
                r.get("name") or "(unnamed)",
                float(r.get("lat") or 0.0),
                float(r.get("lon") or 0.0),
                r.get("tags", {}).get("addr:full") or "",
            )
        )
    return rows


def make_map(df: pd.DataFrame, center: Tuple[float, float], radius_m: int, out_html: str) -> None:
    m = folium.Map(location=center, zoom_start=15, control_scale=True)
    folium.Marker(center, tooltip="Search origin", icon=folium.Icon(color="red")).add_to(m)
    folium.Circle(center, radius=radius_m, color="#1F6FEB", fill=False).add_to(m)
    for _, r in df.iterrows():
        if pd.isna(r.get("lat")) or pd.isna(r.get("lon")):
            continue
        folium.Marker(
            (float(r["lat"]), float(r["lon"])),
            tooltip=f'{r.get("name") or "(unnamed)"}',
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(m)
    m.save(out_html)


def generate_pdf_summary(
    display_center: str,
    summary_bins: Dict[str, Dict[str, int]],
    pdf_path: str,
    map_image: Optional[str] = None,
    details_rows: Optional[List[Tuple[Any, ...]]] = None,
    map_html: Optional[str] = None,
    permit: str = "K6001-DAF-ACON-95841",
    user_name: str = DEFAULT_USER,
    search_dt: Optional[datetime] = None,
    outcome: Optional[str] = None,
) -> None:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.leading = 12
    title = styles["Title"]

    when = search_dt or datetime.now()
    outcome_label = (outcome or compute_outcome(summary_bins)).upper()

    color_map = {
        "HIGH": colors.HexColor("#c62828"),
        "MEDIUM": colors.HexColor("#ef6c00"),
        "LOW": colors.HexColor("#2e7d32"),
    }
    oc = color_map.get(outcome_label, colors.HexColor("#2e7d32"))

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm
    )
    flow: List[Any] = []

    # Title
    flow.append(Paragraph("GeoProx — Proximity Summary", title))
    flow.append(Spacer(1, 3 * mm))

    # Info bar
    info_data = [
        [
            Paragraph(f"<b>GeoProx user:</b> {user_name}", body),
            Paragraph(f"<b>Search Outcome:</b> <font color='white'><b>{outcome_label}</b></font>", body),
        ],
        [
            Paragraph(f"<b>Search complete:</b> {when.strftime('%d/%m/%Y %H:%M')}", body),
            Paragraph(f"<b>Permit:</b> {permit}", body),
        ],
        [
            Paragraph(f"<b>Search center:</b> {display_center}", body),
            Paragraph(f"<b>Open map:</b> <font color='#0b6aa2'><u>{map_html or ''}</u></font>", body),
        ],
    ]
    info_tbl = Table(info_data, colWidths=[95 * mm, 95 * mm])
    info_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (1, 0), (1, 0), oc),
                ("TEXTCOLOR", (1, 0), (1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(info_tbl)
    flow.append(Spacer(1, 6 * mm))

    # Summary table with ticks
    header = ["Category", "No", "<10m", "10–25m", "25–100m"]
    rows: List[List[Any]] = [header]

    def to_checks(bins: Dict[str, int]) -> List[str]:
        has10 = bins.get("<10m", 0) > 0
        has25 = bins.get("10–25m", 0) > 0
        has100 = bins.get("25–100m", 0) > 0
        no = not (has10 or has25 or has100)  # nothing within 100 m
        return ["✔" if no else "", "✔" if has10 else "", "✔" if has25 else "", "✔" if has100 else ""]

    for cat, bins in summary_bins.items():
        rows.append([Paragraph(cat, body), *to_checks(bins)])

    sum_tbl = Table(rows, repeatRows=1, colWidths=[80 * mm, 14 * mm, 16 * mm, 18 * mm, 22 * mm])
    sum_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6aa2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    flow.append(sum_tbl)
    flow.append(Spacer(1, 6 * mm))

    # Details table (≤100 m)
    flow.append(Paragraph("<b>Found items within 100 m (nearest → farthest)</b>", body))
    det_header = ["Distance (m)", "Category", "Name", "Lat", "Lon", "Address"]
    det_data: List[List[Any]] = [det_header]
    for dist, cat, name, lat, lon, addr in (details_rows or []):
        det_data.append([dist, Paragraph(cat, body), Paragraph(name or "(unnamed)", body), f"{lat:.5f}", f"{lon:.5f}", Paragraph(addr or "", body)])
    det_tbl = Table(det_data, repeatRows=1, colWidths=[24 * mm, 34 * mm, 46 * mm, 20 * mm, 20 * mm, 46 * mm])
    det_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow.append(det_tbl)

    doc.build(flow)


# ---------- Coordinator used by the API ----------
def run_geoprox_search(
    *,
    location: str,
    radius_m: int,
    categories: Optional[List[str]],
    permit: Optional[str],
    out_dir: Path,
    w3w_key: Optional[str] = None,
    max_results: int = 500,
) -> dict:
    # filter/normalise categories
    valid = set(OSM_FILTERS.keys())
    categories = [c for c in (categories or []) if c in valid]
    if not categories:
        categories = list(valid)

    # 1) Geocode
    lat, lon, disp = geocode_location_flex(location, w3w_key)

    # 2) Query Overpass
    qi = QueryInput(lat=lat, lon=lon, radius_m=radius_m, selected_categories=categories)
    data = run_overpass_resilient(qi)
    df = osm_elements_to_df(data)

    # 3) Summaries
    summary = summarise_by_bins(df, (lat, lon))
    details = build_details_rows(df, (lat, lon))

    # Cap number of detail rows processed/returned
    if max_results is not None:
        details = details[: int(max_results)]

    # 4) Artifacts (local)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _permit = permit or ""
    safe_permit = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in _permit)[:60] or "no_permit"
    map_html = out_dir / f"proximity_map_{safe_permit}.html"
    make_map(df, (lat, lon), radius_m, str(map_html))

    pdf_path = out_dir / f"GeoProx search - {safe_permit}.pdf"
    _now = datetime.utcnow()
    _outcome = compute_outcome(summary)
    generate_pdf_summary(
        display_center=disp,
        summary_bins=summary,
        pdf_path=str(pdf_path),
        map_image=None,
        details_rows=details,
        map_html=str(map_html),
        permit=_permit,
        user_name=DEFAULT_USER,
        search_dt=_now,
        outcome=_outcome,
    )

    # 5) JSON details for API
    details_rows_json = [
        {"distance_m": int(r[0]), "category": r[1], "name": r[2], "lat": float(r[3]), "lon": float(r[4]), "address": r[5]}
        for r in details
    ]

    # 6) Optional S3 upload
    bucket = os.environ.get("GEOPROX_BUCKET", "").strip()
    if bucket:
        try:
            import boto3

            s3 = boto3.client("s3")
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            base_key = f"searches/{ts}_{safe_permit}"

            def _ct(p: str) -> str:
                if p.endswith(".pdf"):
                    return "application/pdf"
                if p.endswith(".html"):
                    return "text/html; charset=utf-8"
                return "application/octet-stream"

            pdf_key = f"{base_key}.pdf"
            html_key = f"{base_key}.html"

            s3.upload_file(str(pdf_path), bucket, pdf_key, ExtraArgs={"ContentType": _ct(str(pdf_path))})
            s3.upload_file(str(map_html), bucket, html_key, ExtraArgs={"ContentType": _ct(str(map_html))})

            pdf_url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": pdf_key}, ExpiresIn=86400)
            html_url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": html_key}, ExpiresIn=86400)

            return {
                "center": {"lat": lat, "lon": lon, "display": disp},
                "radius_m": radius_m,
                "permit": _permit,
                "summary_bins": summary,
                "details_100m": details_rows_json,
                "artifacts": {"pdf_url": pdf_url, "map_html_url": html_url},
            }
        except Exception as e:
            # Fall through to local paths with a warning
            return {
                "center": {"lat": lat, "lon": lon, "display": disp},
                "radius_m": radius_m,
                "permit": _permit,
                "summary_bins": summary,
                "details_100m": details_rows_json,
                "artifacts": {"pdf_path": str(pdf_path), "map_html_path": str(map_html)},
                "warning": f"S3 upload failed: {e}",
            }

    # 7) No S3 configured → local paths
    return {
        "center": {"lat": lat, "lon": lon, "display": disp},
        "radius_m": radius_m,
        "permit": _permit,
        "summary_bins": summary,
        "details_100m": details_rows_json,
        "artifacts": {"pdf_path": str(pdf_path), "map_html_path": str(map_html)},
    }
