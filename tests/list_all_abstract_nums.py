import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    num_xml = z.read("word/numbering.xml").decode('utf-8')

root = ET.fromstring(num_xml)

print("=== ALL ABSTRACTNUM DEFINITIONS IN CORRECT FORMAT ===")
for absNum in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
    aid = absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId')
    lvl0 = absNum.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl[@{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl="0"]')
    if lvl0 is not None:
        lt = lvl0.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
        rf = lvl0.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
        rf_dict = rf.attrib if rf is not None else {}
        print(f"absId {aid:2s}: lvlText={repr(lt)} (hex {[hex(ord(c)) for c in lt]}) font={rf_dict.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii')}")
