import docx
from xml.etree import ElementTree as ET

doc = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

for t_i, tbl in enumerate(doc.tables):
    print(f"\n================ TABLE {t_i} ================")
    tblStyle = tbl._tbl.tblPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblStyle')
    print("tblStyle:", tblStyle.attrib if tblStyle is not None else None)
    tblBorders = tbl._tbl.tblPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblBorders')
    print("tblBorders:", ET.tostring(tblBorders, encoding='unicode') if tblBorders is not None else None)
    for r_i, row in enumerate(tbl.rows):
        for c_i, cell in enumerate(row.cells):
            tcBorders = cell._tc.tcPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcBorders')
            if tcBorders is not None:
                print(f"  Row {r_i}, Col {c_i} tcBorders: {ET.tostring(tcBorders, encoding='unicode')}")
            else:
                pass
