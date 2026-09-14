"""
Property Viewing Acknowledgement Document Engine for Home IHC AI CRM.
Handles dynamic population of Microsoft Word (.docx) templates, OpenXML border
stabilization, native Wingdings bullet checkbox toggling, and headless PDF conversion.
"""

import os
import shutil
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

logger = logging.getLogger(__name__)

# Root directories & Template discovery
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_TEMPLATE = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "templates", "Property Acknowledgement Document.docx"))
_REPO_TEMPLATE = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "..", "..", "docs", "Property Acknowledgement Document.docx"))

if os.path.exists(_PKG_TEMPLATE):
    DEFAULT_TEMPLATE_PATH = _PKG_TEMPLATE
elif os.path.exists(_REPO_TEMPLATE):
    DEFAULT_TEMPLATE_PATH = _REPO_TEMPLATE
else:
    DEFAULT_TEMPLATE_PATH = _PKG_TEMPLATE

# Output directory: backend/data/output/acknowledgements or /tmp/acknowledgements fallback
_CANDIDATE_OUT = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "..", "data", "output", "acknowledgements"))
DEFAULT_OUTPUT_DIR = os.getenv("ACKNOWLEDGEMENTS_OUTPUT_DIR") or _CANDIDATE_OUT


def stabilize_table_borders(table: docx.table.Table) -> None:
    """
    Injects explicit <w:tblBorders> into Table tblPr.
    Ensures that outer black border and center vertical dividing line
    render consistently across Microsoft Word, LibreOffice, QuickLook, and PDF engines
    matching the native TableGrid styling (sz="4").
    """
    tbl_borders = parse_xml(
        r"""
        <w:tblBorders {}>
            <w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>
            <w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>
            <w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>
            <w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>
            <w:insideH w:val="none"/>
            <w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>
        </w:tblBorders>
        """.format(nsdecls("w"))
    )
    existing = table._tbl.tblPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblBorders')
    if existing is not None:
        table._tbl.tblPr.remove(existing)
    table._tbl.tblPr.append(tbl_borders)


def set_cell_checkbox(cell: docx.table._Cell, checked: bool) -> None:
    """
    Sets a clean, deterministic Unicode square checkbox (☐ or ☑) in the cell.
    Completely strips any OpenXML <w:numPr> list numbering to prevent Microsoft Word
    from rendering decimal numbers (1., 2., 3.) or bullet discs.
    """
    p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    
    # Strip any <w:numPr> from the paragraph XML
    for np in p._p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr'):
        parent = np.getparent()
        if parent is not None:
            parent.remove(np)

    box_char = "☑" if checked else "☐"
    
    # Remove existing runs
    while p.runs:
        p._p.remove(p.runs[-1]._r)
        
    r = p.add_run(box_char)
    r.font.name = "Arial"
    r.font.size = Pt(10.5)
    r.bold = checked
    
    # Tight paragraph formatting
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = Pt(11)


def get_sample_acknowledgement_data() -> Dict[str, Any]:
    """
    Returns a complete, realistic sample dataset matching operational reference
    (Form 0190 / Form 0257, Mentakab Industrial Land / Lot 1745, Nick / Lee Wan Soon).
    """
    return {
        "form_no": "0190",
        "date": "27.03.2025",
        "salutation": "MR",
        "customer_name": "Lee Wan Soon",
        "no_of_pax": "2",
        "company_name": "ELPIJI (M) SDN BHD",
        "company_reg_no": "",
        "company_address": "601-A, Level 6, Tower A, Uptown 5, 5, Jalan SS21/39, Damansara Uptown, 47400 Petaling Jaya, Selangor D. E., Malaysia",
        "car_plate": "",
        "phone": "012-329 2280",
        "called_in_date": "17-03-2025",
        "referral_source": "Bentongland Website",
        "customer_request": "Required 2-3 acres Industrial Factory & Land with TNB Supply: 400amp",
        "requirement_summary": "Industrial Factory and Land",
        "property_types": ["Industrial Land", "Factory"],
        "target_location": "Temerloh",
        "remarks": "Currently Industrial Factory has 300amp",
        "assigned_to": "Direct Seller",
        "partner_agency": "Chester Properties Sdn. Bhd [E(1)1321/16]",
        "customer_signer": "Lee Wan Soon on behalf of ELPIJI (M) SDN BHD",
        "staff_name": "Leong Chu Ping",
        "properties_viewed": [
            {
                "no": "1.",
                "details": "2.7 acres Mentakab Industry Land For Sale LOT 1745",
                "date": "27.03.2025",
                "price": "RM 4,000,000",
                "description": "• Freehold & Industrial Title\n• Connected electrical & water supply and Fencing & Gated"
            }
        ],
        "documents_submitted": [
            {
                "title_details": "Title ",
                "qty": "1 set",
                "remarks": "Whatsapp Messenger"
            }
        ]
    }


def populate_acknowledgement_document(
    data: Dict[str, Any],
    template_path: str = DEFAULT_TEMPLATE_PATH
) -> docx.Document:
    """
    Populates all 22 fields of the Property Viewing Acknowledgement Word document.
    Uses the golden template architecture with compact nested checkbox tables,
    preserving exact A4 pagination and preventing signature block split across pages.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Base template not found at {template_path}")

    doc = docx.Document(template_path)

    # 1. Update Form No (Paragraph 5)
    form_no = str(data.get("form_no", "0190"))
    p5 = doc.paragraphs[5]
    no_run_idx = -1
    for idx, r in enumerate(p5.runs):
        if "No:" in r.text:
            no_run_idx = idx
            break
    if no_run_idx != -1:
        while len(p5.runs) > no_run_idx + 1:
            p5._p.remove(p5.runs[-1]._r)
        for digit in form_no:
            r = p5.add_run(digit)
            r.bold = True
            r.font.size = Pt(14.0)
            r.font.color.rgb = RGBColor(255, 0, 0)

    # 2. Update Header Date (Paragraph 7)
    header_date = str(data.get("date", datetime.now().strftime("%d.%m.%Y")))
    p7 = doc.paragraphs[7]
    date_updated = False
    for r in p7.runs:
        if r.text.strip() == "27.03.2025" or (r.text.strip() and r.text.strip()[0].isdigit() and "." in r.text):
            r.text = header_date
            r.bold = True
            date_updated = True
            break
    if not date_updated and len(p7.runs) > 12:
        p7.runs[12].text = header_date
        p7.runs[12].bold = True

    # 3. Table 0 (Customer Particulars & Customer Requirements)
    t0 = doc.tables[0]
    stabilize_table_borders(t0)
    c0 = t0.rows[0].cells[0]
    c1 = t0.rows[0].cells[1]

    # Find nested tables in c0
    c0_nested = [docx.table.Table(node, c0) for node in c0._tc.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')]

    # 3.1 Salutation in c0 nested table 0 (1 row x 6 cols)
    salutation = (data.get("salutation") or "MR").upper()
    if c0_nested:
        t_sal = c0_nested[0]
        # Insert a clean line of breathing space above t_sal so MR/MRS/MS does not stick to the top border
        tc_children = list(c0._tc)
        tbl_elem = t_sal._tbl
        if tbl_elem in tc_children:
            tbl_idx = tc_children.index(tbl_elem)
            if tbl_idx <= 1:
                top_spacer = parse_xml(r'<w:p {}><w:pPr><w:spacing w:before="80" w:after="40"/><w:rPr><w:sz w:val="14"/></w:rPr></w:pPr><w:r><w:t> </w:t></w:r></w:p>'.format(nsdecls('w')))
                c0._tc.insert(tbl_idx, top_spacer)

        # Col 0: MR, Col 2: MRS, Col 4: MS
        set_cell_checkbox(t_sal.rows[0].cells[0], "MR" in salutation and "MRS" not in salutation)
        set_cell_checkbox(t_sal.rows[0].cells[2], "MRS" in salutation)
        set_cell_checkbox(t_sal.rows[0].cells[4], "MS" in salutation)

    # 3.2 Full Name in c0.paragraphs[0]
    cust_name = data.get("customer_name") or data.get("name") or ""
    p_name = c0.paragraphs[0]
    name_run = None
    for r in p_name.runs:
        if r.text.strip() in ["Nick", "Lee Wan Soon"] or (name_run is None and r.text not in ["Full ", "Name:", " "]):
            name_run = r
    if name_run is not None:
        name_run.text = cust_name
    elif len(p_name.runs) > 4:
        p_name.runs[4].text = cust_name
    elif cust_name:
        p_name.add_run(cust_name)

    # 3.3 No of Pax in c0.paragraphs[2]
    pax = str(data.get("no_of_pax", "2"))
    p_pax = c0.paragraphs[2]
    pax_updated = False
    for r in p_pax.runs:
        if r.text.strip().isdigit():
            r.text = pax
            r.bold = True
            pax_updated = True
            break
    if not pax_updated:
        r = p_pax.add_run(f" {pax}")
        r.bold = True

    # 3.4 Company Name & Co Reg No in c0.paragraphs[4]
    company_name = data.get("company_name", "")
    reg_no = data.get("company_reg_no", "")
    company_full = f"{company_name} ({reg_no})" if reg_no else company_name
    p_comp = c0.paragraphs[4]
    if len(p_comp.runs) > 1:
        p_comp.runs[1].text = company_full
        if company_full:
            p_comp.runs[0].font.highlight_color = WD_COLOR_INDEX.YELLOW
            p_comp.runs[1].font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            p_comp.runs[0].font.highlight_color = None
            p_comp.runs[1].font.highlight_color = None
    elif company_full:
        r = p_comp.add_run(company_full)
        r.bold = True
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW

    # 3.5 Company Address in c0.paragraphs[6] and c0.paragraphs[7]
    company_addr = data.get("company_address", "")
    p_addr1 = c0.paragraphs[6]
    p_addr2 = c0.paragraphs[7]
    if company_addr:
        addr_lines = company_addr.split("\n")
        line1 = addr_lines[0].strip()
        line2 = "\n".join(addr_lines[1:]).strip() if len(addr_lines) > 1 else ""
        if len(p_addr1.runs) > 3:
            p_addr1.runs[3].text = line1
        if len(p_addr2.runs) > 0:
            p_addr2.runs[0].text = line2
    else:
        if len(p_addr1.runs) > 3:
            p_addr1.runs[3].text = ""
        if len(p_addr2.runs) > 0:
            p_addr2.runs[0].text = ""

    # 3.6 Car Plate No in c0.paragraphs[9]
    car_plate = data.get("car_plate", "")
    p_car = c0.paragraphs[9]
    if car_plate:
        if len(p_car.runs) > 1:
            p_car.runs[1].text = car_plate
        else:
            r = p_car.add_run(car_plate)
            r.bold = True
            r.font.size = Pt(10.0)

    # 3.7 Tel (Hp) in c0.paragraphs[10]
    phone = data.get("phone", "")
    p_tel = c0.paragraphs[10]
    if len(p_tel.runs) > 1:
        p_tel.runs[1].text = phone
    elif phone:
        p_tel.add_run(phone)

    # 3.8 Called In Date in c0.paragraphs[11]
    called_in = data.get("called_in_date", header_date)
    p_called = c0.paragraphs[11]
    if len(p_called.runs) > 2:
        p_called.runs[2].text = called_in
        p_called.runs[2].bold = True

    # 3.9 Marketing Referral Sources in c0 nested table 1 (6 rows x 2 cols)
    ref_source = (data.get("referral_source") or "").lower()
    if len(c0_nested) > 1:
        t_ref = c0_nested[1]
        source_keys = ["iproperty", "mudah", "bentongland", "banner", "whatsapp", "facebook"]
        for r_i, key in enumerate(source_keys):
            if r_i < len(t_ref.rows):
                is_match = key in ref_source
                set_cell_checkbox(t_ref.rows[r_i].cells[0], is_match)

    # 4. Table 0 Cell 1 (Customer Requirements)
    # 4.1 Customer Request in c1.paragraphs[1]
    cust_req = data.get("customer_request", "")
    p_req = c1.paragraphs[1]
    if cust_req:
        while len(p_req.runs) > 1:
            p_req._p.remove(p_req.runs[-1]._r)
        r = p_req.add_run(cust_req)
        r.bold = True
        r.font.size = Pt(10.0)

    # 4.2 Requirement summary in c1.paragraphs[5]
    req_summary = data.get("requirement_summary", "")
    p_sum = c1.paragraphs[5]
    if req_summary:
        if len(p_sum.runs) > 2:
            p_sum.runs[2].text = req_summary
        elif len(p_sum.runs) == 2:
            p_sum.add_run(req_summary)

    # 4.3 Property Types in c1 nested table 0 (4 rows x 4 cols)
    c1_nested = [docx.table.Table(node, c1) for node in c1._tc.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl')]
    prop_types = [pt.lower() for pt in data.get("property_types", [])]
    if c1_nested:
        t_props = c1_nested[0]
        # Row 0 Col 0: Agricultural Land
        set_cell_checkbox(t_props.rows[0].cells[0], any("agri" in pt for pt in prop_types))
        # Row 1 Col 0: Commercial Land
        set_cell_checkbox(t_props.rows[1].cells[0], any("comm" in pt for pt in prop_types))
        # Row 1 Col 2: Hotel / Resort
        set_cell_checkbox(t_props.rows[1].cells[2], any("hotel" in pt or "resort" in pt for pt in prop_types))
        # Row 2 Col 0: Industrial Land
        set_cell_checkbox(t_props.rows[2].cells[0], any("ind" in pt for pt in prop_types))
        # Row 2 Col 2: Factory
        set_cell_checkbox(t_props.rows[2].cells[2], any("factory" in pt for pt in prop_types))
        # Row 3 Col 0: Residential Land
        set_cell_checkbox(t_props.rows[3].cells[0], any("res" in pt for pt in prop_types))
        # Row 3 Col 2: Condominium
        set_cell_checkbox(t_props.rows[3].cells[2], any("condo" in pt for pt in prop_types))

    # 4.4 Target Location in c1.paragraphs[9]
    loc = data.get("target_location", "")
    p_loc = c1.paragraphs[9]
    if loc:
        if len(p_loc.runs) > 2:
            p_loc.runs[2].text = loc
        elif len(p_loc.runs) == 2:
            p_loc.add_run(loc)

    # 4.5 Remarks in c1.paragraphs[11]
    remarks = data.get("remarks", "")
    p_rem = c1.paragraphs[11]
    if remarks:
        while len(p_rem.runs) > 2:
            p_rem._p.remove(p_rem.runs[-1]._r)
        if len(p_rem.runs) == 2:
            p_rem.add_run(remarks)
        elif len(p_rem.runs) > 2:
            p_rem.runs[2].text = remarks

    # 4.6 Assigned To in c1 nested table 1 (2 rows x 2 cols)
    assigned = (data.get("assigned_to") or "").lower()
    if len(c1_nested) > 1:
        t_ass = c1_nested[1]
        is_direct = "direct" in assigned
        is_cobroke = "co-broke" in assigned or "cobroke" in assigned
        if not is_direct and not is_cobroke:
            is_direct = True
        set_cell_checkbox(t_ass.rows[0].cells[0], is_cobroke)
        set_cell_checkbox(t_ass.rows[1].cells[0], is_direct)

    # 4.7 Compact empty spacing paragraphs in c0 and c1 to preserve Page 1 height budget
    for cell in [c0, c1]:
        for p in cell.paragraphs:
            if not p.text.strip():
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = Pt(3)
                for r in p.runs:
                    r.font.size = Pt(3)
            else:
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = Pt(11)

    # 4.8 Legal Partner Agency & Disclaimer formatting
    agency_name = data.get("partner_agency")
    p_disclaimer = None
    p_sig_lines = None
    p_sig_labels = None
    p_name = None
    p_date = None

    for p in doc.paragraphs:
        txt = p.text.strip()
        if "I/We acknowledge and confirm" in txt:
            p_disclaimer = p
            if agency_name and "Era Realtor Sdn. Bhd. [E(1)2053/1]" in txt:
                p.text = txt.replace("Era Realtor Sdn. Bhd. [E(1)2053/1]", agency_name)
        elif "_________" in txt:
            if p_sig_lines is None:
                p_sig_lines = p
        elif "Customer" in txt and "Attended staff" in txt:
            p_sig_labels = p
        elif "Name:" in txt and "Customer" not in txt and p_name is None:
            p_name = p
        elif "Date:" in txt and "PARTICULARS" not in txt and "Property Proposed" not in txt and p_date is None:
            p_date = p

    # Format disclaimer tightly (8.0pt, single line spacing, 3pt before/after)
    if p_disclaimer:
        p_disclaimer.paragraph_format.space_before = Pt(3)
        p_disclaimer.paragraph_format.space_after = Pt(4)
        p_disclaimer.paragraph_format.line_spacing = Pt(10)
        for r in p_disclaimer.runs:
            r.font.size = Pt(8.0)

    # Reclaim vertical space from empty paragraphs between disclaimer and signature block
    if p_disclaimer and p_sig_lines:
        p_disc_idx = list(doc.paragraphs).index(p_disclaimer)
        p_sig_idx = list(doc.paragraphs).index(p_sig_lines)
        for mid_idx in range(p_disc_idx + 1, p_sig_idx):
            mid_p = doc.paragraphs[mid_idx]
            if not mid_p.text.strip():
                mid_p.paragraph_format.space_before = Pt(0)
                mid_p.paragraph_format.space_after = Pt(1)
                mid_p.paragraph_format.line_spacing = Pt(2)
                for r in mid_p.runs:
                    r.font.size = Pt(2)

    # 5. Signatures (Strict Page 1 Confinement)
    signer_name = data.get("customer_signer", cust_name)
    staff_name = data.get("staff_name", "Leong Chu Ping")
    signer_date = data.get("signer_date", header_date)
    staff_date = data.get("staff_date", header_date)

    if p_sig_lines:
        p_sig_lines.paragraph_format.space_before = Pt(2)
        p_sig_lines.paragraph_format.space_after = Pt(1)
        p_sig_lines.paragraph_format.line_spacing = Pt(11)
        p_sig_lines.paragraph_format.keep_with_next = True

    if p_sig_labels:
        p_sig_labels.paragraph_format.space_before = Pt(0)
        p_sig_labels.paragraph_format.space_after = Pt(1)
        p_sig_labels.paragraph_format.line_spacing = Pt(11)
        p_sig_labels.paragraph_format.keep_with_next = True
        for r in p_sig_labels.runs:
            r.font.size = Pt(9.0)

    if p_name:
        p_name.paragraph_format.space_before = Pt(0)
        p_name.paragraph_format.space_after = Pt(1)
        p_name.paragraph_format.line_spacing = Pt(11)
        p_name.paragraph_format.keep_with_next = True
        if len(p_name.runs) > 1:
            p_name.runs[1].text = f" {signer_name}"
        if len(p_name.runs) > 11:
            p_name.runs[11].text = staff_name
        for r in p_name.runs:
            r.font.size = Pt(9.0)

    if p_date:
        p_date.paragraph_format.space_before = Pt(0)
        p_date.paragraph_format.space_after = Pt(2)
        p_date.paragraph_format.line_spacing = Pt(11)
        if len(p_date.runs) > 2:
            p_date.runs[2].text = signer_date
        if len(p_date.runs) > 12:
            p_date.runs[12].text = staff_date
        for r in p_date.runs:
            r.font.size = Pt(9.0)

        # Guarantee explicit page break after signature Date line so Page 2 starts cleanly
        has_break = False
        p_date_idx = list(doc.paragraphs).index(p_date)
        if p_date_idx + 1 < len(doc.paragraphs):
            next_p = doc.paragraphs[p_date_idx + 1]
            if '<w:br w:type="page"/>' in next_p._p.xml:
                has_break = True
        if not has_break:
            r_br = p_date.add_run()
            r_br.add_break(docx.enum.text.WD_BREAK.PAGE)

    # 6. Page 2 Header Date
    for p in doc.paragraphs:
        txt = p.text.strip()
        if "Property Proposed" in txt and "Date:" in txt:
            if len(p.runs) > 16:
                p.runs[16].text = header_date
            elif len(p.runs) > 1:
                p.runs[-1].text = f" {header_date}"

    # 7. Table 1 (Properties Viewed)
    t1 = doc.tables[1]
    props = data.get("properties_viewed", [])
    if props:
        for idx, prop in enumerate(props):
            row_idx = idx + 1
            if row_idx < len(t1.rows):
                row = t1.rows[row_idx]
                if prop.get("no"):
                    p_no = row.cells[0].paragraphs[-1]
                    p_no.text = prop["no"]
                if prop.get("details"):
                    p_det = row.cells[1].paragraphs[0]
                    p_det.text = f"\n{prop['details']}"
                if prop.get("date"):
                    p_dt = row.cells[2].paragraphs[0]
                    p_dt.text = f"\n{prop['date']}"
                if prop.get("price"):
                    price_val = prop["price"]
                    p_pr0 = row.cells[3].paragraphs[0]
                    p_pr0.text = "\nSelling Price:"
                    clean_price = price_val.replace("Selling Price:", "").strip()
                    if len(row.cells[3].paragraphs) > 1:
                        row.cells[3].paragraphs[1].text = clean_price
                    else:
                        row.cells[3].add_paragraph(clean_price)
                if prop.get("description"):
                    desc = prop["description"]
                    lines = desc.split("\n")
                    for l_i, line in enumerate(lines):
                        if l_i < len(row.cells[4].paragraphs):
                            if l_i == 0:
                                row.cells[4].paragraphs[0].text = f"\n{line}"
                            else:
                                row.cells[4].paragraphs[l_i].text = line
                        else:
                            row.cells[4].add_paragraph(line)

    # 8. Table 2 (Submission of Documents & Checkboxes)
    t2 = doc.tables[2]
    docs_sub = data.get("documents_submitted", [])
    if len(t2.rows) > 1:
        row = t2.rows[1]
        doc_item = docs_sub[0] if docs_sub else {}
        if doc_item.get("qty"):
            row.cells[2].paragraphs[0].text = f"\n{doc_item['qty']}"

        # Col 1: Documents Checklist (GM, GRN, HSM, HSD, Pajakan Mukim, Pajakan Negeri, Topo Plan)
        c_doc = row.cells[1]
        checklist_items = ["GM", "GRN", "HSM", "HSD", "Pajakan Mukim", "Pajakan Negeri", "Topo Plan"]
        for p in c_doc.paragraphs:
            for np in p._p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr'):
                parent = np.getparent()
                if parent is not None:
                    parent.remove(np)
            txt = p.text.strip().lstrip("☐").lstrip("☑").strip()
            for item in checklist_items:
                if txt == item or (item in txt and "Title" not in txt):
                    is_chk = any(item.lower() in str(d).lower() for d in [doc_item.get("title_details", ""), doc_item.get("type", "")])
                    p.text = f"{'☑' if is_chk else '☐'}  {item}"
                    if p.runs:
                        p.runs[0].font.name = "Arial"
                        p.runs[0].font.size = Pt(9.5)
                    break

        # Col 4: Remarks Checklist (Whatsapp Messenger, Handover by hardcopy)
        c_rem = row.cells[4]
        rem_val = (doc_item.get("remarks") or "").lower()
        for p in c_rem.paragraphs:
            for np in p._p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr'):
                parent = np.getparent()
                if parent is not None:
                    parent.remove(np)
            txt = p.text.strip().lstrip("☐").lstrip("☑").strip()
            if "whatsapp" in txt.lower():
                is_chk = "whatsapp" in rem_val or "messenger" in rem_val
                p.text = f"{'☑' if is_chk else '☐'}  Whatsapp Messenger"
                if p.runs:
                    p.runs[0].font.name = "Arial"
                    p.runs[0].font.size = Pt(9.5)
            elif "hardcopy" in txt.lower():
                is_chk = "hardcopy" in rem_val
                p.text = f"{'☑' if is_chk else '☐'}  Handover by hardcopy"
                if p.runs:
                    p.runs[0].font.name = "Arial"
                    p.runs[0].font.size = Pt(9.5)

    # 9. Page 2 Bottom Date (Paragraph with date e.g. 27.03.2025)
    for p in doc.paragraphs:
        txt = p.text.strip()
        if "Page | 2" in txt or txt == "27.03.2025" or (txt.startswith("2") and len(txt) == 10 and "." in txt):
            if "CUSTOMER" not in txt and "PARTICULARS" not in txt and "Property Proposed" not in txt:
                if len(p.runs) > 0 and "." in p.runs[0].text:
                    p.runs[0].text = header_date

    # 10. Global XML Sanitization: Remove ALL <w:numPr> elements to eliminate numbering/bullets
    for np in doc._element.xpath('.//w:numPr'):
        parent = np.getparent()
        if parent is not None:
            parent.remove(np)

    return doc


def convert_docx_to_pdf(docx_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    Converts a .docx file to .pdf using headless LibreOffice if available.
    Returns path to generated PDF, or None if conversion utility is unavailable.
    """
    if output_dir is None:
        output_dir = os.path.dirname(docx_path)

    base_name = os.path.splitext(os.path.basename(docx_path))[0]
    expected_pdf = os.path.join(output_dir, f"{base_name}.pdf")

    # Check for soffice or libreoffice
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        logger.warning("Neither soffice nor libreoffice is installed on this host. Skipping PDF conversion.")
        return None

    try:
        cmd = [
            converter,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            docx_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if result.returncode == 0 and os.path.exists(expected_pdf):
            logger.info(f"Successfully converted docx to PDF: {expected_pdf}")
            return expected_pdf
        else:
            logger.error(f"LibreOffice conversion failed: {result.stderr}")
            return None
    except Exception as e:
        logger.error(f"Error during PDF conversion: {e}")
        return None


def generate_viewing_acknowledgement(
    data: Optional[Dict[str, Any]] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    filename_prefix: Optional[str] = None
) -> Dict[str, Any]:
    """
    High-level API:
    Generates populated Word (.docx) document, stabilizes OpenXML borders,
    and converts to PDF if possible.

    Returns:
        {
            "docx_path": str,
            "pdf_path": str | None,
            "form_no": str,
            "customer_name": str
        }
    """
    if data is None:
        data = get_sample_acknowledgement_data()

    os.makedirs(output_dir, exist_ok=True)

    form_no = data.get("form_no", "0000")
    cust_name = data.get("customer_name") or data.get("name") or "Customer"
    sanitized_name = "".join(c if c.isalnum() else "_" for c in cust_name).strip("_")

    if not filename_prefix:
        filename_prefix = f"Viewing_Acknowledgement_{form_no}_{sanitized_name}"

    docx_filename = f"{filename_prefix}.docx"
    docx_path = os.path.join(output_dir, docx_filename)

    doc = populate_acknowledgement_document(data)
    doc.save(docx_path)
    logger.info(f"Saved populated acknowledgement docx to {docx_path}")

    pdf_path = convert_docx_to_pdf(docx_path, output_dir=output_dir)

    return {
        "docx_path": docx_path,
        "pdf_path": pdf_path,
        "form_no": form_no,
        "customer_name": cust_name
    }


class ViewingAcknowledgementEngine:
    """
    Object-Oriented Engine for Customer Property Viewing Acknowledgements.
    Encapsulates template management, OpenXML border stabilization,
    22-field data mapping, and headless PDF conversion.
    """

    def __init__(self, template_path: str = DEFAULT_TEMPLATE_PATH, output_dir: str = DEFAULT_OUTPUT_DIR):
        self.template_path = template_path
        self.output_dir = output_dir

    @staticmethod
    def get_sample_data() -> Dict[str, Any]:
        """Returns sample 22-field acknowledgement dataset."""
        return get_sample_acknowledgement_data()

    def stabilize_borders(self, table: docx.table.Table) -> None:
        """Injects explicit <w:tblBorders> to stabilize table styling."""
        stabilize_table_borders(table)

    def populate(self, data: Dict[str, Any]) -> docx.Document:
        """Populates the 22-field template from dataset."""
        return populate_acknowledgement_document(data, template_path=self.template_path)

    def convert_to_pdf(self, docx_path: str, output_dir: Optional[str] = None) -> Optional[str]:
        """Converts generated .docx to .pdf via headless LibreOffice."""
        return convert_docx_to_pdf(docx_path, output_dir=output_dir or self.output_dir)

    def generate(
        self,
        data: Optional[Dict[str, Any]] = None,
        filename_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """High-level execution generating DOCX and optional PDF."""
        return generate_viewing_acknowledgement(
            data=data,
            output_dir=self.output_dir,
            filename_prefix=filename_prefix
        )
