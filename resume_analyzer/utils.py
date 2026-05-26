import fitz


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