import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    for name in z.namelist():
        if "numbering" in name:
            print("Found:", name)
            xml_content = z.read(name).decode('utf-8')
            root = ET.fromstring(xml_content)
            # print all abstractNum and num
            for num in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num'):
                numId = num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
                absId = num.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId').get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                print(f"numId {numId} -> abstractNumId {absId}")
            for absNum in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
                absId = absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId')
                # find lvl
                for lvl in absNum.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl'):
                    ilvl = lvl.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl')
                    lvlText = lvl.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText')
                    rFonts = lvl.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
                    font_name = rFonts.attrib if rFonts is not None else None
                    text_val = lvlText.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if lvlText is not None else None
                    print(f"abstractNum {absId} lvl {ilvl}: text={repr(text_val)}, fonts={font_name}")
