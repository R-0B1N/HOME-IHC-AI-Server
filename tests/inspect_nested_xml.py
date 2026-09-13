import docx
from xml.etree import ElementTree as ET

doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

t0_c = doc_c.tables[0]

def inspect_nested_tables(cell, cell_name):
    root = ET.fromstring(cell._tc.xml)
    tbls = root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')
    print(f"\n================== {cell_name} NESTED TABLES ({len(tbls)}) ==================")
    for t_i, tbl in enumerate(tbls):
        print(f"\n--- Nested Table {t_i} ---")
        # print tblPr
        tblPr = tbl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblPr')
        if tblPr is not None:
            print("  tblPr:", ET.tostring(tblPr, encoding='unicode'))
        for r_i, tr in enumerate(tbl.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr')):
            for c_i, tc in enumerate(tr.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')):
                xml_str = ET.tostring(tc, encoding='unicode')
                print(f"  Row {r_i}, Col {c_i}: {xml_str}\n")

inspect_nested_tables(t0_c.rows[0].cells[0], "CELL 0")
inspect_nested_tables(t0_c.rows[0].cells[1], "CELL 1")
