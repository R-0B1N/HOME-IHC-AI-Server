"""
Reporting Engine for Home IHC AI CRM.
Generates weekly Excel database reports (Buyer Database.xlsx and Owner Database.xlsx)
from PostgreSQL using openpyxl (if available) or standard-library OpenXML xlsx packager.
"""

import os
import io
import zipfile
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from xml.sax.saxutils import escape

from app.db.models import SessionLocal, Customer, Property

logger = logging.getLogger(__name__)

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_CANDIDATE_REPORTS = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "..", "data", "output", "reports"))
DEFAULT_REPORTS_DIR = os.getenv("REPORTS_OUTPUT_DIR") or _CANDIDATE_REPORTS


def _col_idx_to_letter(idx: int) -> str:
    """Converts 0-indexed column integer to Excel column letters (0 -> A, 26 -> AA)."""
    result = ""
    idx += 1
    while idx > 0:
        idx, remainder = divmod(idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def create_xlsx_bytes(headers: List[str], rows: List[List[Any]], sheet_name: str = "Database") -> bytes:
    """
    Creates a clean OpenXML spreadsheet (.xlsx) in pure standard Python.
    Compatible with Microsoft Excel, Apple Numbers, Google Sheets, and LibreOffice Calc.
    """
    # Try openpyxl first if available
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        ws.append(headers)
        for row in rows:
            ws.append([str(c) if c is not None else "" for c in row])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        pass

    # Pure standard library OpenXML generator
    sheet_data_lines = []
    
    # 1. Header Row (Row 1)
    header_cells = []
    for c_idx, h in enumerate(headers):
        ref = f"{_col_idx_to_letter(c_idx)}1"
        escaped_val = escape(str(h) if h is not None else "")
        header_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
    sheet_data_lines.append(f'<row r="1">{"".join(header_cells)}</row>')

    # 2. Data Rows (Row 2 to N+1)
    for r_idx, row in enumerate(rows, start=2):
        row_cells = []
        for c_idx, val in enumerate(row):
            ref = f"{_col_idx_to_letter(c_idx)}{r_idx}"
            escaped_val = escape(str(val) if val is not None else "")
            row_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
        sheet_data_lines.append(f'<row r="{r_idx}">{"".join(row_cells)}</row>')

    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_data_lines)}
  </sheetData>
</worksheet>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    return buf.getvalue()


def export_buyer_database_xlsx(output_path: Optional[str] = None, db_session=None) -> str:
    """
    Queries all buyer leads from Customer table and generates Buyer Database.xlsx.
    """
    if output_path is None:
        os.makedirs(DEFAULT_REPORTS_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = os.path.join(DEFAULT_REPORTS_DIR, f"Buyer_Database_{date_str}.xlsx")

    headers = [
        "Customer ID",
        "Contact Name",
        "Phone Number",
        "Email",
        "Lead Intent",
        "Lead Temperature",
        "Target Location",
        "Property Types",
        "Budget Range (MYR)",
        "Assigned Agent",
        "Bypass AI",
        "Created Date",
        "Last Interaction Date"
    ]

    db = db_session or SessionLocal()
    should_close = db_session is None
    rows = []
    try:
        customers = db.query(Customer).all()
        for c in customers:
            meta = c.metadata_json or {}
            intent = meta.get("current_agent") or meta.get("intent") or "buyer"
            if intent not in ["buyer", "tenant", "general"] and not meta.get("buyer_budget"):
                continue

            loc = meta.get("location") or meta.get("buyer_location") or meta.get("current_location") or ""
            ptypes = meta.get("property_type") or meta.get("buyer_property_type") or ""
            budget = meta.get("budget") or meta.get("buyer_budget") or ""
            temp = meta.get("lead_temp") or meta.get("temperature") or "Warm"
            bypass = "Yes" if meta.get("bypass_ai") else "No"
            agent = meta.get("assigned_agent", "Irene Leong")

            created_str = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
            updated_str = c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else ""

            rows.append([
                str(c.id),
                c.contact_name or "Unknown",
                c.phone_number or "",
                c.email or "",
                intent.title(),
                str(temp).title(),
                str(loc),
                str(ptypes),
                str(budget),
                agent,
                bypass,
                created_str,
                updated_str
            ])
    finally:
        if should_close:
            db.close()

    xlsx_bytes = create_xlsx_bytes(headers, rows, sheet_name="Buyer Database")
    with open(output_path, "wb") as f:
        f.write(xlsx_bytes)

    logger.info(f"Generated Buyer Database report: {output_path} ({len(rows)} records)")
    return output_path


def export_owner_database_xlsx(output_path: Optional[str] = None, db_session=None) -> str:
    """
    Queries all owner property listings from Property table and generates Owner Database.xlsx.
    """
    if output_path is None:
        os.makedirs(DEFAULT_REPORTS_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = os.path.join(DEFAULT_REPORTS_DIR, f"Owner_Database_{date_str}.xlsx")

    headers = [
        "Property ID",
        "Listing Title",
        "Status",
        "Category",
        "Sub-Type",
        "Asking Price (MYR)",
        "Price Per Acre (MYR)",
        "Price Per Sqft (MYR)",
        "Land Area (Acres)",
        "Land Area (Sqft)",
        "State",
        "City / District",
        "Tenure",
        "Title Status",
        "Agent Name",
        "Agent Phone",
        "Source URL"
    ]

    db = db_session or SessionLocal()
    should_close = db_session is None
    rows = []
    try:
        properties = db.query(Property).all()
        for p in properties:
            cat_str = ", ".join(p.property_category) if isinstance(p.property_category, list) else str(p.property_category or "")
            rows.append([
                str(p.id),
                p.title or "Untitled",
                p.listing_status or "Available",
                cat_str,
                p.property_type_sub or "",
                f"{p.asking_price_myr:,.2f}" if p.asking_price_myr else "0.00",
                f"{p.price_per_acre_myr:,.2f}" if p.price_per_acre_myr else "",
                f"{p.price_per_sqft_myr:,.2f}" if p.price_per_sqft_myr else "",
                f"{p.land_area_acres:.2f}" if p.land_area_acres else "",
                f"{p.land_area_sqft:.0f}" if p.land_area_sqft else "",
                p.state or "Pahang",
                p.city or p.area or "",
                p.tenure_type or "",
                p.title_status or "",
                p.agent_name or "Irene Leong",
                p.agent_phone or "+6011-65144931",
                p.source_url or ""
            ])
    finally:
        if should_close:
            db.close()

    xlsx_bytes = create_xlsx_bytes(headers, rows, sheet_name="Owner Database")
    with open(output_path, "wb") as f:
        f.write(xlsx_bytes)

    logger.info(f"Generated Owner Database report: {output_path} ({len(rows)} records)")
    return output_path


def generate_weekly_database_reports(output_dir: str = DEFAULT_REPORTS_DIR, db_session=None) -> Dict[str, str]:
    """
    Generates both Buyer Database.xlsx and Owner Database.xlsx in target directory.
    Returns mapping of report paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    
    buyer_path = os.path.join(output_dir, f"Buyer_Database_{date_str}.xlsx")
    owner_path = os.path.join(output_dir, f"Owner_Database_{date_str}.xlsx")

    export_buyer_database_xlsx(buyer_path, db_session=db_session)
    export_owner_database_xlsx(owner_path, db_session=db_session)

    # Maintain canonical latest copies
    canonical_buyer = os.path.join(output_dir, "Buyer Database.xlsx")
    canonical_owner = os.path.join(output_dir, "Owner Database.xlsx")
    with open(buyer_path, "rb") as src, open(canonical_buyer, "wb") as dst:
        dst.write(src.read())
    with open(owner_path, "rb") as src, open(canonical_owner, "wb") as dst:
        dst.write(src.read())

    return {
        "buyer_report": buyer_path,
        "owner_report": owner_path,
        "canonical_buyer": canonical_buyer,
        "canonical_owner": canonical_owner
    }


class BaseExcelReportGenerator:
    """
    Abstract Base Class for Excel Report Generators.
    Encapsulates header management, row building, and OpenXML binary export.
    """

    def __init__(self, headers: List[str], sheet_name: str, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        self.headers = headers
        self.sheet_name = sheet_name
        self.output_dir = output_dir
        self.db_session = db_session

    def format_rows(self, db_session) -> List[List[Any]]:
        """Subclasses must implement row extraction and transformation."""
        raise NotImplementedError

    def generate_bytes(self, db_session=None) -> bytes:
        """Executes row formatting and returns raw .xlsx binary bytes."""
        db = db_session or self.db_session or SessionLocal()
        should_close = (db_session is None and self.db_session is None)
        try:
            rows = self.format_rows(db)
        finally:
            if should_close:
                db.close()
        return create_xlsx_bytes(self.headers, rows, sheet_name=self.sheet_name)

    def generate(self, output_path: Optional[str] = None, db_session=None) -> str:
        """Executes row formatting and outputs valid .xlsx spreadsheet."""
        if output_path is None:
            os.makedirs(self.output_dir, exist_ok=True)
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{self.sheet_name.replace(' ', '_')}_{date_str}.xlsx"
            output_path = os.path.join(self.output_dir, filename)

        xlsx_bytes = self.generate_bytes(db_session=db_session)
        with open(output_path, "wb") as f:
            f.write(xlsx_bytes)

        logger.info(f"Generated {self.sheet_name} report: {output_path}")
        return output_path


class BuyerReportGenerator(BaseExcelReportGenerator):
    """Generates Buyer Database.xlsx reports with lead qualification and temperature attributes."""

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        headers = [
            "Customer ID",
            "Contact Name",
            "Phone Number",
            "Email",
            "Lead Intent",
            "Lead Temperature",
            "Target Location",
            "Property Types",
            "Budget Range (MYR)",
            "Assigned Agent",
            "Bypass AI",
            "Created Date",
            "Last Interaction Date"
        ]
        super().__init__(headers=headers, sheet_name="Buyer Database", output_dir=output_dir, db_session=db_session)

    def format_rows(self, db_session) -> List[List[Any]]:
        rows = []
        customers = db_session.query(Customer).all()
        for c in customers:
            meta = c.metadata_json or {}
            intent = meta.get("current_agent") or meta.get("intent") or "buyer"
            if intent not in ["buyer", "tenant", "general"] and not meta.get("buyer_budget"):
                continue

            loc = meta.get("location") or meta.get("buyer_location") or meta.get("current_location") or ""
            ptypes = meta.get("property_type") or meta.get("buyer_property_type") or ""
            budget = meta.get("budget") or meta.get("buyer_budget") or ""
            temp = meta.get("lead_temp") or meta.get("temperature") or "Warm"
            bypass = "Yes" if meta.get("bypass_ai") else "No"
            agent = meta.get("assigned_agent", "Irene Leong")

            created_str = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
            updated_str = c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else ""

            rows.append([
                str(c.id),
                c.contact_name or "Unknown",
                c.phone_number or "",
                c.email or "",
                intent.title(),
                str(temp).title(),
                str(loc),
                str(ptypes),
                str(budget),
                agent,
                bypass,
                created_str,
                updated_str
            ])
        return rows


class OwnerReportGenerator(BaseExcelReportGenerator):
    """Generates Owner Database.xlsx reports with property listings, pricing, and title metadata."""

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        headers = [
            "Property ID",
            "Listing Title",
            "Status",
            "Category",
            "Sub-Type",
            "Asking Price (MYR)",
            "Price Per Acre (MYR)",
            "Price Per Sqft (MYR)",
            "Land Area (Acres)",
            "Land Area (Sqft)",
            "State",
            "City / District",
            "Tenure",
            "Title Status",
            "Agent Name",
            "Agent Phone",
            "Source URL"
        ]
        super().__init__(headers=headers, sheet_name="Owner Database", output_dir=output_dir, db_session=db_session)

    def format_rows(self, db_session) -> List[List[Any]]:
        rows = []
        properties = db_session.query(Property).all()
        for p in properties:
            cat_str = ", ".join(p.property_category) if isinstance(p.property_category, list) else str(p.property_category or "")
            rows.append([
                str(p.id),
                p.title or "Untitled",
                p.listing_status or "Available",
                cat_str,
                p.property_type_sub or "",
                f"{p.asking_price_myr:,.2f}" if p.asking_price_myr else "0.00",
                f"{p.price_per_acre_myr:,.2f}" if p.price_per_acre_myr else "",
                f"{p.price_per_sqft_myr:,.2f}" if p.price_per_sqft_myr else "",
                f"{p.land_area_acres:.2f}" if p.land_area_acres else "",
                f"{p.land_area_sqft:.0f}" if p.land_area_sqft else "",
                p.state or "Pahang",
                p.city or p.area or "",
                p.tenure_type or "",
                p.title_status or "",
                p.agent_name or "Irene Leong",
                p.agent_phone or "+6011-65144931",
                p.source_url or ""
            ])
        return rows


class WeeklyDatabaseReportManager:
    """Orchestrates generation of all scheduled database reports."""

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR):
        self.output_dir = output_dir
        self.buyer_generator = BuyerReportGenerator(output_dir=output_dir)
        self.owner_generator = OwnerReportGenerator(output_dir=output_dir)

    def generate_all(self, db_session=None) -> Dict[str, str]:
        return generate_weekly_database_reports(output_dir=self.output_dir, db_session=db_session)

