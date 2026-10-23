"""
Reporting Engine for Home IHC AI CRM.
Generates weekly Excel database reports (Buyer Database.xlsx, Owner Database.xlsx,
and Consolidated Weekly Business Report.xlsx) from PostgreSQL using openpyxl
(if available) or standard-library OpenXML xlsx packager.
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


# ==============================================================================
# 1. SPREADSHEET BUILDER (LOW-LEVEL BINARY OPENXML & OPENPYXL ENCAPSULATION)
# ==============================================================================

class OpenXmlSpreadsheetBuilder:
    """
    Encapsulates OpenXML spreadsheet (.xlsx) generation.
    Supports single-sheet and multi-sheet workbooks with automatic openpyxl acceleration
    when installed, falling back to a pure Python standard-library OpenXML packager.
    """

    @staticmethod
    def col_idx_to_letter(idx: int) -> str:
        """Converts 0-indexed column integer to Excel column letters (0 -> A, 26 -> AA)."""
        result = ""
        idx += 1
        while idx > 0:
            idx, remainder = divmod(idx - 1, 26)
            result = chr(65 + remainder) + result
        return result

    @classmethod
    def build_single_sheet(cls, headers: List[str], rows: List[List[Any]], sheet_name: str = "Database") -> bytes:
        """Convenience builder for single-sheet workbooks."""
        return cls.build({sheet_name: {"headers": headers, "rows": rows}})

    @classmethod
    def build(cls, sheets_data: Dict[str, Dict[str, Any]]) -> bytes:
        """
        Builds a complete OpenXML spreadsheet (.xlsx) binary.
        sheets_data format:
        {
            "SheetName": {
                "headers": ["Col1", "Col2"],
                "rows": [["val1", "val2"]]
            }
        }
        """
        if not sheets_data:
            return cls.build_single_sheet(["Empty"], [], "Sheet1")

        # 1. High-performance path via openpyxl if installed
        openpyxl_bytes = cls._try_openpyxl(sheets_data)
        if openpyxl_bytes is not None:
            return openpyxl_bytes

        # 2. Pure standard library OpenXML generator
        return cls._build_pure_openxml(sheets_data)

    @classmethod
    def _try_openpyxl(cls, sheets_data: Dict[str, Dict[str, Any]]) -> Optional[bytes]:
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            first = True
            for sheet_title, data in sheets_data.items():
                if first:
                    ws = wb.active
                    ws.title = sheet_title
                    first = False
                else:
                    ws = wb.create_sheet(title=sheet_title)
                ws.append(data.get("headers", []))
                for row in data.get("rows", []):
                    ws.append([str(c) if c is not None else "" for c in row])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        except ImportError:
            return None

    @classmethod
    def _build_sheet_xml(cls, headers: List[str], rows: List[List[Any]]) -> str:
        lines = []
        # Header row (Row 1)
        header_cells = []
        for c_idx, h in enumerate(headers):
            ref = f"{cls.col_idx_to_letter(c_idx)}1"
            escaped_val = escape(str(h) if h is not None else "")
            header_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
        lines.append(f'<row r="1">{"".join(header_cells)}</row>')

        # Data rows (Row 2 to N+1)
        for r_idx, row in enumerate(rows, start=2):
            row_cells = []
            for c_idx, val in enumerate(row):
                ref = f"{cls.col_idx_to_letter(c_idx)}{r_idx}"
                escaped_val = escape(str(val) if val is not None else "")
                row_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped_val}</t></is></c>')
            lines.append(f'<row r="{r_idx}">{"".join(row_cells)}</row>')

        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(lines)}
  </sheetData>
</worksheet>"""

    @classmethod
    def _build_pure_openxml(cls, sheets_data: Dict[str, Dict[str, Any]]) -> bytes:
        sheet_keys = list(sheets_data.keys())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # [Content_Types].xml
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

            # _rels/.rels
            zf.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )

            # xl/workbook.xml and xl/_rels/workbook.xml.rels
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

            # xl/worksheets/sheetN.xml
            for idx, sname in enumerate(sheet_keys, start=1):
                sdata = sheets_data[sname]
                s_xml = cls._build_sheet_xml(sdata.get("headers", []), sdata.get("rows", []))
                zf.writestr(f"xl/worksheets/sheet{idx}.xml", s_xml)

        return buf.getvalue()


# ==============================================================================
# 2. REPORT GENERATORS (OBJECT-ORIENTED DOMAIN REPORTERS)
# ==============================================================================

class BaseExcelReportGenerator:
    """
    Abstract Base Class for Excel Report Generators.
    Encapsulates header management, database session scoping, and file export.
    Follows Template Method Pattern.
    """

    def __init__(self, headers: List[str], sheet_name: str, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        self.headers = headers
        self.sheet_name = sheet_name
        self.output_dir = output_dir
        self.db_session = db_session

    def format_rows(self, db_session) -> List[List[Any]]:
        """Subclasses must implement row extraction and formatting."""
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
        return OpenXmlSpreadsheetBuilder.build_single_sheet(self.headers, rows, sheet_name=self.sheet_name)

    def generate(self, output_path: Optional[str] = None, db_session=None) -> str:
        """Executes row formatting and writes a valid .xlsx spreadsheet to disk."""
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

    BUYER_HEADERS = [
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

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        super().__init__(
            headers=self.BUYER_HEADERS,
            sheet_name="Buyer Database",
            output_dir=output_dir,
            db_session=db_session
        )

    def format_rows(self, db_session) -> List[List[Any]]:
        customers = db_session.query(Customer).all()
        rows = []
        for customer in customers:
            row = self._format_buyer_row(customer)
            if row is not None:
                rows.append(row)
        return rows

    @staticmethod
    def _format_buyer_row(c: Customer) -> Optional[List[Any]]:
        meta = c.metadata_json or {}
        intent = meta.get("current_agent") or meta.get("intent") or "buyer"
        if intent not in ["buyer", "tenant", "general"] and not meta.get("buyer_budget"):
            return None

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

        return [
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
        ]


class OwnerReportGenerator(BaseExcelReportGenerator):
    """Generates Owner Database.xlsx reports with property listings, pricing, and title metadata."""

    OWNER_HEADERS = [
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

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        super().__init__(
            headers=self.OWNER_HEADERS,
            sheet_name="Owner Database",
            output_dir=output_dir,
            db_session=db_session
        )

    def format_rows(self, db_session) -> List[List[Any]]:
        properties = db_session.query(Property).all()
        return [self._format_owner_row(p) for p in properties]

    @staticmethod
    def _format_owner_row(p: Property) -> List[Any]:
        cat_str = ", ".join(p.property_category) if isinstance(p.property_category, list) else str(p.property_category or "")
        return [
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
        ]


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

            summary_headers, summary_rows, metrics = self._compile_executive_metrics(buyer_rows, owner_rows, now)

            sheets_data = {
                "Executive Summary": {"headers": summary_headers, "rows": summary_rows},
                "Buyer Database": {"headers": self.buyer_gen.headers, "rows": buyer_rows},
                "Owner Database": {"headers": self.owner_gen.headers, "rows": owner_rows}
            }

            xlsx_bytes = OpenXmlSpreadsheetBuilder.build(sheets_data)

            filename = f"Home_IHC_Weekly_Business_Report_{date_str}.xlsx"
            file_path = os.path.join(self.output_dir, filename)
            canonical_path = os.path.join(self.output_dir, "Home_IHC_Weekly_Business_Report.xlsx")

            with open(file_path, "wb") as f:
                f.write(xlsx_bytes)
            with open(canonical_path, "wb") as f:
                f.write(xlsx_bytes)

            logger.info(f"Generated Consolidated Weekly Report: {file_path} ({metrics['total_buyers']} buyers, {metrics['total_owners']} properties)")

            return {
                "file_path": file_path,
                "canonical_path": canonical_path,
                "filename": filename,
                "total_buyers": metrics["total_buyers"],
                "hot_buyers": metrics["hot_buyers"],
                "warm_buyers": metrics["warm_buyers"],
                "total_owners": metrics["total_owners"],
                "available_properties": metrics["available_properties"],
                "date_display": now.strftime("%d %b %Y"),
                "date_str": date_str
            }
        finally:
            if should_close:
                db.close()

    @staticmethod
    def _compile_executive_metrics(buyer_rows: List[List[Any]], owner_rows: List[List[Any]], timestamp: datetime):
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
            ["Report Generated At", timestamp.strftime("%Y-%m-%d %H:%M MYT"), "Home IHC Automated Business Run"]
        ]
        metrics = {
            "total_buyers": total_buyers,
            "total_owners": total_owners,
            "hot_buyers": hot_buyers,
            "warm_buyers": warm_buyers,
            "available_properties": available_properties
        }
        return summary_headers, summary_rows, metrics


# ==============================================================================
# 3. DISPATCHER & LIFECYCLE MANAGEMENT (CLEAN SINGLE-RESPONSIBILITY METHODS)
# ==============================================================================

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
        stored_config = self._load_stored_config()

        if admin_phones:
            self.admin_phones = admin_phones
        else:
            self.admin_phones = stored_config.get("admin_numbers") or [
                os.getenv("PRIMARY_ADMIN_PHONE", "+601165144931"),
                os.getenv("SECONDARY_ADMIN_PHONE", "+14709202239")
            ]

        is_staging = os.getenv("ENVIRONMENT", "").lower() == "staging"
        self.inbox_id = inbox_id or int(os.getenv("STAGING_INBOX_ID" if is_staging else "WHATSAPP_INBOX_ID", "3" if not is_staging else "4"))
        self.template_name = template_name or stored_config.get("template_name") or os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE", "weekly_business_report_digest")
        self.template_lang = template_lang or stored_config.get("template_language") or os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE_LANGUAGE", "en_US")
        self.download_base = os.getenv("API_PUBLIC_BASE_URL", "https://crm.bentongland.com.my")

    @staticmethod
    def _load_stored_config() -> Dict[str, Any]:
        """Loads weekly reporting configuration from Redis if present."""
        try:
            from app.api.settings import redis_client
            import json
            raw = redis_client.get("weekly_reporting_config")
            if raw:
                return json.loads(raw.decode("utf-8"))
        except Exception:
            pass
        return {}

    def dispatch_consolidated_report(self, consolidated_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatches a single consolidated report digest via pre-approved Meta WhatsApp Template.
        Guarantee: Exactly ONE template message is dispatched per admin phone. Zero Error 131047.
        """
        results = {}
        download_url = f"{self.download_base}/api/v1/settings/reporting-download/consolidated"
        date_str = consolidated_info.get("date_display", datetime.now().strftime("%d %b %Y"))

        template_params = [
            str(date_str),
            str(consolidated_info.get("total_buyers", 0)),
            str(consolidated_info.get("hot_buyers", 0)),
            str(consolidated_info.get("total_owners", 0)),
            download_url
        ]

        # 1. Dispatch single Meta Template message to each admin
        for phone in self.admin_phones:
            clean_phone = phone.strip()
            if not clean_phone:
                continue
            results[clean_phone] = self._dispatch_template_to_admin(clean_phone, template_params)

        # 2. In-Chatwoot Archival: Single internal private note per admin contact
        self._archive_report_in_chatwoot(consolidated_info, date_str, download_url)

        return results

    def _dispatch_template_to_admin(self, clean_phone: str, template_params: List[str]) -> Dict[str, Any]:
        """Dispatches WhatsApp template message to a single recipient."""
        from app.services.chatwoot import send_whatsapp_template
        try:
            res = send_whatsapp_template(
                inbox_id=self.inbox_id,
                to_phone=clean_phone,
                template_name=self.template_name,
                parameters=template_params,
                language_code=self.template_lang
            )
            logger.info(f"Dispatched weekly report Meta template '{self.template_name}' to {clean_phone}")
            return {
                "status": "sent" if res else "dispatched",
                "template": self.template_name,
                "response": res
            }
        except Exception as e:
            logger.error(f"Failed to dispatch weekly report template to {clean_phone}: {e}")
            return {"status": "failed", "error": str(e)}

    def _archive_report_in_chatwoot(self, consolidated_info: Dict[str, Any], date_str: str, download_url: str):
        """Archives the consolidated spreadsheet as an internal private note for each admin."""
        from app.services.chatwoot import (
            get_or_create_contact,
            get_or_create_conversation,
            send_message_with_attachment
        )
        file_path = consolidated_info.get("file_path") or consolidated_info.get("canonical_path")
        if not file_path or not os.path.exists(file_path):
            return

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            filename = consolidated_info.get("filename", os.path.basename(file_path))

            note_content = (
                f"📊 **Weekly Business Report Digest** ({date_str})\n\n"
                f"• 👥 **Active Buyers**: {consolidated_info.get('total_buyers', 0)} ({consolidated_info.get('hot_buyers', 0)} hot)\n"
                f"• 🏡 **Managed Listings**: {consolidated_info.get('total_owners', 0)}\n"
                f"• 🔗 **Download**: {download_url}"
            )

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
                                content=note_content,
                                file_name=filename,
                                file_content=file_bytes,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                is_private=True
                            )
                except Exception as arch_err:
                    logger.warning(f"Failed to archive report attachment in Chatwoot for {clean_phone}: {arch_err}")
        except Exception as file_err:
            logger.warning(f"Chatwoot archival file reading error: {file_err}")

    def dispatch_reports(self, reports: Dict[str, str], consolidated_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Backwards compatible dispatcher routing into consolidated template dispatch."""
        if consolidated_info:
            return self.dispatch_consolidated_report(consolidated_info)

        try:
            gen = ConsolidatedWeeklyReportGenerator()
            info = gen.generate()
            return self.dispatch_consolidated_report(info)
        except Exception as e:
            logger.error(f"Fallback generation error in dispatch_reports: {e}")
            return {}


class WeeklyDatabaseReportManager:
    """Orchestrates generation and dispatch of all scheduled database reports."""

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, inbox_id: int = None):
        self.output_dir = output_dir
        self.inbox_id = inbox_id
        self.buyer_generator = BuyerReportGenerator(output_dir=output_dir)
        self.owner_generator = OwnerReportGenerator(output_dir=output_dir)
        self.consolidated_generator = ConsolidatedWeeklyReportGenerator(output_dir=output_dir)

    def generate_all(self, db_session=None) -> Dict[str, str]:
        """Generates all individual and consolidated reports and returns file path mappings."""
        os.makedirs(self.output_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")

        buyer_path = os.path.join(self.output_dir, f"Buyer_Database_{date_str}.xlsx")
        owner_path = os.path.join(self.output_dir, f"Owner_Database_{date_str}.xlsx")

        self.buyer_generator.generate(output_path=buyer_path, db_session=db_session)
        self.owner_generator.generate(output_path=owner_path, db_session=db_session)

        # Maintain canonical latest copies
        canonical_buyer = os.path.join(self.output_dir, "Buyer Database.xlsx")
        canonical_owner = os.path.join(self.output_dir, "Owner Database.xlsx")
        self._copy_file(buyer_path, canonical_buyer)
        self._copy_file(owner_path, canonical_owner)

        consolidated = self.consolidated_generator.generate(db_session=db_session)

        return {
            "buyer_report": buyer_path,
            "owner_report": owner_path,
            "canonical_buyer": canonical_buyer,
            "canonical_owner": canonical_owner,
            "consolidated_report": consolidated["file_path"],
            "canonical_consolidated": consolidated["canonical_path"]
        }

    def generate_and_dispatch(self, db_session=None, send_to_admins: bool = True) -> Dict[str, Any]:
        """Generates reports and dispatches WhatsApp digest if requested."""
        reports = self.generate_all(db_session=db_session)
        consolidated_info = self.consolidated_generator.generate(db_session=db_session)
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

    @staticmethod
    def _copy_file(src: str, dst: str):
        try:
            with open(src, "rb") as f_src, open(dst, "wb") as f_dst:
                f_dst.write(f_src.read())
        except Exception as e:
            logger.warning(f"Could not copy {src} to {dst}: {e}")


# ==============================================================================
# 4. BACKWARD-COMPATIBLE PROCEDURAL FACADES
# ==============================================================================

_col_idx_to_letter = OpenXmlSpreadsheetBuilder.col_idx_to_letter
create_xlsx_bytes = OpenXmlSpreadsheetBuilder.build_single_sheet
create_multisheet_xlsx_bytes = OpenXmlSpreadsheetBuilder.build


def export_buyer_database_xlsx(output_path: Optional[str] = None, db_session=None) -> str:
    """Procedural facade: queries buyer leads and generates Buyer Database.xlsx."""
    return BuyerReportGenerator().generate(output_path=output_path, db_session=db_session)


def export_owner_database_xlsx(output_path: Optional[str] = None, db_session=None) -> str:
    """Procedural facade: queries owner properties and generates Owner Database.xlsx."""
    return OwnerReportGenerator().generate(output_path=output_path, db_session=db_session)


def generate_weekly_database_reports(output_dir: str = DEFAULT_REPORTS_DIR, db_session=None) -> Dict[str, str]:
    """Procedural facade: generates all weekly database reports."""
    return WeeklyDatabaseReportManager(output_dir=output_dir).generate_all(db_session=db_session)
