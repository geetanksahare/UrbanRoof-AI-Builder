# UrbanRoof AI Builder | DDR Generator

A Streamlit-based AI application that reads property inspection and thermal PDF reports, extracts text and images, sends the content to Gemini AI, and generates a structured **Detailed Diagnostic Report (DDR)** in both on-screen and downloadable PDF formats.

---

## 🚀 Features

* Upload one or more PDF inspection/thermal reports
* Extract text from every page using **PyMuPDF**
* Extract embedded images from reports
* Automatically select the best Gemini model
* Generate structured JSON-based DDR
* Interactive Streamlit dashboard preview
* Download a professional PDF report
* Includes:

  * Property details
  * Issue summary
  * Area-wise observations
  * Probable root causes
  * Severity assessment
  * Recommended actions
  * Additional notes
  * Missing information table

---

## 🛠️ Tech Stack

* Python
* Streamlit
* PyMuPDF (fitz)
* Google Generative AI
* Pillow
* ReportLab

---

## ⚙️ Project Workflow

1. Enter Gemini API key
2. Upload PDF inspection reports
3. Extract text + images from PDFs
4. Send data to Gemini AI
5. Generate structured DDR (JSON)
6. Display results in dashboard
7. Generate downloadable PDF report

---

## 📦 Installation

Clone the repository:

```bash
git clone https://github.com/your-username/urbanroof-ai-builder.git
cd urbanroof-ai-builder
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate the environment:

**Windows**

```bash
venv\Scripts\activate
```

**macOS / Linux**

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 📄 Requirements

```
streamlit
pymupdf
google-generativeai
fpdf
pillow
reportlab
```

---

## ▶️ Running the App

```bash
streamlit run app.py
```

---

## 🧑‍💻 How to Use

1. Open the app in your browser
2. Enter your **Gemini API Key**
3. Upload PDF inspection reports
4. Click **Analyze & Generate DDR**
5. View results in dashboard
6. Download the generated PDF

---

## 📊 Output Includes

* Property details
* Overall severity score
* Area-wise observations
* Thermal analysis
* Root cause analysis
* Severity table
* Recommended repair actions
* Missing information report

---

## 📁 Folder Structure

```
project-folder/
│── app.py
│── requirements.txt
│── README.md
```

---

## ⚠️ Important Notes

* Requires a valid Gemini API key
* Only PDF files are supported
* Multiple PDFs can be uploaded
* AI generates structured JSON before PDF creation
* Recommended actions are always generated

---

## 📜 License

This project is created for academic / assignment purposes.

---

## 👨‍💻 Author

Built using Streamlit and Gemini AI for automated property diagnostic reporting.
