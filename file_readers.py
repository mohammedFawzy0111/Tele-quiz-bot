import pdfplumber
from docx import Document
from config import NON_ASCII_RE


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_pdf_file(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                t = NON_ASCII_RE.sub(" ", t)
                text += t + "\n"
    return text


def read_word_file(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)
