from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DETAIL_FIELDS = [
    ("Utility Type", "utility_type"),
    ("Date of Assessment", "assessment_date"),
    ("Location of Work", "location_of_work"),
    ("Permit Number", "permit_number"),
    ("Work Order Reference", "work_order_ref"),
    ("Excavation Site Number", "excavation_site_number"),
    ("Address", "site_address"),
    ("Post Code", "site_postcode"),
    ("Highway Authority", "highway_authority"),
    ("Works Type", "works_type"),
    ("Surface Location", "surface_location"),
    ("What Three Words", "what_three_words"),
]

QUESTION_ROWS = [
    ("Q1", "q1_asbestos", "Are there any signs of asbestos fibres or asbestos containing materials in the excavation?",
     "If asbestos or signs of asbestos are identified the excavation does not qualify for a risk assessment."),
    ("Q2", "q2_binder_shiny", "Is the binder shiny, sticky to touch and is there an organic odour?",
     "All three (shiny, sticky and creosote odour) required for a yes."),
    ("Q3", "q3_spray_pak", "Spray PAK across the profile of asphalt / bitumen. Does the paint change colour to Band 1 or 2?",
     "Ensure to spray a line across the full depth of the bituminous layer. Refer to PAK colour chart."),
    ("Q4", "q4_soil_colour", "Is the soil stained an unusual colour (such as orange, black, blue or green)?",
     "Compare the discolouration of soil to other parts of the excavation."),
    ("Q5", "q5_water_sheen", "If there is water or moisture in the excavation, is there a rainbow sheen or colouration to the water?",
     "Looking for signs of oil in the excavation."),
    ("Q6", "q6_pungent_odour", "Are there any pungent odours to the material?",
     "Think bleach, garlic, egg, tar, gas or other strong smells."),
    ("Q7", "q7_litmus_change", "Use litmus paper on wet soil, does it change colour to high or low pH?",
     "Refer to the pH colour chart."),
]

RESULT_ROWS = [
    ("Bituminous", "result_bituminous"),
    ("Sub-base", "result_sub_base"),
]


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
        fontSize=10,
        textColor=colors.HexColor("#5f6c7b"),
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
    table_header_style = ParagraphStyle(
        "Header",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#1f2c3a"),
    )

    story = []
    story.append(Paragraph("Site Assessment Report", title_style))
    story.append(Paragraph(f"Permit reference: {permit_ref}", subtitle_style))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        subtitle_style,
    ))
    story.append(Spacer(1, 8 * mm))

    # Details table
    details_data = []
    for label, key in DETAIL_FIELDS:
        value = form_data.get(key) or "-"
        details_data.append([
            Paragraph(label, label_style),
            Paragraph(value, value_style),
        ])
    details_table = Table(details_data, colWidths=[55 * mm, None])
    details_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 8 * mm))

    # Questions table
    question_data = [[
        Paragraph("Ref", table_header_style),
        Paragraph("Question", table_header_style),
        Paragraph("Answer", table_header_style),
        Paragraph("Notes", table_header_style),
    ]]
    for ref, key, question, note in QUESTION_ROWS:
        answer = form_data.get(key) or "-"
        question_data.append([
            Paragraph(ref, value_style),
            Paragraph(question, value_style),
            Paragraph(answer, value_style),
            Paragraph(note, value_style),
        ])
    question_table = Table(question_data, colWidths=[15 * mm, 75 * mm, 30 * mm, None])
    question_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe6f0")),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(question_table)
    story.append(Spacer(1, 8 * mm))

    # Results
    results_data = []
    for label, key in RESULT_ROWS:
        value = form_data.get(key) or "-"
        results_data.append([
            Paragraph(label, label_style),
            Paragraph(value, value_style),
        ])
    assess_table = Table(results_data, colWidths=[55 * mm, None])
    assess_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c3cbd6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7dde7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(assess_table)
    story.append(Spacer(1, 6 * mm))

    assessor_name = form_data.get("assessor_name") or "-"
    story.append(Paragraph(f"Assessor name: {assessor_name}", value_style))
    if form_data.get("site_outcome"):
        story.append(Paragraph(f"Assessment outcome: {form_data.get('site_outcome')}", value_style))
    if form_data.get("site_notes"):
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Additional notes:", label_style))
        story.append(Paragraph(form_data.get("site_notes"), value_style))

    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Signature", label_style))
    story.append(Spacer(1, 12 * mm))
    story.append(Table([["", ""]], colWidths=[70 * mm, None], style=TableStyle([
        ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.HexColor("#647286")),
        ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.HexColor("#647286")),
    ])))

    doc.build(story)
    return out_path
