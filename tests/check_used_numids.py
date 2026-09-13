import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    doc_xml = z.read("word/document.xml").decode('utf-8')
    num_xml = z.read("word/numbering.xml").decode('utf-8')

root_doc = ET.fromstring(doc_xml)
root_num = ET.fromstring(num_xml)

# Find all numIds used in document
used_num_ids = set()
for numPr in root_doc.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr'):
    numId_elem = numPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
    if numId_elem is not None:
        used_num_ids.add(numId_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val'))

print("All numIds used in doc:", sorted(list(used_num_ids)))

# Map numId to abstractNumId
num_to_abs = {}
for num in root_num.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num'):
    nid = num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
    aid = num.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
    num_to_abs[nid] = aid

for nid in sorted(list(used_num_ids)):
    aid = num_to_abs.get(nid)
    print(f"\n--- numId {nid} (abstractNumId {aid}) ---")
    for absNum in root_num.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
        if absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId') == aid:
            for lvl in absNum.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl'):
                ilvl = lvl.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl')
                lvlText = lvl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                rFonts = lvl.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
                font_dict = rFonts.attrib if rFonts is not None else {}
                char_hex = [hex(ord(c)) for c in lvlText]
                print(f"  lvl {ilvl}: lvlText={repr(lvlText)} ({char_hex}) font={font_dict.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii')}")
