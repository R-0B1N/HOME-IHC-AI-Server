import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from xml.etree import ElementTree as ET
import os

TEMPLATE_PATH = "artifacts/Property Acknowledgement Document Template.docx"
GOLDEN_PATH = "docs/Property Acknowledgement Document Correct Format.docx"
OUTPUT_PATH = "artifacts/Viewing_Acknowledgement_Populated.docx"

def set_cell_checkbox(cell, checked: bool):
    """Sets paragraph in cell to numId=999 (checked) or numId=998 (unchecked)."""
    p = cell.paragraphs[0] if cell.paragraphs else None
    if p is not None:
        numId_elem = p._p.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
        if numId_elem is not None:
            numId_elem.set(qn('w:val'), '999' if checked else '998')

def test_populate():
    doc = docx.Document(TEMPLATE_PATH)
    
    # 1. Form No (Paragraph 5)
    # P5: 'CUSTOMER PROPERTY VIEWING ACKNOWLEDGEMENT \t                                  \t\t      No: 0257'
    p5 = doc.paragraphs[5]
    # Remove digit runs after 'No: '
    # In P5, runs 7..10 are the digits
    while len(p5.runs) > 7:
        p5._p.remove(p5.runs[-1]._r)
    if len(p5.runs) > 6 and p5.runs[6].text == 'No: ':
        # Add digit runs for form_no, e.g. "0190" or "0257"
        form_no = "0257"
        for digit in form_no:
            r = p5.add_run(digit)
            r.bold = True
            r.font.size = Pt(14.0)
            r.font.color.rgb = RGBColor(255, 0, 0)
            
    # 2. Header Date (Paragraph 7)
    # P7 Run 12 is '27.03.2025'
    p7 = doc.paragraphs[7]
    if len(p7.runs) > 12:
        p7.runs[12].text = "27.03.2025"
        p7.runs[12].bold = True

    # 3. Table 0
    t0 = doc.tables[0]
    c0 = t0.rows[0].cells[0]
    c1 = t0.rows[0].cells[1]

    # Full Name: c0.paragraphs[0]
    # r0: 'Full ', r1: 'Name:', r2: ' ', r3: ' ', r4: 'Nick'
    p_name = c0.paragraphs[0]
    if len(p_name.runs) > 4:
        p_name.runs[4].text = "Nick"

    # No of pax: c0.paragraphs[2]
    # r0: 'No of pax:', r1: ' ', r2: '2'
    p_pax = c0.paragraphs[2]
    if len(p_pax.runs) > 2:
        p_pax.runs[2].text = "2"

    # Company Name: c0.paragraphs[4]
    # r0: 'Company Name: ', r1: 'ELPIJI (M) SDN BHD'
    p_comp = c0.paragraphs[4]
    if len(p_comp.runs) > 1:
        p_comp.runs[1].text = "ELPIJI (M) SDN BHD"

    # Company Address: c0.paragraphs[6] and [7]
    p_addr1 = c0.paragraphs[6]
    p_addr2 = c0.paragraphs[7]
    if len(p_addr1.runs) > 3:
        p_addr1.runs[3].text = "601-A, Level 6, Tower A, Uptown 5, 5, Jalan SS21/39,"
    if len(p_addr2.runs) > 0:
        p_addr2.runs[0].text = "Damansara Uptown, 47400 Petaling Jaya, Selangor D. E., Malaysia"

    # Tel (Hp): c0.paragraphs[10]
    p_tel = c0.paragraphs[10]
    if len(p_tel.runs) > 1:
        p_tel.runs[1].text = "+60126761818"

    # Called in date: c0.paragraphs[11]
    p_called = c0.paragraphs[11]
    if len(p_called.runs) > 2:
        p_called.runs[2].text = "17-03-2025"

    # Customer's request: c1.paragraphs[1]
    p_req = c1.paragraphs[1]
    # r0: 'Customer’s request: ', r1: 'Required', r2: ' 2-', r3: '3 acres', r4: ' Industrial Factory & Land with TNB Supply: 400amp'
    while len(p_req.runs) > 1:
        p_req._p.remove(p_req.runs[-1]._r)
    r_req = p_req.add_run("Required 2-3 acres Industrial Factory & Land with TNB Supply: 400amp")
    r_req.bold = True
    r_req.font.size = Pt(10.0)

    # Types of Properties: c1.paragraphs[5]
    p_types = c1.paragraphs[5]
    if len(p_types.runs) > 2:
        p_types.runs[2].text = "Industrial Factory and Land"

    # Location: c1.paragraphs[9]
    p_loc = c1.paragraphs[9]
    if len(p_loc.runs) > 2:
        p_loc.runs[2].text = "Temerloh"

    # Remarks: c1.paragraphs[11]
    p_rem = c1.paragraphs[11]
    while len(p_rem.runs) > 2:
        p_rem._p.remove(p_rem.runs[-1]._r)
    p_rem.runs[2].text = "Currently Industrial Factory has 300amp"

    # Signatures
    p16 = doc.paragraphs[16]
    if len(p16.runs) > 1:
        p16.runs[1].text = " Nick"
    if len(p16.runs) > 11:
        p16.runs[11].text = "Leong Chu Ping"

    p17 = doc.paragraphs[17]
    if len(p17.runs) > 2:
        p17.runs[2].text = "27.03.2025"
    if len(p17.runs) > 12:
        p17.runs[12].text = "27.03.2025"

    # Page 2 Header Date
    p19 = doc.paragraphs[19]
    if len(p19.runs) > 16:
        p19.runs[16].text = "27.03.2025"

    # Table 1: Row 1
    t1 = doc.tables[1]
    # Row 1 Col 0: 1.
    # Col 1: details
    # Col 2: date
    # Col 3: price
    # Col 4: desc

    # Table 2: Row 1
    # Col 2: 1 set

    # Bottom date: p26
    p26 = doc.paragraphs[26]
    if len(p26.runs) > 0:
        p26.runs[0].text = "27.03.2025"

    doc.save(OUTPUT_PATH)
    print("Saved output to", OUTPUT_PATH)

test_populate()
