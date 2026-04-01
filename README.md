# 🏢 UrbanRoof AI Builder: Automated DDR Generator

An AI-powered diagnostic system designed to transform raw property inspection reports and thermal imaging data into professional, client-ready **Detailed Diagnostic Reports (DDR)**.

## 🌟 Overview
UrbanRoof AI Builder automates the tedious process of manual data entry for property inspectors. By leveraging Large Language Models (LLMs) and advanced PDF processing, the system extracts critical observations, identifies root causes, and generates a structured, branded PDF report in seconds.

## 🚀 Key Features
* **Intelligent Extraction:** Uses `PyMuPDF` to extract text and high-resolution site/thermal photos while filtering out irrelevant document icons.
* **AI-Powered Reasoning:** Powered by **Google Gemini 2.5 Flash** to synthesize data from multiple documents, handling conflicting details and missing information as per strict business rules.
* **Deep-Search Recommendations:** Specifically engineered to locate and extract detailed "Suggested Therapies" (Grouting, RCC treatment, etc.) often buried deep in technical appendices.
* **Professional PDF Engine:** A custom-built generation layer using `FPDF` that produces a branded corporate report with cover pages and styled section banners.
* **Interactive Dashboard:** A clean `Streamlit` interface for real-time analysis and previewing observations area-by-area.

## 🛠️ Tech Stack
* **Frontend:** [Streamlit](https://streamlit.io/)
* **AI Model:** [Google Gemini 2.5 Flash](https://aistudio.google.com/)
* **PDF Processing:** [PyMuPDF (Fitz)](https://pymupdf.readthedocs.io/)
* **Image Handling:** [Pillow (PIL)](https://python-pillow.org/)
* **Report Generation:** [FPDF2](https://pyfpdf.github.io/fpdf2/)

## 📦 Installation & Setup

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/your-username/urbanroof-ai-builder.git](https://github.com/your-username/urbanroof-ai-builder.git)
    cd urbanroof-ai-builder
    ```

2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Up API Key:**
    * Obtain a Gemini API Key from [Google AI Studio](https://aistudio.google.com/).
    * Input the key directly into the sidebar of the running application.

4.  **Run the App:**
    ```bash
    streamlit run app.py
    ```

## 📋 Submission Requirements (Checklist)
- [x] **Working Code:** `app.py` handles extraction, AI analysis, and PDF generation.
- [x] **Structured Data:** AI output follows a strict JSON schema.
- [x] **Images:** Relevant thermal and site images are embedded in the final PDF.
- [x] **Requirements:** `requirements.txt` file included.

## 🛡️ Limitations & Future Scope
* **Scan-to-Text:** Current version reads text layers. Future updates will include OCR (Tesseract) for scanned/handwritten documents.
* **Vision Integration:** Moving toward native Multimodal Vision analysis for direct thermal image interpretation.
* **Batch Processing:** Plans to implement multi-property analysis for enterprise-scale auditing.

---
