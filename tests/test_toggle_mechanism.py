import zipfile
import os
from xml.etree import ElementTree as ET
import docx

doc_path = "docs/Property Acknowledgement Document Correct Format.docx"
test_out = "artifacts/test_checked_numbering.docx"
os.makedirs("artifacts", exist_ok=True)

# 1. Read numbering.xml
with zipfile.ZipFile(doc_path, 'r') as zin:
    num_xml = zin.read("word/numbering.xml").decode('utf-8')

root = ET.fromstring(num_xml)
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

# Let's inspect an existing abstractNum, e.g. absId 50
abs50 = root.find('.//w:abstractNum[@w:abstractNumId="50"]', ns)
print("abs50 found?", abs50 is not None)

# Clone abs50 to create abs999 (checked)
abs999 = ET.fromstring(ET.tostring(abs50))
abs999.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId', '999')
lvl0 = abs999.find('.//w:lvl[@w:ilvl="0"]', ns)
lvlText = lvl0.find('w:lvlText', ns)
lvlText.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '\uf0fe') # checked box
print("abs999 lvlText:", hex(ord(lvlText.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val'))))

# Insert abs999 before the first <w:num> element
first_num = root.find('w:num', ns)
idx = list(root).index(first_num)
root.insert(idx, abs999)

# Create num 999 pointing to abstractNumId 999
num999_xml = """
<w:num xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:numId="999">
    <w:abstractNumId w:val="999"/>
</w:num>
"""
root.append(ET.fromstring(num999_xml))

# Write updated numbering.xml into a new docx
new_num_xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
with zipfile.ZipFile(doc_path, 'r') as zin:
    with zipfile.ZipFile(test_out, 'w') as zout:
        for item in zin.infolist():
            if item.filename == "word/numbering.xml":
                zout.writestr(item, new_num_xml)
            else:
                zout.writestr(item, zin.read(item.filename))

# Now test opening with python-docx and setting a paragraph's numId to 999!
doc = docx.Document(test_out)
t0 = doc.tables[0]
c0 = t0.rows[0].cells[0]
# Salutation is in nested table 0
# Cell 0 has numId 51 (MR)
# Let's verify we can find numId in the first cell of nested table 0
root_c0 = ET.fromstring(c0._tc.xml)
first_p = root_c0.find('.//w:numPr/w:numId[@w:val="51"]', ns)
print("Found MR numId=51?", first_p is not None)

# In docx, let's find the paragraph element in XML and change val to 999
for p in c0._tc.findall('.//w:p', ns):
    numId_elem = p.find('.//w:numPr/w:numId', ns)
    if numId_elem is not None and numId_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') == '51':
        print("Changing numId from 51 to 999")
        numId_elem.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '999')

doc.save(test_out)
print("Successfully modified and saved test_out:", os.path.getsize(test_out))

# Re-open to verify
doc_verify = docx.Document(test_out)
print("Reopened successfully without any docx corruption!")
