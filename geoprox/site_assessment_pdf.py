from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_site_assessment_pdf(out_path: Path, *, permit_ref: str, form_data: Dict[str, str]) -> Path:
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
        fontSize = 10,
        textColor = colors.HexColor("#5f6c7b"),
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize = 10,
        textColor = colors.HexColor("#1f2c3a"),
    )
    value_style = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontSize = 11,
        textColor = colors.HexColor("#0b1724"),
        leading = 14,
    )

    story = []
    story.append(Paragraph("Site Assessment Report", title_style))
    story.append(Paragraph(f"Permit reference: {permit_ref}", subtitle_style))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        subtitle_style,
    ))
    story.append(Spacer(1, 10 * mm))

    sections = [
        ("Inspection Date", form_data.get("inspection_date", "")),
        ("Inspector Name", form_data.get("inspector_name", "")),
        ("Inspector Email", form_data.get("inspector_email", "")),
        ("Contact Number", form_data.get("contact_number", "")),
        ("On-Site Contact", form_data.get("onsite_contact", "")),
        ("Weather Conditions", form_data.get("weather", "")),
        ("Access Notes", form_data.get("access_notes", "")),
        ("Site Conditions", form_data.get("site_conditions", "")),
        ("Hazards Identified", form_data.get("hazards", "")),
        ("Actions Required", form_data.get("actions_required", "")),
        ("Overall Risk Level", form_data.get("risk_level", "")),
        ("Assessment Outcome", form_data.get("site_outcome", "")),
        ("Additional Notes", form_data.get("additional_notes", "")),
    ]

    table_data = []
    for label, value in sections:
        table_data.append([
            Paragraph(label, label_style),
            Paragraph(value or "-", value_style),
        ])

    table = Table(table_data, colWidths=[55 * mm, None])
    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5fa")),
        ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#c3c9d4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    table.setStyle(table_style)
    story.append(table)

    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Signature", label_style))
    story.append(Spacer(1, 12 * mm))
    story.append(Table(
        [["", ""]],
        colWidths=[70 * mm, None],
        style=TableStyle([
            ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.HexColor("#647286")),
            ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.HexColor("#647286")),
        ]),
    ))

    doc.build(story)
    return out_path
