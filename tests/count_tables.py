import docx
from xml.etree import ElementTree as ET

doc_o = docx.Document("backend/app/templates/Property Acknowledgement Document.docx")
doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

def count_all_tables(doc, name):
    xml_str = doc._part._element.xml
    root = ET.fromstring(xml_str)
    all_tbls = root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')
    print(f"{name}: Total <w:tbl> elements in entire document: {len(all_tbls)}")

count_all_tables(doc_o, "Old Template")
count_all_tables(doc_c, "Correct Format")
