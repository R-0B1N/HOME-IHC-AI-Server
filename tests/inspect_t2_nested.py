import docx
from xml.etree import ElementTree as ET

doc = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

t2 = doc.tables[2]
def dump_nested_in_cell(cell, label):
    root = ET.fromstring(cell._tc.xml)
    tbls = root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')
    print(f"\n--- {label}: {len(tbls)} nested tables ---")
    for t_i, tbl in enumerate(tbls):
        print(f"Nested Table {t_i}:")
        for r_i, tr in enumerate(tbl.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr')):
            cells_info = []
            for c_i, tc in enumerate(tr.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')):
                numPr = tc.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
                nid = numPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if numPr is not None else ""
                texts = [t.text for t in tc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
                cells_info.append(f"({'numId=' + nid if nid else ''} {' '.join(texts)})")
            print(f"  Row {r_i}: {', '.join(cells_info)}")

dump_nested_in_cell(t2.rows[1].cells[1], "Table 2 Row 1 Col 1 (Documents)")
dump_nested_in_cell(t2.rows[1].cells[4], "Table 2 Row 1 Col 4 (Remarks)")
