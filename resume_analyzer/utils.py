import fitz
import hashlib


CACHE_VERSION = "v1"


def normalize_text_for_hash(text):
    return " ".join(text.split())


def compute_content_hash(text):
    normalized_text = normalize_text_for_hash(text)
    content = f"{CACHE_VERSION}{normalized_text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
    
        full_text = []

        for page in doc:
            blocks = page.get_text("blocks")
            blocks = sorted(blocks, key=lambda b: (b[1], b[0]))

            for block in blocks:
                full_text.append(block[4])

        doc.close()
        return "\n".join(full_text)
    
    except Exception as e:

        print("PDF PARSING ERROR:", e)

        return None