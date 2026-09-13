import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    doc_xml = z.read("word/document.xml").decode('utf-8')
    num_xml = z.read("word/numbering.xml").decode('utf-8')

root_doc = ET.fromstring(doc_xml)
root_num = ET.fromstring(num_xml)

# Look for all numPr in document.xml and print their preceding/following text
for p in root_doc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
    numPr = p.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
    if numPr is not None:
        nid = numPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
        # get text of p
        texts = [t.text for t in p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
        # also check parent tag or cell or previous/next p
        print(f"p with numId={nid}: text={repr(''.join(texts))}")
