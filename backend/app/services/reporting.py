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
from app.services.classification_config import use_legacy_weekly_template, weekly_template_name
from app.services.customer_classification import canonical_category_name, stored_category, stored_temperature

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
        "Last Interaction Date",
        "Previous Role",
        "Previous Role At",
        "Previous Role Source",
    ]

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR, db_session=None):
        super().__init__(
            headers=self.BUYER_HEADERS,
            sheet_name="Buyer Database",
            output_dir=output_dir,
            db_session=db_session
        )

    def format_rows(self, db_session) -> List[List[Any]]:
        grouped = self.rows_by_category(db_session)
        return grouped.get("buyer", [])

    @staticmethod
    def _format_buyer_row(c: Customer) -> List[Any]:
        """Row formatter kept for callers that inspect one customer record."""
        _category, row = BuyerReportGenerator.format_customer_record(c)
        return row

    @classmethod
    def rows_by_category(cls, db_session) -> Dict[str, List[List[Any]]]:
        grouped = {name: [] for name in ("buyer", "seller", "agent", "tenant", "landlord", "uncertain")}
        for customer in db_session.query(Customer).all():
            category, row = cls.format_customer_record(customer)
            grouped.setdefault(category, []).append(row)
        return grouped

    @staticmethod
    def format_customer_record(c: Customer):
        meta = c.metadata_json or {}
        raw_intent = stored_category(meta)
        category = canonical_category_name(raw_intent) if raw_intent else "uncertain"
        intent = category

        loc = meta.get("location") or meta.get("buyer_location") or meta.get("current_location") or ""
        ptypes = meta.get("property_type") or meta.get("buyer_property_type") or ""
        budget = (
            meta.get("budget")
            or meta.get("buyer_budget")
            or meta.get("asking_price")
            or meta.get("asking_rent")
            or meta.get("expected_rental")
            or ""
        )
        stored_temp = stored_temperature(meta)
        temp = stored_temp if stored_temp else "Unset"
        bypass = "Yes" if meta.get("bypass_ai") else "No"
        
        agent = meta.get("assigned_agent") or meta.get("assigned_agent_name")
        agent_phone = meta.get("assigned_agent_phone")
        if not agent:
            # Fallback heuristic for historical hot leads without explicit assigned_agent key
            # If bentong tenant/rental inquiry was routed to Ah Tat
            if "bentong" in str(loc).lower() and ("tenant" in str(intent).lower() or "rental" in str(ptypes).lower()):
                agent = "Ah Tat"
                agent_phone = "+60129663589"
            else:
                agent = "Irene Leong"

        if agent_phone and agent_phone not in agent:
            agent_display = f"{agent} ({agent_phone})"
        else:
            agent_display = agent

        created_at_dt = getattr(c, "created_at", None) or getattr(c, "last_interaction", None)
        created_str = created_at_dt.strftime("%Y-%m-%d %H:%M") if created_at_dt else ""
        last_int_dt = getattr(c, "last_interaction", None) or getattr(c, "updated_at", None)
        updated_str = last_int_dt.strftime("%Y-%m-%d %H:%M") if last_int_dt else ""
        phone = getattr(c, "phone_number", None) or getattr(c, "id", "")

        row = [
            str(c.id),
            c.contact_name or "Unknown",
            phone,
            c.email or "",
            intent.title(),
            str(temp).title(),
            str(loc),
            str(ptypes),
            str(budget),
            agent_display,
            bypass,
            created_str,
            updated_str,
            str(meta.get("previous_role") or ""),
            str(meta.get("previous_role_at") or ""),
            str(meta.get("previous_role_source") or ""),
        ]
        return category, row


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
            f"{p.asking_price_myr:,.2f}" if isinstance(p.asking_price_myr, (int, float)) else "0.00",
            f"{p.price_per_acre_myr:,.2f}" if isinstance(p.price_per_acre_myr, (int, float)) else "",
            f"{p.price_per_sqft_myr:,.2f}" if isinstance(p.price_per_sqft_myr, (int, float)) else "",
            f"{p.land_area_acres:.2f}" if isinstance(p.land_area_acres, (int, float)) else "",
            f"{p.land_area_sqft:.0f}" if isinstance(p.land_area_sqft, (int, float)) else "",
            p.state or "Pahang",
            p.city or p.area or "",
            p.tenure_type or "",
            p.title_status or "",
            p.agent_name or "Irene Leong",
            p.agent_phone or "+6011-65144931",
            p.source_url or ""
        ]


CUSTOMER_SHEET_ORDER = ("buyer", "seller", "agent", "tenant", "landlord", "uncertain")
SHEET_TITLES = {
    "buyer": "Buyer",
    "seller": "Seller",
    "agent": "Agent",
    "tenant": "Tenant",
    "landlord": "Landlord",
    "uncertain": "Uncertain",
}


def _temperature_counts(rows: List[List[Any]]) -> Dict[str, int]:
    counts = {"hot": 0, "warm": 0, "cold": 0}
    for row in rows:
        if len(row) > 5:
            label = str(row[5]).strip().lower()
            if label in counts:
                counts[label] += 1
    return counts


class ConsolidatedWeeklyReportGenerator:
    """
    Weekly workbook tabs: Executive Summary, Buyer, Seller, Agent, Tenant,
    Landlord, Uncertain. Website listings are not included.
    """

    def __init__(self, output_dir: str = DEFAULT_REPORTS_DIR):
        self.output_dir = output_dir
        self.buyer_gen = BuyerReportGenerator(output_dir=output_dir)

    def generate(self, db_session=None) -> Dict[str, Any]:
        os.makedirs(self.output_dir, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            grouped = self.buyer_gen.rows_by_category(db)
            summary_headers, summary_rows, metrics = self._compile_executive_metrics(grouped, now)
            sheets_data = {
                "Executive Summary": {"headers": summary_headers, "rows": summary_rows},
            }
            for key in CUSTOMER_SHEET_ORDER:
                sheets_data[SHEET_TITLES[key]] = {
                    "headers": self.buyer_gen.headers,
                    "rows": grouped.get(key, []),
                }

            xlsx_bytes = OpenXmlSpreadsheetBuilder.build(sheets_data)
            filename = f"Home_IHC_Weekly_Business_Report_{date_str}.xlsx"
            file_path = os.path.join(self.output_dir, filename)
            canonical_path = os.path.join(self.output_dir, "Home_IHC_Weekly_Business_Report.xlsx")
            with open(file_path, "wb") as handle:
                handle.write(xlsx_bytes)
            with open(canonical_path, "wb") as handle:
                handle.write(xlsx_bytes)

            logger.info(
                "Generated Consolidated Weekly Report: %s (%s customers)",
                file_path,
                metrics["total_customers"],
            )
            result = {
                "file_path": file_path,
                "canonical_path": canonical_path,
                "filename": filename,
                "date_display": now.strftime("%d %b %Y"),
                "date_str": date_str,
            }
            result.update(metrics)
            return result
        finally:
            if should_close:
                db.close()

    @staticmethod
    def _compile_executive_metrics(grouped: Dict[str, List[List[Any]]], timestamp: datetime):
        summary_headers = ["Metric", "Count / Value", "Description"]
        summary_rows = []
        metrics = {}
        total_customers = 0
        total_hot = 0
        for key in CUSTOMER_SHEET_ORDER:
            rows = grouped.get(key, [])
            temps = _temperature_counts(rows)
            total_customers += len(rows)
            total_hot += temps["hot"]
            title = SHEET_TITLES[key]
            metrics[f"total_{key}s" if key != "uncertain" else "uncertain_count"] = len(rows)
            if key == "buyer":
                metrics["total_buyers"] = len(rows)
                metrics["hot_buyers"] = temps["hot"]
                metrics["warm_buyers"] = temps["warm"]
            metrics[f"hot_{key}"] = temps["hot"]
            metrics[f"warm_{key}"] = temps["warm"]
            metrics[f"cold_{key}"] = temps["cold"]
            summary_rows.append([f"{title} customers", len(rows), f"Customers classified as {title.lower()}"])
            summary_rows.append([f"{title} hot", temps["hot"], f"Hot {title.lower()} customers"])
            summary_rows.append([f"{title} warm", temps["warm"], f"Warm {title.lower()} customers"])
            summary_rows.append([f"{title} cold", temps["cold"], f"Cold {title.lower()} customers"])
        summary_rows.append(["Total customers", total_customers, "All classified customer rows, including uncertain"])
        summary_rows.append(["Total hot", total_hot, "Hot customers across every category"])
        summary_rows.append(["Report Generated At", timestamp.strftime("%Y-%m-%d %H:%M MYT"), "Home IHC weekly customer report"])
        metrics["total_customers"] = total_customers
        metrics["total_hot"] = total_hot
        metrics["agent_distribution"] = "See Agent tab"
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

        self.primary_admin_phone = (
            self.admin_phones[0] if self.admin_phones else os.getenv("PRIMARY_ADMIN_PHONE", "+601165144931")
        ).strip()

        is_staging = os.getenv("ENVIRONMENT", "").lower() == "staging"
        self.inbox_id = inbox_id or int(os.getenv("STAGING_INBOX_ID" if is_staging else "WHATSAPP_INBOX_ID", "3" if not is_staging else "4"))
        if use_legacy_weekly_template():
            self.template_name = (
                template_name
                or stored_config.get("template_name")
                or os.getenv("WHATSAPP_WEEKLY_REPORT_LEGACY_TEMPLATE", "weekly_business_report_digest")
            )
        else:
            self.template_name = template_name or weekly_template_name()
        self.template_lang = template_lang or stored_config.get("template_language") or os.getenv("WHATSAPP_WEEKLY_REPORT_TEMPLATE_LANGUAGE", "en_US")
        self.download_base = os.getenv("API_PUBLIC_BASE_URL", "https://database.bentongland.com.my")

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
        date_code = consolidated_info.get("date_str") or datetime.now().strftime("%Y%m%d")
        try:
            from app.core.security import generate_report_download_token
            token = generate_report_download_token("consolidated", date_code)
            download_url = f"{self.download_base}/api/v1/settings/reporting-download/consolidated?date={date_code}&token={token}"
        except Exception as tok_err:
            logger.warning(f"Failed to generate secure download token: {tok_err}")
            download_url = f"{self.download_base}/api/v1/settings/reporting-download/consolidated"

        date_str = consolidated_info.get("date_display", datetime.now().strftime("%d %b %Y"))
        button_suffix = ""
        if "token=" in download_url:
            button_suffix = download_url.split("/reporting-download/", 1)[-1]

        if use_legacy_weekly_template():
            template_params = [
                str(date_str),
                str(consolidated_info.get("total_customers", consolidated_info.get("total_buyers", 0))),
                str(consolidated_info.get("total_hot", consolidated_info.get("hot_buyers", 0))),
                str(consolidated_info.get("total_customers", 0)),
                download_url,
            ]
            button_suffix = ""
        else:
            template_params = [
                str(date_str),
                str(consolidated_info.get("total_customers", 0)),
                str(consolidated_info.get("total_buyers", 0)),
                str(consolidated_info.get("total_sellers", 0)),
                str(consolidated_info.get("total_agents", 0)),
                str(consolidated_info.get("total_tenants", 0)),
                str(consolidated_info.get("total_landlords", 0)),
                str(consolidated_info.get("uncertain_count", 0)),
                str(consolidated_info.get("total_hot", 0)),
            ]
        self._button_suffix = button_suffix

        # 1. Dispatch single Meta Template message to each admin
        for phone in self.admin_phones:
            clean_phone = phone.strip()
            if not clean_phone:
                continue
            results[clean_phone] = self._dispatch_template_to_admin(
                clean_phone,
                template_params,
                button_url_suffix=getattr(self, "_button_suffix", ""),
            )

        # 2. In-Chatwoot Archival: Single internal private note per admin contact
        self._archive_report_in_chatwoot(consolidated_info, date_str, download_url)

        return results

    def _dispatch_template_to_admin(
        self,
        clean_phone: str,
        template_params: List[str],
        button_url_suffix: str = "",
    ) -> Dict[str, Any]:
        """Dispatches WhatsApp template message to a single recipient."""
        from app.services.chatwoot import send_whatsapp_template
        try:
            res = send_whatsapp_template(
                inbox_id=self.inbox_id,
                to_phone=clean_phone,
                template_name=self.template_name,
                parameters=template_params,
                language_code=self.template_lang,
                button_url_suffix=button_url_suffix or None,
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
        """
        Archives the consolidated spreadsheet as a single internal private note in Chatwoot.
        Guarantee: Uses exactly ONE message and ONE conversation thread anchored to the primary admin.
        """
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
                f"📊 **Weekly Business Report & Executive Summary** ({date_str})\n\n"
                f"• Customers: {consolidated_info.get('total_customers', 0)} ({consolidated_info.get('total_hot', 0)} hot)\n"
                f"• Buyer {consolidated_info.get('total_buyers', 0)}, "
                f"Seller {consolidated_info.get('total_sellers', 0)}, "
                f"Agent {consolidated_info.get('total_agents', 0)}, "
                f"Tenant {consolidated_info.get('total_tenants', 0)}, "
                f"Landlord {consolidated_info.get('total_landlords', 0)}, "
                f"Uncertain {consolidated_info.get('uncertain_count', 0)}\n"
                f"• Download: {download_url}\n\n"
                f"• Tab 1: Executive KPI Summary\n"
                f"• Tab 2: Buyer\n"
                f"• Tab 3: Seller\n"
                f"• Tab 4: Agent\n"
                f"• Tab 5: Tenant\n"
                f"• Tab 6: Landlord\n"
                f"• Tab 7: Uncertain\n\n"
                f"Previous role and timestamp are columns on each customer tab."
            )

            # Single conversation guarantee: Anchor strictly to primary admin
            target_phone = self.primary_admin_phone
            if target_phone:
                try:
                    contact_id = get_or_create_contact(target_phone, f"Staff/Admin ({target_phone})")
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
                    logger.warning(f"Failed to archive report attachment in Chatwoot for {target_phone}: {arch_err}")
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
        self.consolidated_generator = ConsolidatedWeeklyReportGenerator(output_dir=output_dir)

    def generate_all(self, db_session=None) -> Dict[str, str]:
        """Generates the category workbook. Website listings are not part of this report."""
        os.makedirs(self.output_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        buyer_path = os.path.join(self.output_dir, f"Buyer_Database_{date_str}.xlsx")
        self.buyer_generator.generate(output_path=buyer_path, db_session=db_session)
        canonical_buyer = os.path.join(self.output_dir, "Buyer Database.xlsx")
        self._copy_file(buyer_path, canonical_buyer)
        consolidated = self.consolidated_generator.generate(db_session=db_session)
        return {
            "buyer_report": buyer_path,
            "canonical_buyer": canonical_buyer,
            "consolidated_report": consolidated["file_path"],
            "canonical_consolidated": consolidated["canonical_path"],
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
            "customers_count": consolidated_info.get("total_customers", 0),
            "hot_count": consolidated_info.get("total_hot", 0),
            "sellers_count": consolidated_info.get("total_sellers", 0),
            "agents_count": consolidated_info.get("total_agents", 0),
            "tenants_count": consolidated_info.get("total_tenants", 0),
            "landlords_count": consolidated_info.get("total_landlords", 0),
            "uncertain_count": consolidated_info.get("uncertain_count", 0),
            "hot_buyers_count": consolidated_info.get("hot_buyers", 0),
            "agent_distribution": consolidated_info.get("agent_distribution", "N/A"),
            "consolidated_file": consolidated_info.get("file_path"),
            "buyer_file": reports.get("buyer_report"),
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
