import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    xml_content = z.read("word/numbering.xml").decode('utf-8')
    root = ET.fromstring(xml_content)
    num_map = {}
    for num in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num'):
        numId = num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
        absId = num.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
        num_map[numId] = absId

    for absNum in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
        absId = absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId')
        # check which numIds use this absId
        using_nums = [k for k, v in num_map.items() if v == absId]
        for lvl in absNum.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl'):
            ilvl = lvl.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl')
            lvlText = lvl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText')
            rFonts = lvl.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
            font_info = rFonts.attrib if rFonts is not None else {}
            text_val = lvlText.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if lvlText is not None else ""
            char_hex = [hex(ord(c)) for c in text_val]
            if using_nums:
                print(f"numIds {using_nums} (absId {absId}) lvl {ilvl}: text={repr(text_val)} ({char_hex}) fonts={font_info}")
