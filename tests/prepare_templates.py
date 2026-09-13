import zipfile
import os
import shutil
from xml.etree import ElementTree as ET

src_docx = "docs/Property Acknowledgement Document Correct Format.docx"
target_pkg = "backend/app/templates/Property Acknowledgement Document.docx"
target_docs = "docs/Property Acknowledgement Document.docx"

with zipfile.ZipFile(src_docx, 'r') as zin:
    num_xml = zin.read("word/numbering.xml").decode('utf-8')

root_num = ET.fromstring(num_xml)
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

# Find an existing abstractNum with Wingdings, e.g. abs50
abs50 = root_num.find('.//w:abstractNum[@w:abstractNumId="50"]', ns)

# Create abstractNum 998 (unchecked box: \uf0a8)
abs998 = ET.fromstring(ET.tostring(abs50))
abs998.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId', '998')
lvl0_998 = abs998.find('.//w:lvl[@w:ilvl="0"]', ns)
lvl0_998.find('w:lvlText', ns).set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '\uf0a8')

# Create abstractNum 999 (checked box: \uf0fe)
abs999 = ET.fromstring(ET.tostring(abs50))
abs999.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId', '999')
lvl0_999 = abs999.find('.//w:lvl[@w:ilvl="0"]', ns)
lvl0_999.find('w:lvlText', ns).set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '\uf0fe')

# Insert abstractNum 998 and 999 before first <w:num>
first_num = root_num.find('w:num', ns)
idx = list(root_num).index(first_num)
root_num.insert(idx, abs998)
root_num.insert(idx + 1, abs999)

# Create <w:num w:numId="998"> and <w:num w:numId="999">
num998 = ET.fromstring("""
<w:num xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:numId="998">
    <w:abstractNumId w:val="998"/>
</w:num>
""")
num999 = ET.fromstring("""
<w:num xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:numId="999">
    <w:abstractNumId w:val="999"/>
</w:num>
""")
root_num.append(num998)
root_num.append(num999)

new_num_xml = ET.tostring(root_num, encoding='utf-8', xml_declaration=True)

for target_path in [target_pkg, target_docs]:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    temp_target = target_path + ".tmp"
    with zipfile.ZipFile(src_docx, 'r') as zin:
        with zipfile.ZipFile(temp_target, 'w') as zout:
            for item in zin.infolist():
                if item.filename == "word/numbering.xml":
                    zout.writestr(item, new_num_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))
    shutil.move(temp_target, target_path)
    print(f"Updated {target_path} ({os.path.getsize(target_path)} bytes)")
