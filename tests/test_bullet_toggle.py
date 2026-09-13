import zipfile
import shutil
import os
from xml.etree import ElementTree as ET

src_docx = "docs/Property Acknowledgement Document Correct Format.docx"
test_docx = "artifacts/test_bullet_toggle.docx"
os.makedirs("artifacts", exist_ok=True)

# Let's inspect what happens if we change lvlText in numbering.xml
with zipfile.ZipFile(src_docx, 'r') as zin:
    with zipfile.ZipFile(test_docx, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/numbering.xml":
                root = ET.fromstring(data.decode('utf-8'))
                # Find abstractNum 50 (numId 51, which is MR)
                for absNum in root.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNum'):
                    aid = absNum.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId')
                    if aid == '50': # MR
                        lvl0 = absNum.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvl[@{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl="0"]')
                        lvlText = lvl0.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lvlText')
                        print("Old MR lvlText:", hex(ord(lvlText.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val'))))
                        lvlText.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '\uf0fe') # checked box
                data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            zout.writestr(item, data)

print("Saved test_docx, verifying size:", os.path.getsize(test_docx))
