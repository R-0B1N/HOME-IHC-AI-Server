import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    styles_xml = z.read("word/styles.xml").decode('utf-8')

root = ET.fromstring(styles_xml)
for style in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}style'):
    style_id = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId')
    if style_id == 'TableGrid':
        print(ET.tostring(style, encoding='unicode'))
