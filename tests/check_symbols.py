import zipfile
from xml.etree import ElementTree as ET

with zipfile.ZipFile("docs/Property Acknowledgement Document Correct Format.docx") as z:
    doc_xml = z.read("word/document.xml").decode('utf-8')
    num_xml = z.read("word/numbering.xml").decode('utf-8')

print("Checking document.xml for check symbols:")
for sym in ['\uf0fe', '\uf0fd', '\u2611', '\u2610', '☑', '☐']:
    print(f"doc_xml count of {repr(sym)} ({hex(ord(sym))}): {doc_xml.count(sym)}")

print("\nChecking numbering.xml for check symbols:")
for sym in ['\uf0fe', '\uf0fd', '\u2611', '\u2610', '☑', '☐', '\uf0a8']:
    print(f"num_xml count of {repr(sym)} ({hex(ord(sym))}): {num_xml.count(sym)}")
