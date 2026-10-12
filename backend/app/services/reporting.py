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


def create_multisheet_xlsx_bytes(sheets_data: Dict[str, Dict[str, Any]]) -> bytes:
    """
    Creates a clean multi-sheet OpenXML spreadsheet (.xlsx) in pure standard Python.
    sheets_data: {
        "SheetName": {
            "headers": [...],
            "rows": [[...], ...]
        }
    }
    """
    # 1. Try openpyxl first if available
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        first_sheet = True
        for sheet_title, data in sheets_data.items():
            if first_sheet:
                ws = wb.active
                ws.title = sheet_title
                first_sheet = False
            else:
                ws = wb.create_sheet(title=sheet_title)
            ws.append(data.get("headers", []))
            for row in data.get("rows", []):
                ws.append([str(c) if c is not None else "" for c in row])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        pass

    # 2. Pure standard library OpenXML generator supporting multiple sheets
    def _generate_sheet_xml(headers: List[str], rows: List[List[Any]]) -> str:
        sheet_lines = []
        header_cells = []
        for c_idx, h in enumerate(headers):
            ref = f"{_col_idx_to_letter(c_idx)}1"
            escaped_val = escape(str(h) if h is not None else "")
            header_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
        sheet_lines.append(f'<row r="1">{"".join(header_cells)}</row>')

        for r_idx, row in enumerate(rows, start=2):
            row_cells = []
            for c_idx, val in enumerate(row):
                ref = f"{_col_idx_to_letter(c_idx)}{r_idx}"
                escaped_val = escape(str(val) if val is not None else "")
                row_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
            sheet_lines.append(f'<row r="{r_idx}">{"".join(row_cells)}</row>')

        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_lines)}
  </sheetData>
</worksheet>"""

    sheet_keys = list(sheets_data.keys())
    if not sheet_keys:
        return create_xlsx_bytes(["Empty"], [], "Sheet1")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        override_lines = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        ]
        for idx in range(1, len(sheet_keys) + 1):
            override_lines.append(
                f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        content_types_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {"".join(override_lines)}
</Types>"""
        zf.writestr("[Content_Types].xml", content_types_xml)

        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )

        sheet_entries = []
        wb_rels_entries = []
        for idx, sname in enumerate(sheet_keys, start=1):
            sheet_entries.append(f'<sheet name="{escape(sname)}" sheetId="{idx}" r:id="rId{idx}"/>')
            wb_rels_entries.append(
                f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
            )

        workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    {"".join(sheet_entries)}
  </sheets>
</workbook>"""
        zf.writestr("xl/workbook.xml", workbook_xml)

        workbook_rels_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {"".join(wb_rels_entries)}
</Relationships>"""
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)

        for idx, sname in enumerate(sheet_keys, start=1):
            sdata = sheets_data[sname]
            s_xml = _generate_sheet_xml(sdata.get("headers", []), sdata.get("rows", []))
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", s_xml)

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

            created_at_dt = getattr(c, "created_at", None) or getattr(c, "last_interaction", None)
            created_str = created_at_dt.strftime("%Y-%m-%d %H:%M") if created_at_dt else ""
            last_int_dt = getattr(c, "last_interaction", None) or getattr(c, "updated_at", None)
            updated_str = last_int_dt.strftime("%Y-%m-%d %H:%M") if last_int_dt else ""
            phone = getattr(c, "phone_number", None) or getattr(c, "id", "")

            rows.append([
                str(c.id),
                c.contact_name or "Unknown",
                phone,
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
    Generates Buyer Database.xlsx, Owner Database.xlsx, and Consolidated Weekly Business Report.
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

    # Consolidated multi-tab workbook
    consolidated_path = os.path.join(output_dir, f"Home_IHC_Weekly_Business_Report_{date_str}.xlsx")
    canonical_consolidated = os.path.join(output_dir, "Home_IHC_Weekly_Business_Report.xlsx")
    try:
        con_gen = ConsolidatedWeeklyReportGenerator(output_dir=output_dir)
        con_gen.generate(db_session=db_session)
    except Exception as e:
        logger.warning(f"Could not generate consolidated workbook in generate_weekly_database_reports: {e}")

    return {
        "buyer_report": buyer_path,
        "owner_report": owner_path,
        "canonical_buyer": canonical_buyer,
        "canonical_owner": canonical_owner,
        "consolidated_report": consolidated_path,
        "canonical_consolidated": canonical_consolidated
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

            created_at_dt = getattr(c, "created_at", None) or getattr(c, "last_interaction", None)
            created_str = created_at_dt.strftime("%Y-%m-%d %H:%M") if created_at_dt else ""
            last_int_dt = getattr(c, "last_interaction", None) or getattr(c, "updated_at", None)
            updated_str = last_int_dt.strftime("%Y-%m-%d %H:%M") if last_int_dt else ""
            phone = getattr(c, "phone_number", None) or getattr(c, "id", "")

            rows.append([
                str(c.id),
                c.contact_name or "Unknown",
                phone,
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


class ConsolidatedWeeklyReportGenerator:
    """
    Compiles Buyer, Seller/Owner, and Executive KPI metrics into a single multi-tab
    canonical OpenXML .xlsx spreadsheet: Home_IHC_Weekly_Business_Report.xlsx
    """

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR):
        self.output_dir = output_dir
        self.buyer_gen = BuyerReportGenerator(output_dir=output_dir)
        self.owner_gen = OwnerReportGenerator(output_dir=output_dir)

    def generate(self, db_session=None) -> Dict[str, Any]:
        os.makedirs(self.output_dir, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        
        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            buyer_rows = self.buyer_gen.format_rows(db)
            owner_rows = self.owner_gen.format_rows(db)

            total_buyers = len(buyer_rows)
            total_owners = len(owner_rows)
            hot_buyers = sum(1 for r in buyer_rows if len(r) > 5 and str(r[5]).lower() == "hot")
            warm_buyers = sum(1 for r in buyer_rows if len(r) > 5 and str(r[5]).lower() == "warm")
            available_properties = sum(1 for r in owner_rows if len(r) > 2 and "avail" in str(r[2]).lower())

            summary_headers = ["Metric", "Count / Value", "Description"]
            summary_rows = [
                ["Total Registered Buyers", total_buyers, "Qualified prospects registered in CRM"],
                ["🔥 Hot Buyer Leads", hot_buyers, "High-temperature prospects requiring active follow-up"],
                ["⚡ Warm Buyer Leads", warm_buyers, "Engaged buyer prospects exploring listings"],
                ["Total Listings / Owners", total_owners, "Managed properties across Bentong, Raub & Temerloh"],
                ["Available Listings", available_properties, "Listings ready for immediate buyer matching"],
                ["Report Generated At", now.strftime("%Y-%m-%d %H:%M MYT"), "Home IHC Automated Business Run"]
            ]

            sheets_data = {
                "Executive Summary": {"headers": summary_headers, "rows": summary_rows},
                "Buyer Database": {"headers": self.buyer_gen.headers, "rows": buyer_rows},
                "Owner Database": {"headers": self.owner_gen.headers, "rows": owner_rows}
            }

            xlsx_bytes = create_multisheet_xlsx_bytes(sheets_data)
            
            filename = f"Home_IHC_Weekly_Business_Report_{date_str}.xlsx"
            file_path = os.path.join(self.output_dir, filename)
            canonical_path = os.path.join(self.output_dir, "Home_IHC_Weekly_Business_Report.xlsx")

            with open(file_path, "wb") as f:
                f.write(xlsx_bytes)
            with open(canonical_path, "wb") as f:
                f.write(xlsx_bytes)

            logger.info(f"Generated Consolidated Weekly Report: {file_path} ({total_buyers} buyers, {total_owners} properties)")

            return {
                "file_path": file_path,
                "canonical_path": canonical_path,
                "filename": filename,
                "total_buyers": total_buyers,
                "hot_buyers": hot_buyers,
                "warm_buyers": warm_buyers,
                "total_owners": total_owners,
                "available_properties": available_properties,
                "date_display": now.strftime("%d %b %Y"),
                "date_str": date_str
            }
        finally:
            if should_close:
                db.close()


class AdminWhatsAppDispatcher:
    """
    Dispatches weekly database reports directly to administrator WhatsApp numbers
    utilizing pre-approved Meta WhatsApp utility templates, eliminating 24h window
    re-engagement blocks (Error 131047) and Chatwoot conversation duplication.
    """

    def __init__(
        self,
        admin_phones: List[str] = None,
        inbox_id: int = None,
        template_name: str = None,
        template_lang: str = None
    ):
        stored_phones = []
        stored_template_name = None
        stored_template_lang = None
        try:
            from app.api.settings import redis_client
            import json
            raw = redis_client.get("weekly_reporting_config")
            if raw:
                stored = json.loads(raw.decode("utf-8"))
                stored_phones = stored.get("admin_numbers", [])
                stored_template_name = stored.get("template_name")
                stored_template_lang = stored.get("template_language")
        except Exception:
            pass

        if admin_phones:
            self.admin_phones = admin_phones
        else:
            self.admin_phones = stored_phones or [
                os.getenv("PRIMARY_ADMIN_PHONE", "+601165144931"),
                os.getenv("SECONDARY_ADMIN_PHONE", "+14709202239")
            ]

        is_staging = os.getenv("ENVIRONMENT", "").lower() == "staging"
        self.inbox_id = inbox_id or int(os.getenv("STAGING_INBOX_ID" if is_staging else "WHATSAPP_INBOX_ID", "3" if not is_staging else "4"))
        self.template_name = template_name or stored_template_name or os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE", "weekly_business_report_digest")
        self.template_lang = template_lang or stored_template_lang or os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE_LANGUAGE", "en_US")
        self.download_base = os.getenv("API_PUBLIC_BASE_URL", "https://crm.bentongland.com.my")

    def dispatch_consolidated_report(self, consolidated_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatches a single consolidated report digest via pre-approved Meta WhatsApp Template.
        Guarantee: Exactly ONE template message is dispatched per admin phone. Zero Error 131047.
        """
        from app.services.chatwoot import (
            send_whatsapp_template,
            get_or_create_contact,
            get_or_create_conversation,
            send_message_with_attachment
        )

        results = {}
        download_url = f"{self.download_base}/api/v1/settings/reporting-download/consolidated"
        date_str = consolidated_info.get("date_display", datetime.now().strftime("%d %b %Y"))
        total_buyers = consolidated_info.get("total_buyers", 0)
        hot_buyers = consolidated_info.get("hot_buyers", 0)
        total_owners = consolidated_info.get("total_owners", 0)

        template_params = [
            str(date_str),
            str(total_buyers),
            str(hot_buyers),
            str(total_owners),
            download_url
        ]

        # 1. Dispatch single Meta Template message to each admin (Allowed outside 24h window)
        for phone in self.admin_phones:
            clean_phone = phone.strip()
            if not clean_phone:
                continue
            try:
                res = send_whatsapp_template(
                    inbox_id=self.inbox_id,
                    to_phone=clean_phone,
                    template_name=self.template_name,
                    parameters=template_params,
                    language_code=self.template_lang
                )
                results[clean_phone] = {
                    "status": "sent" if res else "dispatched",
                    "template": self.template_name,
                    "response": res
                }
                logger.info(f"Dispatched weekly report Meta template '{self.template_name}' to {clean_phone}")
            except Exception as e:
                logger.error(f"Failed to dispatch weekly report template to {clean_phone}: {e}")
                results[clean_phone] = {"status": "failed", "error": str(e)}

        # 2. In-Chatwoot Archival: Single internal private note per admin contact (Zero freeform outbound)
        try:
            file_path = consolidated_info.get("file_path") or consolidated_info.get("canonical_path")
            if file_path and os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                filename = consolidated_info.get("filename", os.path.basename(file_path))
                for phone in self.admin_phones:
                    clean_phone = phone.strip()
                    if not clean_phone:
                        continue
                    try:
                        contact_id = get_or_create_contact(clean_phone, f"Staff/Admin ({clean_phone})")
                        if contact_id:
                            conv_id = get_or_create_conversation(contact_id, self.inbox_id)
                            if isinstance(conv_id, dict):
                                conv_id = conv_id.get("id")
                            if conv_id:
                                send_message_with_attachment(
                                    conversation_id=conv_id,
                                    content=(
                                        f"📊 **Weekly Business Report Digest** ({date_str})\n\n"
                                        f"• 👥 **Active Buyers**: {total_buyers} ({hot_buyers} hot)\n"
                                        f"• 🏡 **Managed Listings**: {total_owners}\n"
                                        f"• 🔗 **Download**: {download_url}"
                                    ),
                                    file_name=filename,
                                    file_content=file_bytes,
                                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    is_private=True  # Strictly private internal note
                                )
                    except Exception as arch_err:
                        logger.warning(f"Failed to archive report attachment in Chatwoot for {clean_phone}: {arch_err}")
        except Exception as file_err:
            logger.warning(f"Chatwoot archival file reading error: {file_err}")

        return results

    def dispatch_reports(self, reports: Dict[str, str], consolidated_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Backwards compatible dispatcher routing into consolidated template dispatch."""
        if consolidated_info:
            return self.dispatch_consolidated_report(consolidated_info)

        # If consolidated_info not passed, generate it
        try:
            gen = ConsolidatedWeeklyReportGenerator()
            info = gen.generate()
            return self.dispatch_consolidated_report(info)
        except Exception as e:
            logger.error(f"Fallback generation error in dispatch_reports: {e}")
            return {}


class WeeklyDatabaseReportManager:
    """Orchestrates generation of all scheduled database reports."""

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, inbox_id: int = None):
        self.output_dir = output_dir
        self.inbox_id = inbox_id
        self.buyer_generator = BuyerReportGenerator(output_dir=output_dir)
        self.owner_generator = OwnerReportGenerator(output_dir=output_dir)
        self.consolidated_generator = ConsolidatedWeeklyReportGenerator(output_dir=output_dir)

    def generate_all(self, db_session=None) -> Dict[str, str]:
        reports = generate_weekly_database_reports(output_dir=self.output_dir, db_session=db_session)
        consolidated = self.consolidated_generator.generate(db_session=db_session)
        reports["consolidated_report"] = consolidated["file_path"]
        reports["canonical_consolidated"] = consolidated["canonical_path"]
        return reports

    def generate_and_dispatch(self, db_session=None, send_to_admins: bool = True) -> Dict[str, Any]:
        consolidated_info = self.consolidated_generator.generate(db_session=db_session)
        reports = generate_weekly_database_reports(output_dir=self.output_dir, db_session=db_session)
        reports["consolidated_report"] = consolidated_info["file_path"]
        reports["canonical_consolidated"] = consolidated_info["canonical_path"]

        dispatch_results = {}
        if send_to_admins:
            dispatcher = AdminWhatsAppDispatcher(inbox_id=self.inbox_id)
            dispatch_results = dispatcher.dispatch_consolidated_report(consolidated_info)

        return {
            "reports": reports,
            "dispatch_results": dispatch_results,
            "buyers_count": consolidated_info.get("total_buyers", 0),
            "owners_count": consolidated_info.get("total_owners", 0),
            "hot_buyers_count": consolidated_info.get("hot_buyers", 0),
            "consolidated_file": consolidated_info.get("file_path"),
            "buyer_file": reports.get("buyer_report"),
            "owner_file": reports.get("owner_report")
        }

