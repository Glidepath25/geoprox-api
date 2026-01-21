# geoprox/core.py
from __future__ import annotations

# ---------- stdlib ----------
import os
import logging
import re
import json
import math
import time
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

# ---------- third-party ----------
import requests
import pandas as pd
import folium
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform, nearest_points
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.backends.backend_agg import FigureCanvasAgg
import pyproj
from pyproj.enums import TransformDirection

# PDF (ReportLab)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader


log = logging.getLogger("uvicorn.error")

DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[1] / 'static' / 'geoprox-logo.png'

# ---------- Defaults / constants ----------
DEFAULT_USER = "Contractor A - Streetworks coordinator"

USER_AGENT = "GlidePath-GeoProx-API/1.0"
HTTP_TIMEOUT = 40.0  # seconds per Overpass attempt
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Categories â†’ list of OSM filters (each filter is either `key`, `key=value` or `key=*`)
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

SEARCH_CATEGORY_OPTIONS: List[Tuple[str, str]] = [
    ("manufacturing", "Industrial / Manufacturing"),
    ("gas_holding", "Gas holder stations"),
    ("mines", "Mining (coal, metalliferous)"),
    ("petrol_stations", "Petrol stations / Garages"),
    ("sewage_treatment", "Sewage Treatment Works"),
    ("substations", "Sub-Stations"),
    ("landfills", "Waste Site - Landfill & Treatment / Disposal"),
    ("scrapyards", "Waste Site - Scrapyard / Metal Recycling"),
    ("waste_disposal", "Waste Site - Other"),
]
SEARCH_CATEGORY_LABELS: Dict[str, str] = {key: label for key, label in SEARCH_CATEGORY_OPTIONS}
_SEARCH_CATEGORY_KEYS = set(SEARCH_CATEGORY_LABELS)
MANUAL_CATEGORY_TAGS: Dict[str, Dict[str, str]] = {
    "manufacturing": {"landuse": "industrial"},
    "gas_holding": {"man_made": "gasometer"},
    "mines": {"landuse": "quarry"},
    "petrol_stations": {"amenity": "fuel"},
    "sewage_treatment": {"man_made": "wastewater_plant"},
    "substations": {"power": "substation"},
    "landfills": {"landuse": "landfill"},
    "scrapyards": {"landuse": "scrap_yard"},
    "waste_disposal": {"amenity": "recycling"},
}


# ---------- Basic helpers ----------
def compute_outcome(summary_bins: Dict[str, Dict[str, int]]) -> str:
    """HIGH if any category has <10 m, MEDIUM if any 10-25 m, else LOW."""
    has10 = any(b.get("<10m", 0) > 0 for b in summary_bins.values())
    if has10:
        return "HIGH"
    has25 = any(b.get("10-25m", 0) > 0 for b in summary_bins.values())
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


# --- replace the entire geocode_location_flex function with this ---

def geocode_location_flex(
    loc: str,
    w3w_key: str | None = None,
) -> tuple[float, float, str]:
    """
    Accepts either:
      - "lat,lon"   (commas and/or extra spaces tolerated)
      - "lat lon"   (space separated)
      - "///word.word.word" (what3words, if w3w_key provided)

    Returns (lat, lon, display_string) or raises ValueError on invalid input.
    """
    loc = (loc or "").strip()

    # what3words
    if loc.startswith("///"):
        if not w3w_key:
            raise ValueError("what3words location supplied but WHAT3WORDS_API_KEY is not set")
        words = loc.lstrip("/").strip()
        display = f"///{words}"

        # very small inline call (keeps existing requests flow and avoids None returns)
        import requests
        r = requests.get(
            "https://api.what3words.com/v3/convert-to-coordinates",
            params={"words": words, "key": w3w_key},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if "coordinates" not in data:
            raise ValueError(f"what3words could not geocode '{loc}'")
        lat = float(data["coordinates"]["lat"])
        lon = float(data["coordinates"]["lng"])
        return lat, lon, display

    # numeric lat/lon - handle "lat, lon" OR "lat lon"
    # normalise separators to comma, then split
    clean = loc.replace("  ", " ").replace("\t", " ").replace(" ,", ",").replace(", ", ",")
    if "," in clean:
        parts = clean.split(",")
    else:
        parts = clean.split()

    if len(parts) != 2:
        raise ValueError("Location must be 'lat,lon', 'lat lon', or a what3words address starting with ///")

    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except Exception:
        raise ValueError("Could not parse latitude/longitude numbers")

    # quick sanity bounds
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("Latitude/Longitude out of bounds")

    return lat, lon, f"{lat:.6f}, {lon:.6f}"


def _resolve_display_center(
    raw_loc: str,
    lat: float,
    lon: float,
    w3w_key: Optional[str],
    fallback: str,
) -> str:
    """
    Pick the best human-readable label for the search centre.
    - honour an explicit what3words string if the user supplied one
    - otherwise, keep the coordinate display (do not auto-convert to what3words)
    - finally, fall back to the provided display string
    """
    raw = (raw_loc or "").strip()
    if raw.startswith("///"):
        return raw
    if fallback and fallback.startswith("///"):
        return fallback
    return fallback or f"{lat:.6f}, {lon:.6f}"



def _ovf(token: str) -> str:
    """token like 'key', 'key=value', or 'key=*' â†’ Overpass tag filter snippet."""
    if "=" in token:
        k, v = token.split("=", 1)
        k = k.strip()
        v = v.strip()
        if v == "*":
            return f'["{k}"]'
        return f'["{k}"="{v}"]'
    return f'["{token.strip()}"]'


def _geometry_from_osm_element(el: Dict[str, Any]) -> Optional[BaseGeometry]:
    coords = el.get("geometry") or []
    points: List[Tuple[float, float]] = []
    for pt in coords:
        try:
            points.append((float(pt["lon"]), float(pt["lat"])))
        except Exception:
            continue
    geom: Optional[BaseGeometry] = None
    if points:
        if len(points) >= 4 and points[0] == points[-1]:
            try:
                poly = Polygon(points)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                geom = poly
            except Exception:
                geom = None
        if geom is None and len(points) >= 2:
            try:
                geom = LineString(points)
            except Exception:
                geom = None
        if geom is None:
            geom = ShapelyPoint(points[0])
    if geom is None:
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is not None and lon is not None:
            try:
                geom = ShapelyPoint(float(lon), float(lat))
            except Exception:
                geom = None
    if geom is None:
        center = el.get("center") or {}
        lat = center.get("lat")
        lon = center.get("lon")
        if lat is not None and lon is not None:
            try:
                geom = ShapelyPoint(float(lon), float(lat))
            except Exception:
                geom = None
    if geom is not None and getattr(geom, "is_empty", False):
        return None
    return geom


def _geom_centroid_latlon(geom: Optional[BaseGeometry]) -> Tuple[Optional[float], Optional[float]]:
    if geom is None:
        return None, None
    try:
        if isinstance(geom, ShapelyPoint):
            return float(geom.y), float(geom.x)
        centroid = geom.centroid
        return float(centroid.y), float(centroid.x)
    except Exception:
        return None, None


def _utm_transformer(lat: float, lon: float) -> Optional[pyproj.Transformer]:
    try:
        zone = int((lon + 180.0) / 6.0) + 1
        zone = max(1, min(60, zone))
        hemisphere = "north" if lat >= 0 else "south"
        proj = pyproj.CRS.from_proj4(f"+proj=utm +zone={zone} +{hemisphere} +datum=WGS84 +units=m +no_defs")
        return pyproj.Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    except Exception:
        return None


def _annotate_distances(
    df: pd.DataFrame,
    origin: Tuple[float, float],
    *,
    reference_geom: Optional[BaseGeometry] = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    lat0, lon0 = origin
    transformer = _utm_transformer(lat0, lon0)
    ref_geom = reference_geom or ShapelyPoint(lon0, lat0)
    reference_projected: Optional[BaseGeometry] = None
    inverse_func = None
    if transformer is not None:
        try:
            reference_projected = shapely_transform(transformer.transform, ref_geom)

            def _inverse(x, y, z=None, _transform=transformer):
                return _transform.transform(x, y, z, direction=TransformDirection.INVERSE)

            inverse_func = _inverse
        except Exception:
            reference_projected = ref_geom
            transformer = None
    if reference_projected is None:
        reference_projected = ref_geom

    distances: List[float] = []
    ref_lats: List[Optional[float]] = []
    ref_lons: List[Optional[float]] = []
    feature_edge_lats: List[Optional[float]] = []
    feature_edge_lons: List[Optional[float]] = []

    for _, row in df.iterrows():
        dist: Optional[float] = None
        ref_lat: Optional[float] = None
        ref_lon: Optional[float] = None
        feat_lat: Optional[float] = None
        feat_lon: Optional[float] = None
        geom = row.get("geom")
        if isinstance(geom, BaseGeometry):
            geom_projected = shapely_transform(transformer.transform, geom) if transformer is not None else geom
            try:
                dist = float(geom_projected.distance(reference_projected))
                closest_geom, closest_ref = nearest_points(geom_projected, reference_projected)
                if inverse_func is not None:
                    ref_point = shapely_transform(inverse_func, closest_ref)
                    feat_point = shapely_transform(inverse_func, closest_geom)
                else:
                    ref_point = closest_ref
                    feat_point = closest_geom
                ref_lon = float(ref_point.x)
                ref_lat = float(ref_point.y)
                feat_lon = float(feat_point.x)
                feat_lat = float(feat_point.y)
            except Exception:
                dist = None

        if dist is None:
            lat = row.get("lat")
            lon = row.get("lon")
            if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
                distances.append(float("inf"))
                ref_lats.append(None)
                ref_lons.append(None)
                feature_edge_lats.append(None)
                feature_edge_lons.append(None)
                continue
            lat_f = float(lat)
            lon_f = float(lon)
            if isinstance(ref_geom, ShapelyPoint):
                dist = float(_haversine_m(lat0, lon0, lat_f, lon_f))
                ref_lat = lat0
                ref_lon = lon0
                feat_lat = lat_f
                feat_lon = lon_f
            else:
                try:
                    candidate_point = ShapelyPoint(lon_f, lat_f)
                    closest_ref, closest_geom = nearest_points(ref_geom, candidate_point)
                    ref_lon = float(closest_ref.x)
                    ref_lat = float(closest_ref.y)
                    dist = float(_haversine_m(lat_f, lon_f, ref_lat, ref_lon))
                    feat_lat = float(closest_geom.y) if hasattr(closest_geom, 'y') else lat_f
                    feat_lon = float(closest_geom.x) if hasattr(closest_geom, 'x') else lon_f
                except Exception:
                    dist = float(_haversine_m(lat0, lon0, lat_f, lon_f))
                    ref_lat = lat0
                    ref_lon = lon0
                    feat_lat = lat_f
                    feat_lon = lon_f

        distances.append(dist if dist is not None else float("inf"))
        ref_lats.append(ref_lat)
        ref_lons.append(ref_lon)
        feature_edge_lats.append(feat_lat)
        feature_edge_lons.append(feat_lon)

    out = df.copy()
    out["distance_m"] = distances
    out["nearest_lat"] = ref_lats
    out["nearest_lon"] = ref_lons
    out["feature_edge_lat"] = feature_edge_lats
    out["feature_edge_lon"] = feature_edge_lons
    return out


def _ensure_distance_column(
    df: pd.DataFrame, origin: Tuple[float, float], reference_geom: Optional[BaseGeometry] = None
) -> pd.DataFrame:
    if df.empty or "distance_m" in df.columns:
        return df
    return _annotate_distances(df, origin, reference_geom=reference_geom)


def _build_summary_payload(
    summary_bins: Dict[str, Dict[str, int]],
    *,
    outcome: str,
    center: str,
    radius: int,
    permit: str,
    lat: float,
    lon: float,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for label, bins in summary_bins.items():
        lt_10 = (bins or {}).get("<10m", 0) or 0
        r_10_25 = (bins or {}).get("10-25m", 0) or 0
        r_25_100 = (bins or {}).get("25-100m", 0) or 0
        has_lt = lt_10 > 0
        has_mid = r_10_25 > 0
        has_far = r_25_100 > 0
        rows.append(
            {
                "label": label,
                "no": not (has_lt or has_mid or has_far),
                "lt10": has_lt,
                "r10_25": has_mid,
                "r25_100": has_far,
            }
        )
    return {
        "outcome": outcome,
        "center": center,
        "radius": radius,
        "permit": permit,
        "center_coords": {"lat": lat, "lon": lon},
        "categories": rows,
    }



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
    return "[out:json][timeout:180];\n(\n" + body + "\n);\n" "out body center geom;\n"


def _http_post(url: str, data: Dict[str, Any]) -> "requests.Response":
    import requests
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
        geom = _geometry_from_osm_element(el)
        lat_val: Optional[float] = None
        lon_val: Optional[float] = None
        lat_raw = el.get("lat")
        lon_raw = el.get("lon")
        try:
            if lat_raw is not None:
                lat_val = float(lat_raw)
        except Exception:
            lat_val = None
        try:
            if lon_raw is not None:
                lon_val = float(lon_raw)
        except Exception:
            lon_val = None
        if geom is not None:
            c_lat, c_lon = _geom_centroid_latlon(geom)
            if c_lat is not None and c_lon is not None:
                lat_val = c_lat
                lon_val = c_lon
        rows.append({"type": el_type, "name": name, "lat": lat_val, "lon": lon_val, "tags": tags, "geom": geom})
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["type", "name", "lat", "lon", "tags", "geom"])
    return df


def _manual_locations_to_df(
    extra_locations: Optional[List[Dict[str, Any]]],
    origin: Tuple[float, float],
    query_radius_m: int,
) -> pd.DataFrame:
    if not extra_locations:
        return pd.DataFrame(columns=["type", "name", "lat", "lon", "tags", "geom"])

    lat0, lon0 = origin
    try:
        max_radius = float(query_radius_m or 0)
    except Exception:
        max_radius = 0.0
    unlimited = max_radius <= 0.0

    rows: List[Dict[str, Any]] = []
    for feature in extra_locations:
        if not isinstance(feature, dict):
            continue
        lat_raw = feature.get("lat", feature.get("latitude"))
        lon_raw = feature.get("lon", feature.get("longitude"))
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        category_key = str(feature.get("category") or "").strip()
        if category_key not in _SEARCH_CATEGORY_KEYS:
            continue

        distance = _haversine_m(lat0, lon0, lat, lon)
        if not unlimited and distance > max_radius:
            continue

        tags = dict(MANUAL_CATEGORY_TAGS.get(category_key, {}))
        tags["__source"] = "verified_report"
        tags["__search_category"] = category_key

        address = feature.get("address")
        if address:
            tags["addr:full"] = str(address).strip()

        notes = feature.get("notes")
        if notes:
            tags["note"] = str(notes).strip()

        submitted_by = feature.get("submitted_by")
        if submitted_by:
            tags["submitted_by"] = str(submitted_by).strip()

        feature_id = feature.get("id")
        if feature_id is not None:
            tags["report_id"] = str(feature_id)

        name = feature.get("name") or "(unlabelled location)"
        try:
            name_text = str(name)
        except Exception:
            name_text = "Unnamed location"

        rows.append(
            {
                "type": "manual",
                "name": name_text,
                "lat": lat,
                "lon": lon,
                "tags": tags,
                "geom": ShapelyPoint(lon, lat),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["type", "name", "lat", "lon", "tags", "geom"])
    return pd.DataFrame(rows, columns=["type", "name", "lat", "lon", "tags", "geom"])


def summarise_by_bins(
    df: pd.DataFrame, origin: Tuple[float, float], reference_geom: Optional[BaseGeometry] = None
) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}

    bins_template = {"<10m": 0, "10-25m": 0, "25-100m": 0, ">100m / not found": 0}

    # empty -> produce all zeros for the report
    if df.empty:
        for label in [
            "Industrial / Manufacturing",
            "Gas holder stations",
            "Mining (coal, metalliferous)",
            "Petrol stations / Garages",
            "Sewage Treatment Works",
            "Sub-Stations",
            "Waste Site - Landfill & Treatment / Disposal",
            "Waste Site - Scrapyard / Metal Recycling",
            "Waste Site - Other",
        ]:
            out[label] = dict(bins_template)
        return out

    dfe = _ensure_distance_column(df, origin, reference_geom=reference_geom).copy()
    if "distance_m" not in dfe.columns:
        dfe["distance_m"] = float("inf")
    dfe["distance_m"] = pd.to_numeric(dfe["distance_m"], errors="coerce").fillna(float("inf"))

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
        "Waste Site - Landfill & Treatment / Disposal": lambda t: (t.get("landuse") == "landfill")
        or (t.get("amenity") in {"waste_disposal", "waste_transfer_station"}),
        "Waste Site - Scrapyard / Metal Recycling": lambda t: (t.get("landuse") == "scrap_yard")
        or (t.get("amenity") == "scrapyard"),
        "Waste Site - Other": lambda t: (t.get("amenity") in {"recycling"}) and (t.get("landuse") != "scrap_yard"),
    }
    petrol_thresholds = (25.0, 50.0, 100.0)
    default_thresholds = (10.0, 25.0, 100.0)


    for disp, pred in cat_map.items():
        dfi = dfe[dfe["tags"].apply(lambda t: pred(t or {}))]
        b = dict(bins_template)
        if not dfi.empty:
            t1, t2, t3 = petrol_thresholds if disp == "Petrol stations / Garages" else default_thresholds
            d_lt = (dfi["distance_m"] < t1).sum()
            d_mid = ((dfi["distance_m"] >= t1) & (dfi["distance_m"] < t2)).sum()
            d_far = ((dfi["distance_m"] >= t2) & (dfi["distance_m"] <= t3)).sum()
            rest = len(dfi) - (d_lt + d_mid + d_far)
            b["<10m"] = int(d_lt)
            b["10-25m"] = int(d_mid)
            b["25-100m"] = int(d_far)
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
        return "Waste Site - Landfill & Treatment / Disposal"
    if (t.get("landuse") == "scrap_yard") or (t.get("amenity") == "scrapyard"):
        return "Waste Site - Scrapyard / Metal Recycling"
    if (t.get("amenity") == "recycling"):
        return "Waste Site - Other"
    if (t.get("man_made") == "gasometer") or (t.get("storage") == "tank"):
        return "Gas holder stations"
    return "Other"


def build_details_rows(
    df: pd.DataFrame, origin: Tuple[float, float], reference_geom: Optional[BaseGeometry] = None
) -> List[Tuple[Any, ...]]:
    """Return rows for the <=100 m table, nearest -> farthest."""
    if df.empty:
        return []

    dfe = _ensure_distance_column(df, origin, reference_geom=reference_geom).copy()
    if "distance_m" not in dfe.columns:
        dfe["distance_m"] = float("inf")
    dfe["distance_m"] = pd.to_numeric(dfe["distance_m"], errors="coerce").fillna(float("inf"))
    dfe = dfe[dfe["distance_m"] <= 100].sort_values("distance_m")

    rows: List[Tuple[Any, ...]] = []
    for _, r in dfe.iterrows():
        dist_val = float(r.get("distance_m", float("inf")))
        rows.append(
            (
                int(round(dist_val)),
                _display_category(r.get("tags") or {}),
                r.get("name") or "(unnamed)",
                float(r.get("lat") or 0.0),
                float(r.get("lon") or 0.0),
                r.get("tags", {}).get("addr:full") or "",
            )
        )
    return rows


def make_map(
    df: pd.DataFrame,
    center: Tuple[float, float],
    radius_m: int,
    out_html: str,
    *,
    selection_mode: str = "point",
    selection_geom: Optional[BaseGeometry] = None,
) -> None:
    m = folium.Map(location=center, zoom_start=15, control_scale=True)
    center_lat, center_lon = float(center[0]), float(center[1])
    is_polygon_mode = selection_mode == "polygon" and isinstance(selection_geom, BaseGeometry)

    if is_polygon_mode:
        try:
            polygons: List[List[Tuple[float, float]]] = []
            if isinstance(selection_geom, Polygon):
                polygons.append(list(selection_geom.exterior.coords))
            elif hasattr(selection_geom, "geoms"):
                for geom in selection_geom.geoms:  # type: ignore[attr-defined]
                    if isinstance(geom, Polygon):
                        polygons.append(list(geom.exterior.coords))
            for ring in polygons:
                latlngs = [(float(y), float(x)) for x, y in ring]
                if len(latlngs) >= 3:
                    folium.Polygon(latlngs, color="#1F6FEB", weight=2.5, fill=False, tooltip="Search polygon").add_to(m)
        except Exception:
            pass
        folium.Marker((center_lat, center_lon), tooltip="Polygon centroid", icon=folium.Icon(color="red")).add_to(m)
    else:
        folium.Marker(center, tooltip="Search origin", icon=folium.Icon(color="red")).add_to(m)
        folium.Circle(center, radius=radius_m, color="#1F6FEB", fill=False).add_to(m)

    for _, r in df.iterrows():
        lat = r.get("lat")
        lon = r.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue
        lat_f = float(lat)
        lon_f = float(lon)
        folium.Marker(
            (lat_f, lon_f),
            tooltip=f"{r.get('name') or '(unnamed)'}",
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(m)

        edge_lat = r.get("feature_edge_lat")
        edge_lon = r.get("feature_edge_lon")
        if edge_lat is None or edge_lon is None or pd.isna(edge_lat) or pd.isna(edge_lon):
            edge_lat = lat_f
            edge_lon = lon_f
        else:
            edge_lat = float(edge_lat)
            edge_lon = float(edge_lon)

        nearest_lat = r.get("nearest_lat")
        nearest_lon = r.get("nearest_lon")
        dist_val = r.get("distance_m")
        if nearest_lat is None or nearest_lon is None or pd.isna(nearest_lat) or pd.isna(nearest_lon):
            continue
        try:
            distance_float = float(dist_val) if dist_val is not None else None
        except Exception:
            distance_float = None

        if is_polygon_mode:
            line_points = [(edge_lat, edge_lon), (float(nearest_lat), float(nearest_lon))]
            tooltip_text = 'Nearest polygon boundary'
        else:
            line_points = [(center_lat, center_lon), (edge_lat, edge_lon)]
            tooltip_text = 'Nearest boundary'

        folium.PolyLine(line_points, color="#ff9800", weight=2.5, opacity=0.8).add_to(m)
        if distance_float is not None and distance_float != float('inf'):
            tooltip_text = f"{tooltip_text} (distance: {distance_float:.1f} m)"
        folium.CircleMarker(
            (float(nearest_lat), float(nearest_lon)),
            radius=4,
            color="#ff9800",
            fill=True,
            fill_color="#ff9800",
            fill_opacity=0.9,
            tooltip=tooltip_text,
        ).add_to(m)
    m.save(out_html)



def _render_static_map_image(
    df: pd.DataFrame,
    *,
    center: Tuple[float, float],
    radius_m: int,
    out_path: Path,
    selection_mode: str,
    selection_geom: Optional[BaseGeometry],
) -> Optional[Path]:
    def _stitch_osm_tiles() -> Optional[Path]:
        """
        Stitch a small grid of OSM tiles around the search centre to include roads/streets.
        Requires Pillow (via matplotlib dependency in most environments).
        """
        try:
            from PIL import Image
        except Exception as exc:
            log.warning("Pillow missing for tile stitching: %s", exc)
            return None

        try:
            lat0, lon0 = center
            size_px = 800
            cos_lat = max(0.1, math.cos(math.radians(lat0)))

            # Choose zoom so that 80% of the canvas spans ~2*radius.
            desired_mpp = max((radius_m * 2) / (size_px * 0.8), 0.5)
            zoom_float = math.log2((156543.03392 * cos_lat) / desired_mpp)
            zoom = max(2, min(int(zoom_float), 18))

            def _xy(la: float, lo: float, z: int) -> Tuple[float, float]:
                n = 2 ** z
                xt = (lo + 180.0) / 360.0 * n
                lat_rad = math.radians(la)
                yt = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
                return xt, yt

            xtile, ytile = _xy(lat0, lon0, zoom)
            # number of tiles to cover radius; add padding so center stays centered without clamping
            mpp = 156543.03392 * cos_lat / (2 ** zoom)
            span_px = (radius_m * 2) / mpp
            tiles_needed = min(6, max(3, int(math.ceil(span_px / 256.0) + 2)))
            pad_tiles = 1

            x_start = int(math.floor(xtile - tiles_needed / 2)) - pad_tiles
            y_start = int(math.floor(ytile - tiles_needed / 2)) - pad_tiles
            width_tiles = tiles_needed + pad_tiles * 2
            height_tiles = tiles_needed + pad_tiles * 2
            canvas = Image.new("RGB", (width_tiles * 256, height_tiles * 256), (247, 249, 252))

            headers = {"User-Agent": USER_AGENT}
            for dx in range(width_tiles):
                for dy in range(height_tiles):
                    tx = x_start + dx
                    ty = y_start + dy
                    if tx < 0 or ty < 0 or tx >= 2 ** zoom or ty >= 2 ** zoom:
                        continue
                    url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
                    try:
                        r = requests.get(url, timeout=8, headers=headers)
                        r.raise_for_status()
                        tile_img = Image.open(BytesIO(r.content)).convert("RGB")
                        canvas.paste(tile_img, (dx * 256, dy * 256))
                    except Exception:
                        # Leave the default background for missing tiles.
                        continue

            # Crop around the centre to desired size.
            center_px = (xtile - x_start) * 256
            center_py = (ytile - y_start) * 256
            left = int(center_px - size_px / 2)
            top = int(center_py - size_px / 2)
            cropped = canvas.crop((left, top, left + size_px, top + size_px))

            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Draw overlays (radius circle + markers) on top of the tiles.
            try:
                from PIL import ImageDraw, ImageFont

                draw = ImageDraw.Draw(cropped, "RGBA")

                cx = size_px / 2
                cy = size_px / 2
                mpp = 156543.03392 * cos_lat / (2 ** zoom)
                radius_px = max(8, radius_m / mpp)

                # Circle for search radius (point mode) or polygon overlay
                if selection_mode == "polygon" and isinstance(selection_geom, BaseGeometry):
                    polygons: List[BaseGeometry] = []
                    if isinstance(selection_geom, Polygon):
                        polygons = [selection_geom]
                    else:
                        polygons = [g for g in getattr(selection_geom, "geoms", []) if isinstance(g, Polygon)]
                    for poly in polygons:
                        try:
                            coords = list(poly.exterior.coords)
                        except Exception:
                            continue
                        pts = []
                        for lon_val, lat_val in coords:
                            px, py = to_px(lat_val, lon_val)
                            pts.append((px, py))
                        if len(pts) >= 3:
                            draw.polygon(pts, outline=(43, 124, 255, 255), fill=(43, 124, 255, 35), width=4)
                else:
                    draw.ellipse(
                        (cx - radius_px, cy - radius_px, cx + radius_px, cy + radius_px),
                        outline=(43, 124, 255, 255),
                        width=4,
                        fill=(43, 124, 255, 35),
                    )

                # Markers: center (red) and features (blue)
                def to_px(lat_val: float, lon_val: float) -> Tuple[float, float]:
                    xt, yt = _xy(lat_val, lon_val, zoom)
                    px = (xt - x_start) * 256 - left
                    py = (yt - y_start) * 256 - top
                    return px, py

                def draw_dot(px: float, py: float, color: Tuple[int, int, int], size: int = 10, outline=None):
                    r = size / 2
                    bbox = (px - r, py - r, px + r, py + r)
                    draw.ellipse(bbox, fill=color + (255,), outline=outline or (255, 255, 255, 220), width=2)

                # Center
                draw_dot(cx, cy, (255, 82, 82), size=16)

                # Features (limit 50)
                count = 0
                for _, row in df.iterrows():
                    if count >= 50:
                        break
                    lat = row.get("lat")
                    lon = row.get("lon")
                    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
                        continue
                    fx, fy = to_px(float(lat), float(lon))
                    draw_dot(fx, fy, (79, 179, 255), size=12)
                    count += 1

                # Radius badge
                try:
                    font = ImageFont.truetype("arial.ttf", 14)
                except Exception:
                    font = None
                badge_text = f"Radius: {radius_m} m"
                text_w, text_h = draw.textsize(badge_text, font=font)
                pad = 6
                badge_box = (cx + radius_px * 0.2, cy - radius_px * 0.9 - text_h - pad * 2, cx + radius_px * 0.2 + text_w + pad * 2, cy - radius_px * 0.9)
                draw.rounded_rectangle(badge_box, radius=6, fill=(255, 255, 255, 235), outline=(180, 186, 195, 255))
                draw.text((badge_box[0] + pad, badge_box[1] + pad), badge_text, fill=(66, 92, 122, 255), font=font)
            except Exception as exc:
                log.warning("Failed to overlay markers on stitched tiles: %s", exc)

            cropped.save(out_path, format="PNG")
            return out_path
        except Exception as exc:
            log.warning("OSM tile stitching failed: %s", exc)
            return None

    try:
        # Try stitched OSM tiles (with overlays) first to capture streets/roads.
        tile_result = _stitch_osm_tiles()
        if tile_result:
            return tile_result

        lat0, lon0 = center
        transformer = _utm_transformer(lat0, lon0)

        def to_xy(lat_val: float, lon_val: float) -> Tuple[float, float]:
            if transformer is not None:
                x, y = transformer.transform(lon_val, lat_val)
                return float(x), float(y)
            return float(lon_val), float(lat_val)

        is_polygon_mode = selection_mode == "polygon" and isinstance(selection_geom, BaseGeometry)
        center_xy = ShapelyPoint(*to_xy(lat0, lon0))
        if is_polygon_mode and isinstance(selection_geom, BaseGeometry):
            try:
                reference_geom_xy: BaseGeometry = shapely_transform(transformer.transform, selection_geom) if transformer else selection_geom
            except Exception:
                reference_geom_xy = selection_geom
        else:
            reference_geom_xy = center_xy.buffer(radius_m) if transformer else center_xy

        fig = Figure(figsize=(6, 6), dpi=150)
        ax = fig.add_subplot(111)
        fig.patch.set_facecolor('#f7f9fc')
        ax.set_facecolor('#f7f9fc')
        ax.grid(True, color='#dce3f0', linewidth=0.6, alpha=0.5, zorder=0)

        xs: List[float] = []
        ys: List[float] = []

        if is_polygon_mode and isinstance(reference_geom_xy, BaseGeometry) and not isinstance(reference_geom_xy, ShapelyPoint):
            try:
                if isinstance(reference_geom_xy, Polygon):
                    polygons = [reference_geom_xy]
                else:
                    polygons = [geom for geom in getattr(reference_geom_xy, 'geoms', []) if isinstance(geom, Polygon)]
                for geom in polygons:
                    x_coords, y_coords = geom.exterior.xy
                    ax.plot(x_coords, y_coords, color='#1F6FEB', linewidth=2.2)
                    xs.extend(x_coords)
                    ys.extend(y_coords)
            except Exception:
                pass
        else:
            buffer_geom = center_xy.buffer(radius_m if transformer is not None else radius_m / 111_000.0)
            x_coords, y_coords = buffer_geom.exterior.xy
            ax.fill(x_coords, y_coords, color='#2b7cff', alpha=0.08, zorder=1)
            ax.plot(x_coords, y_coords, color='#1F6FEB', linewidth=2.2, zorder=2)
            xs.extend(x_coords)
            ys.extend(y_coords)

        feature_pts: List[Tuple[float, float]] = []
        feature_labels: List[Tuple[float, float, str]] = []
        feature_lines: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        edge_pts: List[Tuple[float, float]] = []
        boundary_pts: List[Tuple[float, float]] = []
        # Order features by distance so labels are meaningful
        try:
            df_iter = df.sort_values(by=["distance_m"])
        except Exception:
            df_iter = df
        for idx, row in df_iter.iterrows():
            lat = row.get('lat')
            lon = row.get('lon')
            if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
                continue
            fx, fy = to_xy(float(lat), float(lon))
            feature_pts.append((fx, fy))
            xs.append(fx)
            ys.append(fy)
            # Prepare compact labels (1-based index, distance, category)
            try:
                dist_val = row.get("distance_m")
                dist_txt = f"{float(dist_val):.0f}m" if dist_val is not None and not pd.isna(dist_val) else ""
            except Exception:
                dist_txt = ""
            cat_txt = str(row.get("category") or "").strip()
            if len(cat_txt) > 12:
                cat_txt = cat_txt[:12] + "…"
            label_txt = f"{len(feature_labels)+1}"
            if dist_txt:
                label_txt += f": {dist_txt}"
            if cat_txt:
                label_txt += f" {cat_txt}"
            feature_labels.append((fx, fy, label_txt))

            edge_lat = row.get('feature_edge_lat')
            edge_lon = row.get('feature_edge_lon')
            if edge_lat is None or edge_lon is None or pd.isna(edge_lat) or pd.isna(edge_lon):
                edge_lat = float(lat)
                edge_lon = float(lon)
            edge_x, edge_y = to_xy(float(edge_lat), float(edge_lon))
            edge_pts.append((edge_x, edge_y))
            xs.append(edge_x)
            ys.append(edge_y)

            nearest_lat = row.get('nearest_lat')
            nearest_lon = row.get('nearest_lon')
            if nearest_lat is None or nearest_lon is None or pd.isna(nearest_lat) or pd.isna(nearest_lon):
                continue
            bx, by = to_xy(float(nearest_lat), float(nearest_lon))
            boundary_pts.append((bx, by))
            xs.append(bx)
            ys.append(by)

            if is_polygon_mode:
                start_x, start_y = edge_x, edge_y
                end_x, end_y = bx, by
            else:
                start_x, start_y = center_xy.x, center_xy.y
                end_x, end_y = edge_x, edge_y
            feature_lines.append(((start_x, start_y), (end_x, end_y)))

        if feature_pts:
            ax.scatter([p[0] for p in feature_pts], [p[1] for p in feature_pts], color='#4fb3ff', s=28, zorder=5)
        if edge_pts:
            ax.scatter([p[0] for p in edge_pts], [p[1] for p in edge_pts], color='#4fb3ff', s=18, zorder=5, alpha=0.7)
        if boundary_pts:
            ax.scatter([p[0] for p in boundary_pts], [p[1] for p in boundary_pts], color='#ff9800', s=36, zorder=6)
        if feature_lines:
            for (sx, sy), (ex, ey) in feature_lines:
                ax.plot([sx, ex], [sy, ey], color='#ff9800', linewidth=1.8, alpha=0.9, zorder=4)

        ax.scatter([center_xy.x], [center_xy.y], color='#ff5252', s=40, zorder=8)
        if not feature_pts:
            ax.text(
                0.5,
                0.5,
                f"No nearby features within {radius_m} m",
                ha='center',
                va='center',
                fontsize=11,
                color='#425c7a',
                transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.35', facecolor='white', edgecolor='#d0d7e2', alpha=0.85),
                zorder=10,
            )
        else:
            # Label up to 20 features with distance/category
            for fx, fy, txt in feature_labels[:20]:
                ax.text(
                    fx,
                    fy,
                    txt,
                    fontsize=7.5,
                    color='#0b1b2b',
                    ha='left',
                    va='bottom',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='none', alpha=0.8),
                    zorder=9,
                )
            ax.text(
                0.01,
                0.99,
                f"{len(feature_pts)} features shown",
                ha='left',
                va='top',
                fontsize=8,
                color='#0b1b2b',
                transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='#d0d7e2', alpha=0.9),
                zorder=9,
            )

        if xs and ys:
            # Clamp view to the search radius so the map is zoomed appropriately.
            radius_units = float(radius_m)
            if transformer is None:
                radius_units = float(radius_m) / 111_000.0  # rough degrees per metre
            pad = radius_units * 0.15
            cx, cy = center_xy.x, center_xy.y
            ax.set_xlim(cx - radius_units - pad, cx + radius_units + pad)
            ax.set_ylim(cy - radius_units - pad, cy + radius_units + pad)

        ax.set_aspect('equal', 'box')
        ax.axis('off')

        # Legend and annotations for clarity on otherwise sparse views
        legend_items = [
            Line2D([0], [0], marker='o', color='w', label='Search center', markerfacecolor='#ff5252', markersize=8),
            Line2D([0], [0], marker='o', color='w', label='Nearby feature', markerfacecolor='#4fb3ff', markersize=8),
            Line2D([0], [0], marker='o', color='w', label='Nearest boundary', markerfacecolor='#ff9800', markersize=8),
        ]
        ax.legend(
            handles=legend_items,
            loc='lower left',
            frameon=True,
            framealpha=0.9,
            facecolor='#ffffff',
            edgecolor='#d0d7e2',
        )
        ax.text(
            0.99,
            0.98,
            f"Radius: {radius_m} m",
            ha='right',
            va='top',
            fontsize=9,
            color='#0b1b2b',
            transform=ax.transAxes,
            bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='#d0d7e2', alpha=0.9),
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        FigureCanvasAgg(fig).print_png(str(out_path))
        return out_path
    except Exception as exc:
        log.warning('Failed to render static map image: %s', exc)
        return None



def generate_pdf_summary(
    display_center: str,
    summary_bins: Dict[str, Dict[str, int]],
    pdf_path: str,
    map_image: Optional[str] = None,
    details_rows: Optional[List[Tuple[Any, ...]]] = None,
    map_html: Optional[str] = None,
    permit: str = "K6001-DAF-ACON-95841",
    address: Optional[str] = None,
    highway_authority: Optional[str] = None,
    user_name: str = DEFAULT_USER,
    search_dt: Optional[datetime] = None,
    outcome: Optional[str] = None,
    selection_mode: str = "point",
    logo_path: Optional[str] = None,
) -> None:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.leading = 12
    title = styles["Title"]
    heading = styles["Heading2"]

    resolved_logo: Optional[Path] = None
    if logo_path:
        candidate_path = Path(logo_path)
        if candidate_path.exists():
            resolved_logo = candidate_path
    if resolved_logo is None and DEFAULT_LOGO_PATH.exists():
        resolved_logo = DEFAULT_LOGO_PATH

    when = search_dt or datetime.now()
    outcome_label = (outcome or compute_outcome(summary_bins)).upper()
    selection_label = "Polygon" if (selection_mode or "point").lower() == "polygon" else "Point"

    color_map = {
        "HIGH": colors.HexColor("#c62828"),
        "MEDIUM": colors.HexColor("#ef6c00"),
        "LOW": colors.HexColor("#2e7d32"),
    }
    oc = color_map.get(outcome_label, colors.HexColor("#2e7d32"))

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm
    )
    permit_clean = (permit or "").strip()
    doc_title = "GeoProx - {}".format(permit_clean or "no permit")
    author_name = (user_name or "GeoProx").strip() or "GeoProx"
    subject_text = "Permit: {}".format(permit_clean) if permit_clean else "GeoProx proximity summary"

    def _apply_metadata(canvas_obj, _doc):
        canvas_obj.setTitle(doc_title)
        canvas_obj.setAuthor(author_name)
        canvas_obj.setSubject(subject_text)
        canvas_obj.setCreator("GeoProx API")
        keywords = ["outcome:{}".format(outcome_label)]
        if permit_clean:
            keywords.append("permit:{}".format(permit_clean))
        canvas_obj.setKeywords(keywords)

    flow: List[Any] = []
    if resolved_logo:
        flow.append(Image(str(resolved_logo), width=35 * mm, height=35 * mm, hAlign='LEFT'))
        flow.append(Spacer(1, 4 * mm))

    # Title
    flow.append(Paragraph("GeoProx - Proximity Summary", title))
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
            Paragraph(f"<b>Selection mode:</b> {selection_label}", body),
        ],
        [
            Paragraph(f"<b>Address:</b> {address or ''}", body),
            Paragraph(f"<b>Highway Authority:</b> {highway_authority or ''}", body),
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
    header = ["Category", "No", "<10m", "10-25m", "25-100m"]
    rows: List[List[Any]] = [header]

    def to_checks(bins: Dict[str, int]) -> List[str]:
        has10 = bins.get("<10m", 0) > 0
        has25 = bins.get("10-25m", 0) > 0
        has100 = bins.get("25-100m", 0) > 0
        no = not (has10 or has25 or has100)
        return ["X" if no else "", "X" if has10 else "", "X" if has25 else "", "X" if has100 else ""]

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

    # Details table (<=100 m)
    details_flow: List[Any] = []
    details_flow.append(Paragraph("<b>Found items within 100 m (nearest -> farthest)</b>", body))
    det_header = ["Distance (m)", "Category", "Name", "Lat", "Lon", "Address"]
    det_data: List[List[Any]] = [det_header]

    tuples: List[tuple] = []
    for item in details_rows or []:
        if isinstance(item, dict):
            try:
                tup = (
                    int(item.get('distance_m')),
                    item.get('category') or '',
                    item.get('name') or '',
                    float(item.get('lat') or 0.0),
                    float(item.get('lon') or 0.0),
                    item.get('address') or '',
                )
            except Exception:
                tup = None
        else:
            try:
                tup = (
                    int(item[0]),
                    item[1],
                    item[2],
                    float(item[3]),
                    float(item[4]),
                    item[5],
                )
            except Exception:
                tup = None
        if tup is not None:
            tuples.append(tup)

    tuples.sort(key=lambda x: x[0])
    log.info('PDF detail tuples: %s', tuples)

    for dist, cat, name, lat, lon, addr in tuples:
        det_data.append([
            dist,
            Paragraph(cat or '', body),
            Paragraph(name or "(unnamed)", body),
            f"{lat:.5f}",
            f"{lon:.5f}",
            Paragraph(addr or "", body),
        ])
    det_tbl = Table(det_data, repeatRows=1, colWidths=[24 * mm, 34 * mm, 46 * mm, 20 * mm, 20 * mm, 46 * mm])
    det_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    details_flow.append(det_tbl)

    flow.extend(details_flow)
    map_img_path = Path(map_image).expanduser().resolve() if map_image else None
    has_map_img = map_img_path.is_file() if map_img_path else False
    if has_map_img:
        flow.append(PageBreak())
        flow.append(Paragraph("Search map", heading))
        flow.append(Spacer(1, 4 * mm))
        try:
            reader = ImageReader(str(map_img_path))
            img_w, img_h = reader.getSize()
            max_w = doc.width
            max_h = doc.height
            scale = min(max_w / float(img_w), max_h / float(img_h))
            flow.append(Image(str(map_img_path), width=img_w * scale, height=img_h * scale, hAlign='CENTER'))
        except Exception:
            flow.append(Image(str(map_img_path), width=doc.width, hAlign='CENTER'))
        flow.append(Spacer(1, 6 * mm))
    elif map_image:
        # If a path was supplied but the file is missing, still surface the intent in the PDF.
        flow.append(PageBreak())
        flow.append(Paragraph("Search map (unavailable)", heading))
        flow.append(Paragraph(f"Map image not found at: {map_image}", body))
    doc.build(flow, onFirstPage=_apply_metadata, onLaterPages=_apply_metadata)


# ---------- Coordinator used by the API ----------
def run_geoprox_search(
    *,
    location: str,
    radius_m: int,
    categories: Optional[List[str]],
    permit: Optional[str],
    address: Optional[str] = None,
    highway_authority: Optional[str] = None,
    out_dir: Path,
    w3w_key: Optional[str] = None,
    max_results: int = 500,
    user_name: str = DEFAULT_USER,
    selection_mode: str = "point",
    polygon: Optional[List[Tuple[float, float]]] = None,
    extra_locations: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    # filter/normalise categories
    valid = set(OSM_FILTERS.keys())
    categories = [c for c in (categories or []) if c in valid]
    if not categories:
        categories = list(valid)

    # 1) Geocode
    lat, lon, disp = geocode_location_flex(location, w3w_key)
    display_center = _resolve_display_center(location, lat, lon, w3w_key, disp)

    effective_mode = (selection_mode or "point").lower()
    selection_polygon: Optional[Polygon] = None
    polygon_latlon: Optional[List[List[float]]] = None
    extra_radius = 0.0
    if effective_mode == "polygon" and polygon:
        try:
            vertices_lonlat: List[Tuple[float, float]] = []
            for pt in polygon:
                if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                    continue
                v_lat = float(pt[0])
                v_lon = float(pt[1])
                vertices_lonlat.append((v_lon, v_lat))
                extra_radius = max(extra_radius, _haversine_m(lat, lon, v_lat, v_lon))
            if len(vertices_lonlat) >= 3:
                candidate_poly = Polygon(vertices_lonlat)
                if not candidate_poly.is_valid:
                    candidate_poly = candidate_poly.buffer(0)
                if candidate_poly and not candidate_poly.is_empty:
                    selection_polygon = candidate_poly
                    polygon_latlon = [[float(lat_val), float(lon_val)] for lon_val, lat_val in vertices_lonlat]
            if selection_polygon is None:
                effective_mode = "point"
        except Exception as exc:
            log.warning("Failed to build selection polygon: %s", exc)
            selection_polygon = None
            effective_mode = "point"
    else:
        effective_mode = "point"

    reference_geom: BaseGeometry = selection_polygon if selection_polygon is not None else ShapelyPoint(lon, lat)
    query_radius = radius_m + int(math.ceil(extra_radius)) if effective_mode == "polygon" else radius_m

    # 2) Query Overpass
    qi = QueryInput(lat=lat, lon=lon, radius_m=query_radius, selected_categories=categories)
    data = run_overpass_resilient(qi)
    df = osm_elements_to_df(data)
    manual_df = _manual_locations_to_df(extra_locations, (lat, lon), query_radius)
    if not manual_df.empty:
        if df.empty:
            df = manual_df
        else:
            df = pd.concat([df, manual_df], ignore_index=True)
    df = _annotate_distances(df, (lat, lon), reference_geom=reference_geom)


    # 3) Summaries
    summary = summarise_by_bins(df, (lat, lon), reference_geom=reference_geom)
    details = build_details_rows(df, (lat, lon), reference_geom=reference_geom)
    details = sorted(details, key=lambda row: row[0])
    log.info('Detail rows for PDF: %s', len(details))

    # Cap number of detail rows processed/returned
    if max_results is not None:
        details = details[: int(max_results)]

    # 4) Artifacts (local)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _permit = permit or ""
    safe_permit = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in _permit)[:60] or "no_permit"
    map_html = out_dir / f"proximity_map_{safe_permit}.html"
    make_map(df, (lat, lon), radius_m, str(map_html), selection_mode=effective_mode, selection_geom=selection_polygon)
    map_image_path = out_dir / f"proximity_static_{safe_permit}.png"
    map_image_file = _render_static_map_image(
        df,
        center=(lat, lon),
        radius_m=radius_m,
        out_path=map_image_path,
        selection_mode=effective_mode,
        selection_geom=selection_polygon,
    )

    safe_name = safe_permit or "no_permit"
    pdf_path = out_dir / f"GeoProx - {safe_name}.pdf"
    _now = datetime.utcnow()
    _outcome = compute_outcome(summary)
    summary_payload = _build_summary_payload(
        summary_bins=summary,
        outcome=_outcome,
        center=display_center,
        radius=radius_m,
        permit=_permit,
        lat=lat,
        lon=lon,
    )
    if address:
        summary_payload["address"] = address
    if highway_authority:
        summary_payload["highway_authority"] = highway_authority
    summary_payload["user"] = user_name
    summary_payload["selection_mode"] = effective_mode
    if polygon_latlon:
        summary_payload["polygon"] = polygon_latlon
    generate_pdf_summary(
        display_center=display_center,
        summary_bins=summary,
        pdf_path=str(pdf_path),
        map_image=str(map_image_file) if map_image_file else None,
        details_rows=details,
        map_html=str(map_html),
        permit=_permit,
        address=address,
        highway_authority=highway_authority,
        user_name=user_name,
        search_dt=_now,
        outcome=_outcome,
        selection_mode=effective_mode,
    )

    # 5) JSON details for API
    details_rows_json = [
        {"distance_m": int(r[0]), "category": r[1], "name": r[2], "lat": float(r[3]), "lon": float(r[4]), "address": r[5]}
        for r in details
    ]
    selection_payload = {"mode": effective_mode, "centroid": {"lat": lat, "lon": lon}, "radius_m": radius_m}
    if effective_mode == "polygon":
        selection_payload["query_radius_m"] = query_radius
    if polygon_latlon:
        selection_payload["polygon"] = polygon_latlon
    if map_image_file:
        selection_payload["map_image_path"] = str(map_image_file)



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

            artifacts = {
                "pdf_url": pdf_url,
                "pdf_download_url": pdf_url,
                "pdf_path": str(pdf_path),
                "pdf_key": pdf_key,
                "map_url": html_url,
                "map_embed_url": html_url,
                "map_html_url": html_url,
                "map_html_path": str(map_html),
                "map_key": html_key,
                "map_image_path": str(map_image_file) if map_image_file else None,
            }
            artifacts = {k: v for k, v in artifacts.items() if v}

            return {
                "center": {"lat": lat, "lon": lon, "display": display_center},
                "radius_m": radius_m,
                "permit": _permit,
                "summary": summary_payload,
                "summary_bins": summary,
                "details_100m": details_rows_json,
                "artifacts": artifacts,
                "selection": selection_payload,
            }
        except Exception as e:
            # Fall through to local paths with a warning
            return {
                "center": {"lat": lat, "lon": lon, "display": display_center},
                "radius_m": radius_m,
                "permit": _permit,
                "summary": summary_payload,
                "summary_bins": summary,
                "details_100m": details_rows_json,
                "artifacts": {"pdf_path": str(pdf_path), "map_html_path": str(map_html), "map_image_path": str(map_image_file) if map_image_file else None},
                "warning": f"S3 upload failed: {e}",
                "selection": selection_payload,
            }

    # 7) No S3 configured â†’ local paths
    return {
        "center": {"lat": lat, "lon": lon, "display": display_center},
        "radius_m": radius_m,
        "permit": _permit,
        "summary": summary_payload,
        "summary_bins": summary,
        "details_100m": details_rows_json,
        "artifacts": {"pdf_path": str(pdf_path), "map_html_path": str(map_html), "map_image_path": str(map_image_file) if map_image_file else None},
        "selection": selection_payload,
    }



