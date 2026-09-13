import docx
from xml.etree import ElementTree as ET

doc = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")

# Let's inspect all paragraphs across all cells and body for any symbol or character
xml_str = doc._part._element.xml
root = ET.fromstring(xml_str)

# Find all text elements
all_texts = root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')
print(f"Total <w:t> elements in doc: {len(all_texts)}")
for t in all_texts:
    if any(c in t.text for c in ['☑', '☐', '√', 'X', 'x', 'ü', 'þ', 'ý', '', '', '']):
        print(f"Special char in text: {repr(t.text)}")

# Check all numPr
all_numPr = root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
print(f"Total <w:numPr> elements: {len(all_numPr)}")
