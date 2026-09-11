"""
Property Viewing Acknowledgement Document Engine for Home IHC AI CRM.
Handles dynamic population of Microsoft Word (.docx) templates, OpenXML border
stabilization, Unicode checkbox toggling, and headless PDF conversion.
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
from docx.oxml.ns import nsdecls

logger = logging.getLogger(__name__)

# Root directories & Template discovery
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_TEMPLATE = os.path.join(_CURRENT_DIR, "..", "templates", "Property Acknowledgement Document.docx")
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
    render consistently across Microsoft Word, LibreOffice, QuickLook, and PDF engines.
    """
    tbl_borders = parse_xml(
        r"""
        <w:tblBorders {}>
            <w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>
            <w:left w:val="single" w:sz="8" w:space="0" w:color="000000"/>
            <w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>
            <w:right w:val="single" w:sz="8" w:space="0" w:color="000000"/>
            <w:insideH w:val="none"/>
            <w:insideV w:val="single" w:sz="8" w:space="0" w:color="000000"/>
        </w:tblBorders>
        """.format(nsdecls("w"))
    )
    table._tbl.tblPr.append(tbl_borders)


def get_sample_acknowledgement_data() -> Dict[str, Any]:
    """
    Returns a complete, realistic sample dataset matching operational reference
    (Form 0190, Mentakab Industrial Land / Lot 1745).
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
        "requirement_summary": "> Types of Properties: Industrial Factory and Land",
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
                "details": "2.7 acres Mentakab Industry\nLand For Sale\n\nLOT 1745",
                "date": "27.03.2025",
                "price": "Selling Price:\nRM 4,000,000",
                "description": "• Freehold & Industrial Title\n• Connected electrical & water supply and Fencing & Gated"
            }
        ],
        "documents_submitted": [
            {
                "title_details": "> Title Lot 1745\n☐ GM\n☐ GRN\n☐ HSM\n☐ HSD\n☐ Pajakan Mukim\n☐ Pajakan Negeri\n\n☑ Topo Plan and All CF Approved Industrial Factory Plan",
                "qty": "1 set",
                "remarks": "☑ Whatsapp Messenger\n\n☑ Handover by hardcopy"
            }
        ]
    }


def populate_acknowledgement_document(
    data: Dict[str, Any],
    template_path: str = DEFAULT_TEMPLATE_PATH
) -> docx.Document:
    """
    Populates the 22 fields of the Property Viewing Acknowledgement Word document.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Base template not found at {template_path}")

    doc = docx.Document(template_path)

    # 1. Update Form No (Paragraph 5)
    form_no = str(data.get("form_no", "0190"))
    p5 = doc.paragraphs[5]
    for r in p5.runs:
        if any(digit in r.text for digit in "0123456789"):
            r.text = ""
    run_no = p5.add_run(form_no)
    run_no.font.color.rgb = RGBColor(255, 0, 0)
    run_no.font.size = Pt(13.5)
    run_no.bold = True

    # 2. Update Header Date (Paragraph 7)
    header_date = str(data.get("date", datetime.now().strftime("%d.%m.%Y")))
    p7 = doc.paragraphs[7]
    run_date = p7.add_run(header_date)
    run_date.bold = True
    run_date.font.size = Pt(10.0)

    # 3. Table 0 Cell 0: Customer Particulars
    t0 = doc.tables[0]
    stabilize_table_borders(t0)
    c0 = t0.rows[0].cells[0]

    # Salutation
    salutation = (data.get("salutation") or "MR").upper()
    mr_box = "☑" if "MR" in salutation and "MRS" not in salutation else "☐"
    mrs_box = "☑" if "MRS" in salutation else "☐"
    ms_box = "☑" if "MS" in salutation else "☐"
    c0.paragraphs[1].text = f"          {mr_box}  MR              {mrs_box} MRS               {ms_box} MS"
    if len(c0.paragraphs[1].runs) > 0:
        c0.paragraphs[1].runs[0].bold = True

    # Full Name
    cust_name = data.get("customer_name") or data.get("name") or ""
    c0.paragraphs[2].text = f"Full Name:  {cust_name}"
    if len(c0.paragraphs[2].runs) > 0:
        c0.paragraphs[2].runs[0].bold = True

    # No of Pax
    pax = str(data.get("no_of_pax", "1"))
    c0.paragraphs[4].text = f"No of pax: {pax}"
    if len(c0.paragraphs[4].runs) > 0:
        c0.paragraphs[4].runs[0].bold = True

    # Company Name & Co Reg No
    company_name = data.get("company_name", "")
    reg_no = data.get("company_reg_no", "")
    company_full = f"{company_name} ({reg_no})" if reg_no else company_name
    c0.paragraphs[6].text = f"Company Name & Co Reg No: {company_full}".strip()
    if len(c0.paragraphs[6].runs) > 0:
        c0.paragraphs[6].runs[0].bold = True
        if company_name:
            c0.paragraphs[6].runs[0].font.highlight_color = WD_COLOR_INDEX.YELLOW

    # Company Address
    company_addr = data.get("company_address", "")
    c0.paragraphs[8].text = f"Company Address:\n{company_addr}" if company_addr else "Company Address:"
    if len(c0.paragraphs[8].runs) > 0:
        c0.paragraphs[8].runs[0].font.size = Pt(9.0)

    # Car Plate No
    car_plate = data.get("car_plate", "")
    c0.paragraphs[10].text = f"Car Plate No: {car_plate}"
    if len(c0.paragraphs[10].runs) > 0 and car_plate:
        c0.paragraphs[10].runs[0].bold = True

    # Tel (Hp)
    phone = data.get("phone", "")
    c0.paragraphs[12].text = f"Tel (Hp): {phone}"
    if len(c0.paragraphs[12].runs) > 0:
        c0.paragraphs[12].runs[0].bold = True

    # Called In Date
    called_in = data.get("called_in_date", header_date)
    c0.paragraphs[14].text = f"Called in date: {called_in}"
    if len(c0.paragraphs[14].runs) > 0:
        c0.paragraphs[14].runs[0].bold = True

    # Marketing Referral Source
    ref_source = (data.get("referral_source") or "Bentongland Website").lower()
    sources = [
        ("iproperty", 16, "iProperty"),
        ("mudah", 17, "Mudah"),
        ("bentongland", 19, "Bentongland Website"),
        ("banner", 20, "Banner"),
        ("whatsapp", 21, "Whatsapp"),
        ("facebook", 22, "Facebook"),
    ]
    for key, p_idx, label in sources:
        if p_idx < len(c0.paragraphs):
            is_checked = key in ref_source
            box = "☑" if is_checked else "☐"
            c0.paragraphs[p_idx].text = f"{box} {label}"

    # 4. Table 0 Cell 1: Customer Requirements
    c1 = t0.rows[0].cells[1]

    # Customer Request
    cust_req = data.get("customer_request", "")
    c1.paragraphs[1].text = f"Customer’s request:\n{cust_req}"

    # Requirement Summary
    req_summary = data.get("requirement_summary", "")
    c1.paragraphs[3].text = f"Requirement:\n{req_summary}"

    # Property Types (Nested matrix or text checkboxes)
    prop_types = [t.lower() for t in data.get("property_types", [])]
    is_agri = "agri" in prop_types or any("agri" in pt for pt in prop_types)
    is_comm = "comm" in prop_types or any("comm" in pt for pt in prop_types)
    is_shop = "shop" in prop_types or any("shop" in pt for pt in prop_types)
    is_ind = "ind" in prop_types or any("ind" in pt for pt in prop_types)
    is_factory = "factory" in prop_types or any("factory" in pt for pt in prop_types)
    is_res = "res" in prop_types or any("res" in pt for pt in prop_types)
    is_house = "house" in prop_types or any("house" in pt for pt in prop_types)

    b_agri = "☑" if is_agri else "☐"
    b_comm = "☑" if is_comm else "☐"
    b_shop = "☑" if is_shop else "☐"
    b_ind = "☑" if is_ind else "☐"
    b_factory = "☑" if is_factory else "☐"
    b_res = "☑" if is_res else "☐"
    b_house = "☑" if is_house else "☐"

    c1.paragraphs[7].text = (
        f"Property Link:\n"
        f"{b_agri} Agricultural Land\n"
        f"{b_comm} Commercial Land    {b_shop} Shop\n"
        f"{b_ind} Industrial Land    {b_factory} Factory\n"
        f"{b_res} Residential Land   {b_house} House"
    )

    # Target Location
    loc = data.get("target_location", "Pahang")
    c1.paragraphs[9].text = f"> Location: {loc}"

    # Remarks
    remarks = data.get("remarks", "")
    c1.paragraphs[11].text = f"> Remarks: {remarks}"

    # Assigned To
    assigned = (data.get("assigned_to") or "Direct Seller").lower()
    is_direct = "direct" in assigned
    b_dir = "☑" if is_direct else "☐"
    b_cobroke = "☐" if is_direct else "☑"
    if 15 < len(c1.paragraphs):
        c1.paragraphs[15].text = f"{b_dir} Direct Seller\n{b_cobroke} Co-Broke Partner"

    # Legal Partner Agency (Paragraph 9)
    agency_name = data.get("partner_agency")
    if agency_name and len(doc.paragraphs) > 9:
        p9 = doc.paragraphs[9]
        if "Era Realtor Sdn. Bhd. [E(1)2053/1]" in p9.text:
            p9.text = p9.text.replace("Era Realtor Sdn. Bhd. [E(1)2053/1]", agency_name)

    # 5. Customer & Staff Signatures
    signer_name = data.get("customer_signer", cust_name)
    staff_name = data.get("staff_name", "Leong Chu Ping")

    if len(doc.paragraphs) > 16:
        doc.paragraphs[16].text = f"Name: {signer_name}\t\tName: {staff_name}"
    if len(doc.paragraphs) > 17:
        doc.paragraphs[17].text = f"Date: {header_date}\t\t\t\t\t\tDate: {header_date}"

    # 6. Page 2 Header Date
    if len(doc.paragraphs) > 19:
        doc.paragraphs[19].text = f"Property Proposed/ Viewed \t\t\t\t\t\t            \tDate: {header_date}"

    # 7. Table 1 (Page 2: Properties Proposed / Viewed)
    if len(doc.tables) > 1:
        t1 = doc.tables[1]
        props = data.get("properties_viewed", [])
        if props:
            for idx, prop in enumerate(props):
                row_idx = idx + 1
                if row_idx < len(t1.rows):
                    row = t1.rows[row_idx]
                    row.cells[0].text = f"\n{prop.get('no', f'{idx+1}.')}"
                    row.cells[1].text = f"\n{prop.get('details', '')}"
                    row.cells[2].text = f"\n{prop.get('date', header_date)}"
                    row.cells[3].text = f"\n{prop.get('price', '')}"
                    row.cells[4].text = f"\n{prop.get('description', '')}"

    # 8. Table 2 (Page 2: Submission of Documents)
    if len(doc.tables) > 2:
        t2 = doc.tables[2]
        docs = data.get("documents_submitted", [])
        if docs:
            for idx, doc_item in enumerate(docs):
                row_idx = idx + 1
                if row_idx < len(t2.rows):
                    row = t2.rows[row_idx]
                    if doc_item.get("title_details"):
                        row.cells[1].text = f"\n{doc_item['title_details']}"
                    if doc_item.get("qty"):
                        row.cells[2].text = f"\n{doc_item['qty']}"
                    if doc_item.get("remarks"):
                        row.cells[4].text = f"\n{doc_item['remarks']}"

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

