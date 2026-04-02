import streamlit as st
import fitz  # PyMuPDF
import json
import os
import google.generativeai as genai
import io
from PIL import Image
from datetime import datetime

# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="UrbanRoof AI Builder | DDR Generator",
    layout="wide",
    page_icon="🏢"
)

# ==========================================
# CONSTANTS
# ==========================================
# Keywords in model names that mean "not a text-generation model"
_EXCLUDE = ["deep-research", "embedding", "aqa", "vision", "imagen", "tts", "transcribe"]
BRAND_BLUE   = colors.HexColor("#2980B9")
BRAND_DARK   = colors.HexColor("#1A5276")
BRAND_LIGHT  = colors.HexColor("#D6EAF8")
BRAND_ORANGE = colors.HexColor("#E67E22")
BRAND_RED    = colors.HexColor("#C0392B")
BRAND_GREEN  = colors.HexColor("#1E8449")
SEVERITY_COLORS = {
    "low":      colors.HexColor("#1E8449"),
    "medium":   colors.HexColor("#E67E22"),
    "high":     colors.HexColor("#C0392B"),
    "critical": colors.HexColor("#7B241C"),
    "moderate": colors.HexColor("#E67E22"),
}

# ==========================================
# HELPER — PDF EXTRACTION
# ==========================================
def extract_pdf_data(uploaded_files):
    combined_text = ""
    extracted_images = {}

    for file in uploaded_files:
        try:
            pdf_bytes = file.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            combined_text += f"\n--- Start of Document: {file.name} ---\n"

            for page_num in range(len(doc)):
                page = doc[page_num]
                combined_text += f"\n[Page {page_num + 1}]\n{page.get_text('text')}"

                for img_idx, img in enumerate(page.get_images(full=True)):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    if base_image["width"] < 100 or base_image["height"] < 100:
                        continue
                    image_key = f"{file.name}_Page{page_num+1}_Img{img_idx+1}"
                    extracted_images[image_key] = base_image["image"]
                    combined_text += f"\n[IMAGE EXTRACTED HERE: Reference ID -> {image_key}]\n"

            combined_text += f"\n--- End of Document: {file.name} ---\n"
        except Exception as e:
            st.error(f"Error reading {file.name}: {e}")

    return combined_text, extracted_images


# ==========================================
# HELPER — GEMINI API CALL
# ==========================================
def get_best_model(api_key: str) -> str:
    """
    Ask the API which models are actually available for this key, filter out
    non-text-generation models by name, then pick the best one.
    Preference: flash (free-tier friendly) > pro, newer version > older.
    """
    genai.configure(api_key=api_key)
    try:
        candidates = []
        for m in genai.list_models():
            if "generateContent" not in m.supported_generation_methods:
                continue
            name = m.name.replace("models/", "")
            if not name.startswith("gemini-"):
                continue
            if any(kw in name.lower() for kw in _EXCLUDE):
                continue
            candidates.append(name)

        if not candidates:
            raise ValueError("No suitable models found via list_models()")

        # Split into flash vs pro pools; prefer non-preview within each pool
        def score(name):
            s = 0
            if "flash" in name:   s += 100
            if "preview" not in name: s += 50
            if "latest"  in name: s += 20
            # Newer major version numbers score higher (e.g. 2.0 > 1.5)
            import re
            nums = re.findall(r"(\d+)\.(\d+)", name)
            if nums:
                s += int(nums[0][0]) * 10 + int(nums[0][1])
            return s

        candidates.sort(key=score, reverse=True)
        return candidates[0]

    except Exception:
        # Hard fallback: try common names directly
        for fallback in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]:
            try:
                genai.GenerativeModel(fallback).generate_content(
                    "OK", generation_config=genai.GenerationConfig(max_output_tokens=1)
                )
                return fallback
            except Exception as e:
                if "429" in str(e):
                    return fallback
        return "gemini-pro"


def generate_ddr_report(text_context, api_key):
    genai.configure(api_key=api_key)

    system_prompt = """
You are an expert Property Diagnostic AI working for UrbanRoof Private Limited.
Your job is to read building inspection and thermal reports and produce a highly detailed
Detailed Diagnostic Report (DDR) in JSON.

CRITICAL RULES:
1. NEVER invent facts not present in the documents for observations, areas, or property details.
2. If information conflicts, mention the conflict explicitly.
3. For 'Relevant_Image_Captions' use the EXACT Reference IDs from [IMAGE EXTRACTED HERE] markers.
4. Use simple, client-friendly language.
5. For Severity_Table rows, extract from the tabular severity section in the report.
6. For Missing_Info_Table, list each missing item as a row with Missing_Item, Status, Impact.

RECOMMENDED ACTIONS — MANDATORY RULE:
- You MUST always populate Recommended_Actions with practical repair steps.
- First, try to extract them from the document (look for sections titled "RECOMMENDED ACTIONS",
  "SUGGESTED THERAPIES", "ANALYSIS & SUGGESTIONS", "REPAIR STEPS", or numbered priority lists).
- If the document does NOT contain repair steps, you MUST generate them yourself based on the
  Area_wise_Observations and Probable_Root_Causes you identified. Use your expert knowledge of
  building repair, waterproofing, and civil engineering to recommend the correct actions.
- NEVER leave Recommended_Actions empty or write "Not Available". This field is always required.
- Each action must have: Priority_Label, What_to_Do, How_to_Do_It, Materials, Expected_Outcome.
- Typical issues and their standard repair actions:
    * Tile joint gaps / hollowness → Re-grouting with polymer mortar, Nahani trap sealing
    * Skirting dampness → Waterproof treatment, brickbat coba repair
    * External wall cracks → V-cut crack filling, waterproof paint
    * Plumbing leaks → Joint tightening, pipe replacement
    * RCC cracks → Epoxy injection, anti-corrosion treatment
    * Parking ceiling seepage → Slab waterproofing from above, rebar treatment
    * Efflorescence → Salt removal, anti-efflorescence primer, repainting
    * Algae/fungus → Anti-fungal wash, waterproof exterior paint

OUTPUT: Return ONLY a strictly valid JSON object with this exact schema — no markdown fences:
{
  "Property_Details": {
    "Address": "...",
    "Inspection_Date": "...",
    "Inspected_By": "...",
    "Property_Type": "...",
    "Floors": "...",
    "Previous_Audit": "..."
  },
  "Stats": {
    "Affected_Areas": "number or Not Available",
    "Overall_Severity": "High / Medium / Low / Critical",
    "Inspection_Score": "e.g. 85.71%"
  },
  "Property_Issue_Summary": "Detailed narrative summary.",
  "Primary_Issues": ["Issue 1", "Issue 2"],
  "Area_wise_Observations": [
    {
      "Area_Name": "Name of area",
      "Observation": "Description of defect",
      "Source_Exposed_Side": "Where the water/issue comes from",
      "Thermal_Reading": "Hotspot / Coldspot / Delta-T / Emissivity or Not Available",
      "Thermal_Interpretation": "What the thermal data means or Not Available",
      "Relevant_Image_Captions": ["Exact Reference ID or empty list"]
    }
  ],
  "Probable_Root_Causes": [
    {
      "Area_Group": "Area or group name",
      "Root_Cause": "Explanation",
      "Mechanism": ["Step 1", "Step 2", "Step 3"]
    }
  ],
  "Severity_Table": [
    {
      "Area": "Area name",
      "Issue": "Issue description",
      "Severity": "High / Medium / Low / Critical / Moderate",
      "Score": "numeric score 1-10",
      "Action_Timeframe": "Immediate / Within 1 Month / etc."
    }
  ],
  "Overall_Severity_Assessment": {
    "Level": "High / Medium / Low / Critical",
    "Reasoning": "Full reasoning paragraph."
  },
  "Recommended_Actions": [
    {
      "Priority_Label": "Priority 1 – Area / Issue Name",
      "What_to_Do": "Clear description of the repair task",
      "How_to_Do_It": "Step-by-step method",
      "Materials": "List of materials / products",
      "Expected_Outcome": "What will be fixed after this action"
    }
  ],
  "Additional_Notes": ["Note 1", "Note 2"],
  "Missing_Info_Table": [
    {
      "Missing_Item": "What is missing",
      "Status": "Not Available",
      "Impact": "How this affects the diagnosis"
    }
  ]
}
"""

    # Truncate to ~80,000 chars (~20k tokens) to stay within free-tier limits
    MAX_CHARS = 80_000
    if len(text_context) > MAX_CHARS:
        st.warning(f"⚠️ Document text truncated from {len(text_context):,} to {MAX_CHARS:,} characters to stay within free-tier token limits.")
        text_context = text_context[:MAX_CHARS]

    import time

    selected_model = get_best_model(api_key)
    st.info(f"🤖 Using model: `{selected_model}`")

    for attempt in range(3):
        try:
            model = genai.GenerativeModel(
                model_name=selected_model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                )
            )
            prompt = (
                "Here is the extracted document text from the inspection and thermal reports. "
                "Generate the complete JSON DDR. Pay special attention to extracting ALL "
                "Recommended_Actions — they are usually under a numbered priority list "
                "with headings like 'Priority 1', 'Priority 2', etc.\n\n"
                + text_context
            )
            response = model.generate_content(prompt)
            raw = response.text.strip()
            # Strip markdown fences if model added them despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < 2:
                wait = 30 * (attempt + 1)
                st.warning(f"⏳ Rate limit hit — waiting {wait}s before retry (attempt {attempt+1}/3)...")
                time.sleep(wait)
                continue
            st.error(f"Gemini API error: {e}")
            return None
    return None


# ==========================================
# HELPERS
# ==========================================
def safe(text):
    """Encode/decode for latin-1 safety (not needed for ReportLab but kept for safety)."""
    if text is None:
        return "Not Available"
    return str(text)

def ensure_list(item):
    if isinstance(item, str):
        return [] if item.strip().lower() == "not available" else [item]
    return item if isinstance(item, list) else []

def sev_color(level: str):
    return SEVERITY_COLORS.get(str(level).lower(), colors.grey)


# ==========================================
# REPORTLAB — CUSTOM FLOWABLES
# ==========================================
class ColoredLine(Flowable):
    def __init__(self, color, width=None, thickness=1.5):
        super().__init__()
        self.color = color
        self._width = width
        self.thickness = thickness

    def wrap(self, available_width, available_height):
        self.width = self._width or available_width
        return self.width, self.thickness + 2

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)


# ==========================================
# REPORTLAB — STYLES
# ==========================================
def make_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=22,
        textColor=BRAND_DARK, spaceAfter=6, alignment=TA_CENTER
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=11,
        textColor=colors.grey, spaceAfter=4, alignment=TA_CENTER
    )
    styles["section_header"] = ParagraphStyle(
        "section_header", fontName="Helvetica-Bold", fontSize=13,
        textColor=colors.white, spaceAfter=6, spaceBefore=12,
        leftIndent=8
    )
    styles["area_header"] = ParagraphStyle(
        "area_header", fontName="Helvetica-Bold", fontSize=11,
        textColor=BRAND_DARK, spaceAfter=4, spaceBefore=8
    )
    styles["body"] = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5,
        textColor=colors.HexColor("#222222"), spaceAfter=3,
        leading=14, alignment=TA_JUSTIFY
    )
    styles["bullet"] = ParagraphStyle(
        "bullet", fontName="Helvetica", fontSize=9.5,
        textColor=colors.HexColor("#222222"), spaceAfter=2,
        leading=13, leftIndent=12, bulletIndent=0
    )
    styles["label"] = ParagraphStyle(
        "label", fontName="Helvetica-Bold", fontSize=9,
        textColor=BRAND_DARK, spaceAfter=1
    )
    styles["small"] = ParagraphStyle(
        "small", fontName="Helvetica", fontSize=8,
        textColor=colors.grey, leading=11
    )
    styles["priority_title"] = ParagraphStyle(
        "priority_title", fontName="Helvetica-Bold", fontSize=10,
        textColor=colors.white, spaceAfter=0
    )
    styles["priority_body"] = ParagraphStyle(
        "priority_body", fontName="Helvetica", fontSize=9,
        textColor=colors.HexColor("#111111"), spaceAfter=2, leading=13
    )
    styles["cover_label"] = ParagraphStyle(
        "cover_label", fontName="Helvetica-Bold", fontSize=10,
        textColor=BRAND_DARK, spaceAfter=2
    )
    styles["cover_value"] = ParagraphStyle(
        "cover_value", fontName="Helvetica", fontSize=10,
        textColor=colors.HexColor("#222222"), spaceAfter=2
    )
    return styles


# ==========================================
# REPORTLAB — SECTION HEADER BAND
# ==========================================
def section_header_table(title_text, styles):
    """Returns a blue-background section-header table row."""
    p = Paragraph(title_text, styles["section_header"])
    t = Table([[p]], colWidths=["100%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


# ==========================================
# REPORTLAB — PDF BUILDER
# ==========================================
def build_pdf(report_data: dict, extracted_images: dict) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 2 * cm
    COL_W = PAGE_W - 2 * MARGIN

    styles = make_styles()

    # ---- Header / Footer callbacks ----
    def on_page(canvas, doc):
        canvas.saveState()
        # Header (skip cover page = page 1)
        if doc.page > 1:
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(BRAND_BLUE)
            canvas.drawString(MARGIN, PAGE_H - 1.2 * cm,
                              "UrbanRoof | Detailed Diagnostic Report")
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.grey)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.2 * cm,
                                   "www.urbanroof.in")
            canvas.setStrokeColor(BRAND_BLUE)
            canvas.setLineWidth(0.8)
            canvas.line(MARGIN, PAGE_H - 1.4 * cm, PAGE_W - MARGIN, PAGE_H - 1.4 * cm)

        # Footer
        if doc.page > 1:
            canvas.setStrokeColor(colors.lightgrey)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, 1.4 * cm, PAGE_W - MARGIN, 1.4 * cm)
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.grey)
            canvas.drawCentredString(PAGE_W / 2, 0.9 * cm,
                                     f"Page {doc.page}  |  Generated by UrbanRoof AI Builder  |  {datetime.now().strftime('%d %B %Y')}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=2.2 * cm, bottomMargin=2 * cm,
    )

    story = []

    # ============================================================
    # COVER PAGE
    # ============================================================
    story.append(Spacer(1, 3 * cm))

    # Logo / brand strip
    logo_table = Table(
        [[Paragraph("🏢  UrbanRoof Private Limited", ParagraphStyle(
            "brand", fontName="Helvetica-Bold", fontSize=16,
            textColor=colors.white, alignment=TA_CENTER
        ))]],
        colWidths=[COL_W]
    )
    logo_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(logo_table)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("DETAILED DIAGNOSTIC REPORT", styles["title"]))
    story.append(Paragraph("Property Health Assessment", styles["subtitle"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(ColoredLine(BRAND_BLUE, thickness=2))
    story.append(Spacer(1, 0.6 * cm))

    # Property details table
    pd_raw = report_data.get("Property_Details", {})
    stats   = report_data.get("Stats", {})

    cover_data = [
        [Paragraph("Field", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
         Paragraph("Details", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white))],
        [Paragraph("Inspection Date", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Inspection_Date", "Not Available")), styles["cover_value"])],
        [Paragraph("Property Type", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Property_Type", "Not Available")), styles["cover_value"])],
        [Paragraph("Address", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Address", "Not Available")), styles["cover_value"])],
        [Paragraph("Floors", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Floors", "Not Available")), styles["cover_value"])],
        [Paragraph("Inspected By", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Inspected_By", "Not Available")), styles["cover_value"])],
        [Paragraph("Previous Audit", styles["cover_label"]),
         Paragraph(safe(pd_raw.get("Previous_Audit", "Not Available")), styles["cover_value"])],
    ]
    ct = Table(cover_data, colWidths=[0.35 * COL_W, 0.65 * COL_W])
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4DE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(ct)
    story.append(Spacer(1, 0.6 * cm))

    # Stats bar
    sev_level = safe(stats.get("Overall_Severity", "—"))
    sev_c = sev_color(sev_level)
    stat_data = [[
        Paragraph(f"<b>Affected Areas</b><br/>{safe(stats.get('Affected_Areas', '—'))}", 
                  ParagraphStyle("sc", fontName="Helvetica", fontSize=10, textColor=colors.white, alignment=TA_CENTER, leading=14)),
        Paragraph(f"<b>Overall Severity</b><br/>{sev_level}",
                  ParagraphStyle("sc", fontName="Helvetica", fontSize=10, textColor=colors.white, alignment=TA_CENTER, leading=14)),
        Paragraph(f"<b>Inspection Score</b><br/>{safe(stats.get('Inspection_Score', '—'))}",
                  ParagraphStyle("sc", fontName="Helvetica", fontSize=10, textColor=colors.white, alignment=TA_CENTER, leading=14)),
    ]]
    st_t = Table(stat_data, colWidths=[COL_W / 3] * 3)
    st_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), BRAND_BLUE),
        ("BACKGROUND", (1, 0), (1, 0), sev_c),
        ("BACKGROUND", (2, 0), (2, 0), BRAND_GREEN),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(st_t)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(
        f"Prepared by: UrbanRoof AI Builder  |  Date: {datetime.now().strftime('%B %d, %Y')}",
        styles["subtitle"]
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("UrbanRoof Private Limited  |  Property Health Assessment  |  www.urbanroof.in",
                            styles["small"]))

    story.append(PageBreak())

    # ============================================================
    # 1. PROPERTY ISSUE SUMMARY
    # ============================================================
    story.append(section_header_table("1.  Property Issue Summary", styles))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(safe(report_data.get("Property_Issue_Summary", "Not Available")), styles["body"]))
    story.append(Spacer(1, 0.2 * cm))

    primary_issues = ensure_list(report_data.get("Primary_Issues"))
    if primary_issues:
        story.append(Paragraph("Primary Issues Identified:", styles["label"]))
        for iss in primary_issues:
            story.append(Paragraph(f"• {safe(iss)}", styles["bullet"]))

    story.append(Spacer(1, 0.4 * cm))

    # ============================================================
    # 2. AREA-WISE OBSERVATIONS
    # ============================================================
    story.append(section_header_table("2.  Area-wise Observations", styles))
    story.append(Spacer(1, 0.3 * cm))

    areas = report_data.get("Area_wise_Observations", [])
    for area in areas:
        area_name = safe(area.get("Area_Name", "Unknown Area"))
        story.append(Paragraph(f"2.  {area_name}", styles["area_header"]))

        rows = []
        field_map = [
            ("Observation (Affected Side)", area.get("Observation", "Not Available")),
            ("Source / Exposed Side",       area.get("Source_Exposed_Side", "Not Available")),
            ("Thermal Reading",             area.get("Thermal_Reading", "Not Available")),
            ("Thermal Interpretation",      area.get("Thermal_Interpretation", "Not Available")),
        ]
        for label, value in field_map:
            rows.append([
                Paragraph(label, styles["label"]),
                Paragraph(safe(value), styles["body"]),
            ])

        # Visual evidence row
        img_refs = ensure_list(area.get("Relevant_Image_Captions"))
        ve_text = ", ".join(img_refs) if img_refs else "Not Available"
        rows.append([
            Paragraph("Visual Evidence", styles["label"]),
            Paragraph(ve_text, styles["body"]),
        ])

        tbl = Table(rows, colWidths=[0.28 * COL_W, 0.72 * COL_W])
        tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [BRAND_LIGHT, colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4DE")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.25 * cm))

        # Images — use BytesIO directly so no temp files are needed
        found_images = False
        for ref in img_refs:
            if ref in extracted_images:
                found_images = True
                try:
                    img_obj = Image.open(io.BytesIO(extracted_images[ref])).convert("RGB")
                    img_buf = io.BytesIO()
                    img_obj.save(img_buf, format="JPEG", quality=85)
                    img_buf.seek(0)
                    img_w = min(COL_W * 0.48, 8 * cm)
                    rl_img = RLImage(img_buf, width=img_w, height=img_w * 0.65)
                    story.append(rl_img)
                    story.append(Spacer(1, 0.15 * cm))
                except Exception:
                    pass

        story.append(Spacer(1, 0.3 * cm))

    # ============================================================
    # 3. PROBABLE ROOT CAUSE
    # ============================================================
    story.append(PageBreak())
    story.append(section_header_table("3.  Probable Root Cause", styles))
    story.append(Spacer(1, 0.3 * cm))

    root_causes = report_data.get("Probable_Root_Causes", [])
    if isinstance(root_causes, str):
        story.append(Paragraph(safe(root_causes), styles["body"]))
    else:
        for rc in root_causes:
            story.append(Paragraph(f"■  {safe(rc.get('Area_Group', ''))}", styles["label"]))
            story.append(Paragraph(safe(rc.get("Root_Cause", "Not Available")), styles["body"]))
            steps = ensure_list(rc.get("Mechanism"))
            if steps:
                story.append(Paragraph("Mechanism:", ParagraphStyle(
                    "mech_label", fontName="Helvetica-BoldOblique", fontSize=9,
                    textColor=BRAND_DARK, spaceAfter=2
                )))
                for i, step in enumerate(steps, 1):
                    story.append(Paragraph(f"{i}.  {safe(step)}", styles["bullet"]))
            story.append(Spacer(1, 0.25 * cm))

    # ============================================================
    # 4. SEVERITY ASSESSMENT
    # ============================================================
    story.append(Spacer(1, 0.3 * cm))
    story.append(section_header_table("4.  Severity Assessment", styles))
    story.append(Spacer(1, 0.3 * cm))

    sev_table_data = report_data.get("Severity_Table", [])
    if sev_table_data:
        header = [
            Paragraph("Area", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Issue", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Severity", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Score", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Action", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        ]
        sev_rows = [header]
        sev_row_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ]
        for i, row in enumerate(sev_table_data, 1):
            sev_val = safe(row.get("Severity", ""))
            sc = sev_color(sev_val)
            sev_rows.append([
                Paragraph(safe(row.get("Area", "—")), styles["body"]),
                Paragraph(safe(row.get("Issue", "—")), styles["body"]),
                Paragraph(sev_val, ParagraphStyle(
                    "sev_cell", fontName="Helvetica-Bold", fontSize=9,
                    textColor=colors.white, alignment=TA_CENTER
                )),
                Paragraph(safe(row.get("Score", "—")), ParagraphStyle(
                    "score_cell", fontName="Helvetica-Bold", fontSize=9,
                    textColor=BRAND_DARK, alignment=TA_CENTER
                )),
                Paragraph(safe(row.get("Action_Timeframe", "—")), styles["body"]),
            ])
            sev_row_styles.append(("BACKGROUND", (2, i), (2, i), sc))
            if i % 2 == 0:
                sev_row_styles.append(("BACKGROUND", (0, i), (1, i), BRAND_LIGHT))
                sev_row_styles.append(("BACKGROUND", (3, i), (-1, i), BRAND_LIGHT))

        s_tbl = Table(sev_rows, colWidths=[0.22*COL_W, 0.28*COL_W, 0.14*COL_W, 0.1*COL_W, 0.26*COL_W])
        s_tbl.setStyle(TableStyle(sev_row_styles + [
            ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4DE")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(s_tbl)
        story.append(Spacer(1, 0.3 * cm))

    overall_sev = report_data.get("Overall_Severity_Assessment", {})
    if isinstance(overall_sev, dict):
        story.append(Paragraph(
            f"<b>Severity Reasoning:</b>  {safe(overall_sev.get('Reasoning', 'Not Available'))}",
            styles["body"]
        ))

    # ============================================================
    # 5. RECOMMENDED ACTIONS
    # ============================================================
    story.append(PageBreak())
    story.append(section_header_table("5.  Recommended Actions", styles))
    story.append(Spacer(1, 0.3 * cm))

    actions = report_data.get("Recommended_Actions", [])
    if not actions or (isinstance(actions, str) and "not available" in actions.lower()):
        story.append(Paragraph("No recommended actions could be generated for this report.", styles["body"]))
    else:
        for action in actions:
            if isinstance(action, str):
                story.append(Paragraph(f"• {safe(action)}", styles["bullet"]))
                continue

            # Priority header band
            priority_label = safe(action.get("Priority_Label", "Action Item"))
            ph = Table(
                [[Paragraph(priority_label, styles["priority_title"])]],
                colWidths=[COL_W]
            )
            ph.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_ORANGE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ]))

            # Action detail table
            action_fields = [
                ("What to Do",       action.get("What_to_Do", "Not Available")),
                ("How to Do It",     action.get("How_to_Do_It", "Not Available")),
                ("Materials",        action.get("Materials", "Not Available")),
                ("Expected Outcome", action.get("Expected_Outcome", "Not Available")),
            ]
            action_rows = [
                [Paragraph(lbl, styles["label"]), Paragraph(safe(val), styles["priority_body"])]
                for lbl, val in action_fields
            ]
            at = Table(action_rows, colWidths=[0.22 * COL_W, 0.78 * COL_W])
            at.setStyle(TableStyle([
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#FEF9E7")]),
                ("BOX", (0, 0), (-1, -1), 0.5, BRAND_ORANGE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#F0D9B5")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))

            story.append(KeepTogether([ph, at, Spacer(1, 0.4 * cm)]))

    # ============================================================
    # 6. ADDITIONAL NOTES
    # ============================================================
    story.append(section_header_table("6.  Additional Notes", styles))
    story.append(Spacer(1, 0.3 * cm))

    notes = report_data.get("Additional_Notes", [])
    if isinstance(notes, str):
        story.append(Paragraph(safe(notes), styles["body"]))
    else:
        for note in ensure_list(notes):
            story.append(Paragraph(f"• {safe(note)}", styles["bullet"]))
    story.append(Spacer(1, 0.4 * cm))

    # ============================================================
    # 7. MISSING / UNCLEAR INFORMATION
    # ============================================================
    story.append(section_header_table("7.  Missing or Unclear Information", styles))
    story.append(Spacer(1, 0.3 * cm))

    missing = report_data.get("Missing_Info_Table", [])
    if isinstance(missing, str):
        story.append(Paragraph(safe(missing), styles["body"]))
    elif missing:
        m_header = [
            Paragraph("Missing Item", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Status", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
            Paragraph("Impact on Diagnosis", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)),
        ]
        m_rows = [m_header]
        for m in missing:
            m_rows.append([
                Paragraph(safe(m.get("Missing_Item", "—")), styles["body"]),
                Paragraph(safe(m.get("Status", "Not Available")), ParagraphStyle(
                    "status", fontName="Helvetica-Bold", fontSize=9,
                    textColor=BRAND_ORANGE, alignment=TA_CENTER
                )),
                Paragraph(safe(m.get("Impact", "—")), styles["body"]),
            ])
        m_tbl = Table(m_rows, colWidths=[0.32 * COL_W, 0.18 * COL_W, 0.5 * COL_W])
        m_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
            ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4DE")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(m_tbl)
    else:
        story.append(Paragraph("No missing information reported.", styles["body"]))

    story.append(Spacer(1, 0.4 * cm))
    story.append(ColoredLine(BRAND_BLUE))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        f"Generated by UrbanRoof DDR AI System  |  {datetime.now().strftime('%d %B %Y, %H:%M')}  "
        f"|  UrbanRoof Private Limited  |  info@urbanroof.in  |  +91-8925-805-805",
        ParagraphStyle("footer_text", fontName="Helvetica", fontSize=7.5,
                       textColor=colors.grey, alignment=TA_CENTER)
    ))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


# ==========================================
# STREAMLIT UI
# ==========================================
with st.sidebar:
    st.title("🏗️ UrbanRoof AI Builder")
    st.markdown("### Configuration")
    api_key = st.text_input("Gemini API Key", type="password")

    st.markdown("### Upload Documents")
    uploaded_files = st.file_uploader(
        "Upload Inspection & Thermal Reports (PDF)",
        type="pdf",
        accept_multiple_files=True
    )
    st.markdown("---")
    st.caption("Model: auto-selected from your API key")

st.title("Main DDR (Detailed Diagnostic Report)")

if not api_key:
    st.warning("⚠️ Please enter your Gemini API Key in the sidebar to proceed.")
    st.stop()

if not uploaded_files:
    st.info("📄 Please upload the property inspection PDF files in the sidebar to generate the DDR.")
    st.stop()

if st.button("🚀 Analyze & Generate DDR", type="primary"):

    with st.spinner("Step 1/2: Extracting text and images from PDFs..."):
        raw_text, extracted_images = extract_pdf_data(uploaded_files)

    with st.spinner("Step 2/2: AI is analysing and structuring the DDR..."):
        report_data = generate_ddr_report(raw_text, api_key)

    if report_data:
        st.success("✅ Analysis Complete!")

        # PDF download
        with st.spinner("Generating professional PDF report..."):
            pdf_bytes = build_pdf(report_data, extracted_images)

        st.download_button(
            label="📥 Download Professional PDF Report",
            data=pdf_bytes,
            file_name="UrbanRoof_DDR_Report.pdf",
            mime="application/pdf",
            type="primary"
        )
        st.markdown("---")

        # ---- DASHBOARD PREVIEW ----
        pd_raw = report_data.get("Property_Details", {})
        stats  = report_data.get("Stats", {})

        col1, col2, col3 = st.columns(3)
        col1.metric("Affected Areas",   stats.get("Affected_Areas", "—"))
        col2.metric("Overall Severity", stats.get("Overall_Severity", "—"))
        col3.metric("Inspection Score", stats.get("Inspection_Score", "—"))

        st.header("1. Property Issue Summary")
        st.info(report_data.get("Property_Issue_Summary", "Not Available"))

        primary_issues = ensure_list(report_data.get("Primary_Issues"))
        if primary_issues:
            st.markdown("**Primary Issues:**")
            for iss in primary_issues:
                st.markdown(f"- {iss}")

        st.header("2. Area-wise Observations")
        areas = report_data.get("Area_wise_Observations", [])
        if not areas:
            st.write("Not Available")
        else:
            tabs = st.tabs([a.get("Area_Name", "Unknown") for a in areas])
            for idx, tab in enumerate(tabs):
                with tab:
                    area = areas[idx]
                    fields = {
                        "Observation":         area.get("Observation"),
                        "Source / Exposed":    area.get("Source_Exposed_Side"),
                        "Thermal Reading":     area.get("Thermal_Reading"),
                        "Thermal Interpretation": area.get("Thermal_Interpretation"),
                    }
                    for k, v in fields.items():
                        if v and str(v).lower() != "not available":
                            st.markdown(f"**{k}:** {v}")

                    st.subheader("Visual Evidence:")
                    refs = ensure_list(area.get("Relevant_Image_Captions"))
                    has_img = False
                    if refs:
                        cols = st.columns(3)
                        ci = 0
                        for ref in refs:
                            if ref in extracted_images:
                                has_img = True
                                try:
                                    img = Image.open(io.BytesIO(extracted_images[ref]))
                                    cols[ci % 3].image(img, use_column_width=True)
                                    ci += 1
                                except Exception:
                                    pass
                    if not has_img:
                        st.warning("Image Not Available")

        st.header("3. Probable Root Cause")
        rcs = report_data.get("Probable_Root_Causes", [])
        if isinstance(rcs, str):
            st.write(rcs)
        else:
            for rc in rcs:
                st.markdown(f"**■ {rc.get('Area_Group', '')}**")
                st.write(rc.get("Root_Cause", "Not Available"))
                steps = ensure_list(rc.get("Mechanism"))
                for i, s in enumerate(steps, 1):
                    st.markdown(f"&nbsp;&nbsp;{i}. {s}")

        st.header("4. Severity Assessment")
        sev_rows = report_data.get("Severity_Table", [])
        if sev_rows:
            st.dataframe(
                {
                    "Area":     [r.get("Area", "—") for r in sev_rows],
                    "Issue":    [r.get("Issue", "—") for r in sev_rows],
                    "Severity": [r.get("Severity", "—") for r in sev_rows],
                    "Score":    [r.get("Score", "—") for r in sev_rows],
                    "Action":   [r.get("Action_Timeframe", "—") for r in sev_rows],
                },
                use_container_width=True
            )
        overall = report_data.get("Overall_Severity_Assessment", {})
        if isinstance(overall, dict):
            st.markdown(f"**Level:** {overall.get('Level', '—')}")
            st.markdown(f"**Reasoning:** {overall.get('Reasoning', '—')}")

        st.header("5. Recommended Actions")
        actions = report_data.get("Recommended_Actions", [])
        if not actions:
            st.warning("No recommended actions were generated.")
        else:
            for action in actions:
                if isinstance(action, str):
                    st.markdown(f"- {action}")
                else:
                    with st.expander(f"🔧 {action.get('Priority_Label', 'Action Item')}"):
                        st.markdown(f"**What to Do:** {action.get('What_to_Do', '—')}")
                        st.markdown(f"**How to Do It:** {action.get('How_to_Do_It', '—')}")
                        st.markdown(f"**Materials:** {action.get('Materials', '—')}")
                        st.markdown(f"**Expected Outcome:** {action.get('Expected_Outcome', '—')}")

        st.header("6. Additional Notes")
        notes = report_data.get("Additional_Notes", [])
        if isinstance(notes, str):
            st.write(notes)
        else:
            for n in ensure_list(notes):
                st.markdown(f"- {n}")

        st.header("7. Missing or Unclear Information")
        missing = report_data.get("Missing_Info_Table", [])
        if isinstance(missing, str):
            st.write(missing)
        elif missing:
            st.dataframe(
                {
                    "Missing Item": [m.get("Missing_Item", "—") for m in missing],
                    "Status":       [m.get("Status", "—") for m in missing],
                    "Impact":       [m.get("Impact", "—") for m in missing],
                },
                use_container_width=True
            )
        else:
            st.write("No missing information reported.")
