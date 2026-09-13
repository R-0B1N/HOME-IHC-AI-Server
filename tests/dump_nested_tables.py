import docx
from xml.etree import ElementTree as ET

doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

def dump_element(elem, prefix=""):
    tag = elem.tag.split('}')[-1]
    text = elem.text.strip() if elem.text and elem.text.strip() else ""
    # Check if there are runs/text inside
    if tag == 'tbl':
        print(f"{prefix}[TABLE]")
        for row_i, tr in enumerate(elem.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr')):
            cells = tr.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')
            cell_texts = []
            for tc in cells:
                # get all w:t
                texts = [t.text for t in tc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
                cell_texts.append(" ".join(texts))
            print(f"{prefix}  Row {row_i}: {cell_texts}")
    elif tag == 'p':
        texts = [t.text for t in elem.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
        p_text = "".join(texts)
        if p_text.strip():
            print(f"{prefix}[P]: {p_text}")
    else:
        for child in elem:
            dump_element(child, prefix + "  ")

t0_c = doc_c.tables[0]
print("=== CELL 0 OF CORRECT DOC ===")
for child in t0_c.rows[0].cells[0]._tc:
    dump_element(child, "  ")

print("\n=== CELL 1 OF CORRECT DOC ===")
for child in t0_c.rows[0].cells[1]._tc:
    dump_element(child, "  ")
