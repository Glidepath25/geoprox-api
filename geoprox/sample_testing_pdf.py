from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ENTRY_KEYS = [
    ("sample_1", "Sample 1"),
    ("sample_2", "Sample 2"),
]

DETERMINANTS = [
    ("coal_tar", "Coal Tar (determined by BaP)"),
    ("tph", "Total Petroleum Hydrocarbons (C6-C40)"),
    ("heavy_metal", "Heavy Metal"),
    ("asbestos", "Asbestos"),
    ("other", "Other"),
]

_DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "static" / "geoprox-logo.png"


def _safe_logo_path(logo_path: Optional[Path]) -> Optional[Path]:
    candidate = logo_path or _DEFAULT_LOGO
    if candidate and candidate.exists():
        return candidate
    return None


def _append_attachments(story, attachments: Sequence[Tuple[str, Path]], heading_style: ParagraphStyle, value_style: ParagraphStyle) -> None:
    if not attachments:
        return
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Photo evidence", heading_style))
    for label, path in attachments:
        if not path.exists():
            continue
        story.append(Spacer(1, 3 * mm))
        title = label or path.name
        story.append(Paragraph(title, value_style))
        try:
            img = Image(str(path))
            img.hAlign = "LEFT"
            img._restrictSize(160 * mm, 120 * mm)
            story.append(img)
        except Exception:
            story.append(Paragraph(f"[Unable to embed image: {path.name}]", value_style))


def _material_label(value: Optional[str]) -> str:
    mapping = {
        "bituminous": "Bituminous",
        "sub_base": "Sub-base",
    }
    return mapping.get((value or "").lower(), value or "-")


def _lab_result_label(value: Optional[str]) -> str:
    mapping = {
        "green": "Green",
        "red": "Red",
    }
    return mapping.get((value or "").lower(), value or value or "-")


def _boolean_label(value: Optional[str]) -> str:
    lowered = (value or "").strip().lower()
    if lowered in {"yes", "true", "present"}:
        return "Yes"
    if lowered in {"no", "false", "absent"}:
        return "No"
    return value or "-"


def generate_sample_testing_pdf(
    out_path: Path,
    *,
    permit_ref: str,
    form_data: Dict[str, str],
    attachments: Optional[Sequence[Tuple[str, Path]]] = None,
    logo_path: Optional[Path] = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontSize = 20
    title_style.leading = 24
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#5f6c7b"),
    )
    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#1f2c3a"),
        leading=14,
        spaceAfter=2,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1f2c3a"),
    )
    value_style = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#0b1724"),
        leading=14,
    )

    story = []
    logo = _safe_logo_path(logo_path)
    if logo:
        logo_img = Image(str(logo))
        logo_img._restrictSize(36 * mm, 36 * mm)
        logo_img.hAlign = 'LEFT'
        story.append(logo_img)
        story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Sample Testing Report", title_style))
    story.append(Paragraph(f"Permit reference: {permit_ref}", subtitle_style))
    story.append(
        Paragraph(
            f"Generated: {datetime.utcnow().strftime('%d/%m/%y %H:%M')} UTC",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 8 * mm))

    for key, label in ENTRY_KEYS:
        story.append(Paragraph(label, heading_style))
        sample_data = {
            "Sample number": form_data.get(f"{key}_number") or "-",
            "Material sampled": _material_label(form_data.get(f"{key}_material")),
            "Lab analysis": _lab_result_label(form_data.get(f"{key}_lab_result")),
        }
        sample_table = Table(
            [
                [Paragraph(name, label_style), Paragraph(str(value), value_style)]
                for name, value in sample_data.items()
            ],
            colWidths=[55 * mm, None],
        )
        sample_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
                    ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(sample_table)
        story.append(Spacer(1, 4 * mm))

        determinant_rows = [
            [
                Paragraph("Determinant", label_style),
                Paragraph("Present", label_style),
                Paragraph("Concentration if Red (mg/kg)", label_style),
            ]
        ]
        for det_key, det_label in DETERMINANTS:
            present_value = _boolean_label(form_data.get(f"{key}_{det_key}_present"))
            concentration_value = form_data.get(f"{key}_{det_key}_concentration") or "-"
            determinant_rows.append(
                [
                    Paragraph(det_label, value_style),
                    Paragraph(present_value, value_style),
                    Paragraph(concentration_value, value_style),
                ]
            )
        det_table = Table(determinant_rows, colWidths=[70 * mm, 25 * mm, None])
        det_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe6f0")),
                    ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(det_table)
        story.append(Spacer(1, 6 * mm))

    summary_fields = [
        ("Sampled by", form_data.get("sampled_by_name") or "-"),
        ("Results recorded by", form_data.get("results_recorded_by") or "-"),
    ]
    summary_table = Table(
        [[Paragraph(label, label_style), Paragraph(value, value_style)] for label, value in summary_fields],
        colWidths=[55 * mm, None],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary_table)

    if form_data.get("sample_comments"):
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Comments", heading_style))
        story.append(Paragraph(form_data.get("sample_comments"), value_style))

    _append_attachments(story, attachments or [], heading_style, value_style)

    doc.build(story)
    return out_path
