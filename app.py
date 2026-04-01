import streamlit as st
import fitz  # PyMuPDF
import json
import os
import google.generativeai as genai
import io
from PIL import Image
from fpdf import FPDF
import tempfile
from datetime import datetime # Added for the report date

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="UrbanRoof AI Builder | DDR Generator", layout="wide", page_icon="🏢")

# ==========================================
# CONSTANTS & SETUP
# ==========================================
GEMINI_MODEL = "gemini-2.5-flash"

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def extract_pdf_data(uploaded_files):
    """
    Extracts text and images from uploaded PDF files using PyMuPDF.
    Filters out small logos/icons.
    """
    combined_text = ""
    extracted_images = {}
    
    for file in uploaded_files:
        try:
            pdf_bytes = file.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            combined_text += f"\n--- Start of Document: {file.name} ---\n"
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text("text")
                combined_text += f"\n[Page {page_num + 1}]\n{page_text}"
                
                image_list = page.get_images(full=True)
                for img_idx, img in enumerate(image_list):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    
                    # FIX: Filter out small header/footer logos (e.g., < 100x100 px)
                    if base_image["width"] < 100 or base_image["height"] < 100:
                        continue
                        
                    image_bytes = base_image["image"]
                    image_key = f"{file.name}_Page{page_num+1}_Img{img_idx+1}"
                    extracted_images[image_key] = image_bytes
                    
                    # Insert a marker in the text so the LLM knows an image was here
                    combined_text += f"\n[IMAGE EXTRACTED HERE: Reference ID -> {image_key}]\n"
                    
            combined_text += f"\n--- End of Document: {file.name} ---\n"
        except Exception as e:
            st.error(f"Error reading {file.name}: {e}")
            
    return combined_text, extracted_images

def generate_ddr_report(text_context, api_key):
    """
    Calls Google Gemini API to reason over the text and output the Enforced JSON Schema.
    """
    genai.configure(api_key=api_key)
    
    # ADDED: Improved prompt to find "Suggested Therapies" and ignore blank tables
    system_prompt = """
    You are an expert Property Diagnostic AI. Your job is to read building inspection and thermal reports and generate a Detailed Diagnostic Report (DDR).
    
    CRITICAL RULES:
    1. Do NOT invent facts not present in the documents.
    2. If information conflicts, mention the conflict explicitly.
    3. If information is missing for a required field, write exactly "Not Available".
    4. Use simple, client-friendly language. Avoid unnecessary technical jargon.
    5. For 'Recommended_Actions', IGNORE the empty summary table at the start. You MUST search for detailed repair steps in sections like "ANALYSIS & SUGGESTIONS" or "SUGGESTED THERAPIES" (e.g., Grouting, Plastering, RCC treatment).
    6. For 'Relevant_Image_Captions', you MUST USE THE EXACT 'Reference ID' provided in the text markers.
    
    OUTPUT FORMAT:
    You must return a strictly valid JSON object adhering to this exact schema:
    {
        "Property_Issue_Summary": "A brief summary.",
        "Area_wise_Observations": [
            {
                "Area_Name": "Name of the area",
                "Observations": ["Observation 1"],
                "Relevant_Image_Captions": ["Exact Reference ID"]
            }
        ],
        "Probable_Root_Cause": "Analysis of root causes.",
        "Severity_Assessment": {
            "Level": "Low / Medium / High / Critical",
            "Reasoning": "Why this level."
        },
        "Recommended_Actions": ["Action 1", "Action 2"],
        "Additional_Notes": "Any other context.",
        "Missing_or_Unclear_Information": "Details missing or 'Not Available'."
    }
    """
    
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2,
            )
        )
        
        prompt = f"Here is the extracted document text. Generate the JSON report:\n\n{text_context}"
        response = model.generate_content(prompt)
        
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Failed to generate report with Gemini: {str(e)}")
        return None

# ADDED: Helper to prevent vertical "N-o-t A-v-a-i-l-a-b-l-e" printing
def ensure_list(item):
    if isinstance(item, str):
        if item.strip().lower() == "not available": return []
        return [item]
    return item if isinstance(item, list) else []

# ADDED: Professional PDF Formatting Class
class StyledPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('Arial', 'B', 12)
            self.set_text_color(41, 128, 185) # Blue
            self.cell(0, 10, 'UrbanRoof Detailed Diagnostic Report', 0, 1, 'R')
            self.line(10, 20, 200, 20)
            self.ln(5)

    def footer(self):
        if self.page_no() > 1:
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()} | Generated by UrbanRoof AI', 0, 0, 'C')

def create_pdf_report(report_data, extracted_images):
    """
    Generates a professional downloadable PDF document using FPDF.
    """
    pdf = StyledPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Helper to handle special characters
    def safe_text(text):
        return str(text).encode('latin-1', 'replace').decode('latin-1')

    # --- COVER PAGE ---
    pdf.add_page()
    pdf.set_y(100)
    pdf.set_font("Arial", "B", 26)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(0, 20, "DETAILED DIAGNOSTIC REPORT", 0, 1, 'C')
    pdf.set_font("Arial", "", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%B %d, %Y')}", 0, 1, 'C')
    pdf.cell(0, 10, "Prepared by: UrbanRoof AI Builder", 0, 1, 'C')
    
    # Helper for styled headers
    def add_section_header(title):
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.set_fill_color(41, 128, 185)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, safe_text(f"  {title}"), 0, 1, 'L', fill=True)
        pdf.ln(5)
        pdf.set_font("Arial", "", 11)
        pdf.set_text_color(0, 0, 0)

    # 1. Summary
    add_section_header("1. Property Issue Summary")
    pdf.multi_cell(0, 7, safe_text(report_data.get("Property_Issue_Summary", "Not Available")))
    
    # 2. Area-wise
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(41, 128, 185)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, "  2. Area-wise Observations", 0, 1, 'L', fill=True)
    pdf.set_text_color(0, 0, 0)
    
    areas = report_data.get("Area_wise_Observations", [])
    for area in areas:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, safe_text(f"Area: {area.get('Area_Name', 'Unknown')}"), ln=True)
        pdf.set_font("Arial", "", 11)
        for obs in ensure_list(area.get("Observations")):
            pdf.multi_cell(0, 7, safe_text(f" - {obs}"))
        
        # Image placement in PDF
        for ref in ensure_list(area.get("Relevant_Image_Captions")):
            if ref in extracted_images:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img = Image.open(io.BytesIO(extracted_images[ref])).convert('RGB')
                    img.save(tmp, format="JPEG")
                    tmp_path = tmp.name
                try:
                    pdf.ln(3)
                    pdf.image(tmp_path, x=55, w=100) # Centered image
                    pdf.ln(5)
                except: pass
                finally: os.unlink(tmp_path)

    # 3. Root Cause
    add_section_header("3. Probable Root Cause")
    pdf.multi_cell(0, 7, safe_text(report_data.get("Probable_Root_Cause", "Not Available")))
    
    # 5. Actions (The "Recommended" Part)
    add_section_header("5. Recommended Actions")
    actions = ensure_list(report_data.get("Recommended_Actions"))
    if not actions:
        pdf.cell(0, 10, safe_text("Not Available"), ln=True)
    else:
        for action in actions:
            pdf.multi_cell(0, 7, safe_text(f" - {action}"))

    # 6. Additional Notes
    add_section_header("6. Additional Notes")
    pdf.multi_cell(0, 7, safe_text(report_data.get("Additional_Notes", "Not Available")))

    return bytes(pdf.output(dest="S"), encoding="latin-1")


# ==========================================
# STREAMLIT UI LAYOUT
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

st.title("Main DDR (Detailed Diagnostic Report)")

if not api_key:
    st.warning("⚠️ Please enter your Gemini API Key in the sidebar to proceed.")
    st.stop()

if not uploaded_files:
    st.info("📄 Please upload the property inspection PDF files in the sidebar to generate the DDR.")
    st.stop()

if st.button("🚀 Analyze & Generate DDR", type="primary"):
    with st.spinner("Step 1/2: Extracting text and filtering images..."):
        raw_text, extracted_images = extract_pdf_data(uploaded_files)
        
    with st.spinner(f"Step 2/2: AI is structuring the DDR using {GEMINI_MODEL}..."):
        report_data = generate_ddr_report(raw_text, api_key)
        
    if report_data:
        st.success("Analysis Complete!")
        
        # --- PDF GENERATION BUTTON ---
        pdf_bytes = create_pdf_report(report_data, extracted_images)
        st.download_button(
            label="📥 Download Professional PDF Report",
            data=pdf_bytes,
            file_name="UrbanRoof_Diagnostic_Report.pdf",
            mime="application/pdf",
            type="primary"
        )
        st.markdown("---")
        
        # --- DASHBOARD PREVIEW ---
        st.header("1. Property Issue Summary")
        st.info(report_data.get("Property_Issue_Summary", "Not Available"))
        
        st.header("2. Area-wise Observations")
        areas = report_data.get("Area_wise_Observations", [])
        
        if not areas:
            st.write("Not Available")
        else:
            tabs = st.tabs([area.get("Area_Name", "Unknown Area") for area in areas])
            for index, tab in enumerate(tabs):
                with tab:
                    area = areas[index]
                    st.subheader("Observations:")
                    for obs in ensure_list(area.get("Observations")):
                        st.markdown(f"- {obs}")
                    
                    st.subheader("Visual Evidence:")
                    image_refs = ensure_list(area.get("Relevant_Image_Captions"))
                    has_image = False
                    
                    if image_refs:
                        cols = st.columns(3)
                        col_idx = 0
                        for ref in image_refs:
                            if ref in extracted_images:
                                has_image = True
                                try:
                                    img = Image.open(io.BytesIO(extracted_images[ref]))
                                    cols[col_idx % 3].image(img, use_column_width=True) 
                                    col_idx += 1
                                except: pass
                    
                    if not has_image:
                        st.warning("Image Not Available")

        st.header("3. Probable Root Cause")
        st.write(report_data.get("Probable_Root_Cause", "Not Available"))
        
        st.header("4. Severity Assessment")
        severity = report_data.get("Severity_Assessment", {})
        st.markdown(f"**Level:** {severity.get('Level', 'Not Available')}")
        st.markdown(f"**Reasoning:** {severity.get('Reasoning', 'Not Available')}")
        
        # FIXED: Recommended Actions now uses the ensure_list logic
        st.header("5. Recommended Actions")
        actions = ensure_list(report_data.get("Recommended_Actions"))
        if not actions:
            st.write("Not Available")
        else:
            for action in actions:
                st.markdown(f"- {action}")
                
        st.header("6. Additional Notes")
        st.write(report_data.get("Additional_Notes", "Not Available"))
        
        st.header("7. Missing or Unclear Information")
        st.write(report_data.get("Missing_or_Unclear_Information", "Not Available"))