import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    num_xml = z.read("word/numbering.xml").decode('utf-8')

root_num = ET.fromstring(num_xml)

num_to_abs = {}
for num in root_num.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num'):
    nid = num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
    aid = num.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
    num_to_abs[nid] = aid

for nid in ['51', '48', '49', '36', '37', '38', '39', '40', '41', '43', '52', '53', '1', '2', '3']:
    aid = num_to_abs.get(nid)
    for absNum in root_num.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
        if absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId') == aid:
            lvl = absNum.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl')
            lvlText = lvl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
            rFonts = lvl.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
            font_ascii = rFonts.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii') if rFonts is not None else None
            # Also check if there is an rPr color, bold, etc.
            rPr = lvl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr')
            rpr_str = ET.tostring(rPr, encoding='unicode') if rPr is not None else ""
            char_hex = hex(ord(lvlText[0])) if lvlText else ""
            print(f"numId {nid:2s} -> absId {aid:2s} | char={char_hex} {repr(lvlText)} | font={font_ascii} | rPr={rpr_str}")
