"""
Unit and Integration Regression Test Suite for CR-008:
Consolidated Meta Weekly Report Template & Dispatch Engine.
"""

import os
import io
import json
import zipfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.db.models import Customer, Property
from app.services.reporting import (
    create_multisheet_xlsx_bytes,
    ConsolidatedWeeklyReportGenerator,
    AdminWhatsAppDispatcher,
    WeeklyDatabaseReportManager,
    DEFAULT_REPORTS_DIR
)


class TestWeeklyReportingConsolidationAndMetaTemplate(unittest.TestCase):
    """Test suite verifying consolidated multi-sheet Excel generation and Meta template dispatch."""

    def setUp(self):
        self.test_output_dir = "data/output/test_consolidated_reports"
        os.makedirs(self.test_output_dir, exist_ok=True)

    def test_create_multisheet_xlsx_bytes_structure(self):
        """Verifies multi-sheet OpenXML generator creates discrete sheets and valid workbook relationships."""
        sheets_data = {
            "Executive Summary": {
                "headers": ["Metric", "Count"],
                "rows": [["Total Buyers", 10], ["Total Listings", 50]]
            },
            "Buyer Database": {
                "headers": ["Customer ID", "Name", "Phone"],
                "rows": [["1", "Tan Ah Kow", "+60123456789"], ["2", "Siti Nurhaliza", "+60198765432"]]
            },
            "Owner Database": {
                "headers": ["Property ID", "Title", "Price"],
                "rows": [["101", "Durian Orchard Raub", "1,200,000"], ["102", "Bentong Shoplot", "850,000"]]
            }
        }

        xlsx_bytes = create_multisheet_xlsx_bytes(sheets_data)
        self.assertIsInstance(xlsx_bytes, bytes)
        self.assertGreater(len(xlsx_bytes), 100)

        # Inspect internal zip packaging
        zf = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
        namelist = zf.namelist()
        self.assertIn("[Content_Types].xml", namelist)
        self.assertIn("xl/workbook.xml", namelist)
        self.assertIn("xl/_rels/workbook.xml.rels", namelist)
        self.assertIn("xl/worksheets/sheet1.xml", namelist)
        self.assertIn("xl/worksheets/sheet2.xml", namelist)
        self.assertIn("xl/worksheets/sheet3.xml", namelist)

        # Verify workbook.xml references all 3 sheets
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        self.assertIn("Executive Summary", wb_xml)
        self.assertIn("Buyer Database", wb_xml)
        self.assertIn("Owner Database", wb_xml)

    def test_consolidated_weekly_report_generator_compiles_data(self):
        """Verifies ConsolidatedWeeklyReportGenerator extracts live records and writes consolidated .xlsx."""
        c1 = Customer(
            id="60111111111",
            contact_name="Tan Wei",
            email="tan@example.com",
            last_interaction=datetime.now(timezone.utc),
            metadata_json={
                "intent": "buyer",
                "lead_temp": "hot",
                "buyer_budget": "RM 500,000",
                "assigned_agent": "Ah Tat",
                "assigned_agent_phone": "+60129663589"
            }
        )
        c2 = Customer(
            id="60222222222",
            contact_name="Muthu",
            email="muthu@example.com",
            last_interaction=datetime.now(timezone.utc),
            metadata_json={"intent": "buyer", "lead_temp": "warm", "buyer_budget": "RM 300,000"}
        )
        p1 = Property(
            id=1,
            title="5 Acres Musang King Orchard",
            asking_price_myr=1500000.0,
            state="Pahang",
            city="Raub"
        )

        mock_session = MagicMock()
        def mock_query(model):
            q = MagicMock()
            if model.__name__ == "Customer":
                q.all.return_value = [c1, c2]
            else:
                q.all.return_value = [p1]
            return q
        mock_session.query.side_effect = mock_query

        generator = ConsolidatedWeeklyReportGenerator(output_dir=self.test_output_dir)
        result = generator.generate(db_session=mock_session)

        self.assertIn("file_path", result)
        self.assertTrue(os.path.exists(result["file_path"]))
        self.assertTrue(os.path.exists(result["canonical_path"]))
        self.assertEqual(result["total_buyers"], 2)
        self.assertEqual(result["hot_buyers"], 1)
        self.assertEqual(result["total_owners"], 1)
        self.assertIn("agent_distribution", result)
        self.assertIn("Ah Tat", result["agent_distribution"])

    @patch("app.services.chatwoot.send_whatsapp_template")
    @patch("app.services.chatwoot.get_or_create_contact")
    @patch("app.services.chatwoot.get_contact_conversations")
    @patch("app.services.chatwoot.send_message_with_attachment")
    def test_admin_dispatcher_sends_single_meta_template_per_admin(
        self, mock_send_att, mock_get_convs, mock_get_contact, mock_send_template
    ):
        """
        CRITICAL TEST FOR CR-008:
        Asserts that exactly ONE template message is dispatched per admin phone (NOT 4 or 8),
        bypassing 131047 error and preventing multi-conversation spam.
        """
        mock_send_template.return_value = {"messages": [{"id": "wamid.report123"}]}
        mock_get_contact.return_value = 99
        mock_get_convs.return_value = [{"id": 555, "inbox_id": 3, "status": "open"}]
        mock_send_att.return_value = {"id": 101}

        test_file = os.path.join(self.test_output_dir, "test_file.xlsx")
        with open(test_file, "wb") as f:
            f.write(b"dummy xlsx")

        summary_data = {
            "file_path": test_file,
            "canonical_path": test_file,
            "filename": "Home_IHC_Weekly_Business_Report.xlsx",
            "total_buyers": 45,
            "hot_buyers": 8,
            "total_owners": 120,
            "date_display": "12 Oct 2026"
        }

        admin_phones = ["+601165144931", "+14709202239"]
        dispatcher = AdminWhatsAppDispatcher(admin_phones=admin_phones, inbox_id=3)
        results = dispatcher.dispatch_consolidated_report(summary_data)

        # 1. Assert exactly 2 template calls (one for each admin)
        self.assertEqual(mock_send_template.call_count, 2)
        sent_numbers = [c[1]["to_phone"] for c in mock_send_template.call_args_list]
        self.assertEqual(sent_numbers, admin_phones)

        # 2. Assert template name and 5 dynamic parameters mapping
        first_call_kwargs = mock_send_template.call_args_list[0][1]
        self.assertEqual(first_call_kwargs["template_name"], "weekly_business_report_digest")
        params = first_call_kwargs["parameters"]
        self.assertEqual(len(params), 5)
        self.assertEqual(params[0], "12 Oct 2026") # Date
        self.assertEqual(params[1], "45")          # Total Buyers
        self.assertEqual(params[2], "8")           # Hot Buyers
        self.assertEqual(params[3], "120")         # Total Listings/Owners
        self.assertIn("reporting-download/consolidated", params[4]) # Download link

        # 3. Assert Chatwoot archival uses exactly ONE message in ONE conversation anchored to primary admin
        self.assertEqual(mock_send_att.call_count, 1)
        mock_get_contact.assert_called_once_with("+601165144931", "Staff/Admin (+601165144931)")
        att_call_kwargs = mock_send_att.call_args[1]
        self.assertTrue(att_call_kwargs.get("is_private"))
        self.assertEqual(att_call_kwargs.get("conversation_id"), 555)
        self.assertIn("Weekly Business Report & Executive Summary", att_call_kwargs.get("content"))
        self.assertIn("Tab 1: Executive KPI Summary", att_call_kwargs.get("content"))

    @patch("app.services.reporting.ConsolidatedWeeklyReportGenerator.generate")
    @patch("app.services.reporting.AdminWhatsAppDispatcher.dispatch_consolidated_report")
    def test_weekly_manager_orchestrates_consolidated_pipeline(self, mock_dispatch, mock_gen):
        """Verifies WeeklyDatabaseReportManager generates consolidated reports and dispatches correctly."""
        mock_gen.return_value = {
            "file_path": "/tmp/consolidated.xlsx",
            "canonical_path": "/tmp/Home_IHC_Weekly_Business_Report.xlsx",
            "filename": "Home_IHC_Weekly_Business_Report.xlsx",
            "total_buyers": 10,
            "hot_buyers": 2,
            "total_owners": 15,
            "date_display": "12 Oct 2026"
        }
        mock_dispatch.return_value = {"+601165144931": {"status": "sent"}}

        mock_db = MagicMock()
        mock_db.query.return_value.count.return_value = 10

        manager = WeeklyDatabaseReportManager(output_dir=self.test_output_dir)
        outcome = manager.generate_and_dispatch(db_session=mock_db, send_to_admins=True)

        self.assertIn("consolidated_file", outcome)
        self.assertEqual(outcome["consolidated_file"], "/tmp/consolidated.xlsx")
        self.assertTrue(mock_dispatch.called)

    @patch("app.api.webhooks.CHATWOOT_WEBHOOK_SECRET", "")
    @patch("app.services.reporting.WeeklyDatabaseReportManager.generate_and_dispatch")
    @patch("app.services.chatwoot.send_message_with_attachment")
    @patch("app.services.chatwoot.send_private_note")
    def test_report_slash_command_dispatches_single_atomic_message(
        self, mock_send_note, mock_send_att, mock_mgr
    ):
        """Verifies that in-chatwoot /report command dispatches 1 single atomic message and zero text clutter notes."""
        import asyncio
        from unittest.mock import AsyncMock
        from app.api.webhooks import chatwoot_webhook

        test_file = os.path.join(self.test_output_dir, "test_file.xlsx")
        with open(test_file, "wb") as f:
            f.write(b"dummy xlsx")

        mock_mgr.return_value = {
            "consolidated_file": test_file,
            "buyers_count": 30,
            "owners_count": 50,
            "hot_buyers_count": 5,
        }

        mock_request = AsyncMock()
        payload_bytes = json.dumps({
            "event": "message_created",
            "private": True,
            "content": "/report",
            "conversation": {"id": 888}
        }).encode("utf-8")
        mock_request.body.return_value = payload_bytes
        mock_request.headers = {}
        mock_bg = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(chatwoot_webhook(mock_request))
        finally:
            loop.close()

        self.assertEqual(res.get("status"), "command_executed")
        self.assertEqual(res.get("command"), "/report")
        self.assertEqual(mock_send_att.call_count, 1)
        self.assertEqual(mock_send_note.call_count, 0)
        att_args = mock_send_att.call_args[1]
        self.assertEqual(att_args.get("conversation_id"), 888)
        self.assertTrue(att_args.get("is_private"))
        self.assertIn("Weekly Business Report & Executive Summary", att_args.get("content"))

    def test_report_download_token_hmac_security(self):
        """Verifies HMAC token generation and tamper verification for report downloads."""
        from app.core.security import generate_report_download_token, verify_report_download_token

        token = generate_report_download_token("consolidated", "20261102")
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 32)

        # 1. Valid token passes
        self.assertTrue(verify_report_download_token("consolidated", "20261102", token))

        # 2. Tampered token fails
        self.assertFalse(verify_report_download_token("consolidated", "20261102", token[:-1] + "a"))

        # 3. Wrong date fails
        self.assertFalse(verify_report_download_token("consolidated", "20261103", token))

        # 4. Wrong report type fails
        self.assertFalse(verify_report_download_token("buyer", "20261102", token))

        # 5. Missing token or date fails
        self.assertFalse(verify_report_download_token("consolidated", "", token))
        self.assertFalse(verify_report_download_token("consolidated", "20261102", ""))

    def test_dispatcher_generates_signed_tokenized_download_url(self):
        """Verifies AdminWhatsAppDispatcher generates a secure URL pointing to database.bentongland.com.my with date and token."""
        summary_data = {
            "date_display": "02 Nov 2026",
            "date_str": "20261102",
            "total_buyers": 81,
            "hot_buyers": 1,
            "total_owners": 413,
            "filename": "Home_IHC_Weekly_Business_Report_20261102.xlsx"
        }

        with patch("app.services.chatwoot.send_whatsapp_template") as mock_send:
            mock_send.return_value = {"messages": [{"id": "wamid.123"}]}
            dispatcher = AdminWhatsAppDispatcher(admin_phones=["+601165144931"], inbox_id=3)
            dispatcher.dispatch_consolidated_report(summary_data)

            self.assertEqual(mock_send.call_count, 1)
            params = mock_send.call_args[1]["parameters"]
            download_url = params[4]
            self.assertIn("https://database.bentongland.com.my", download_url)
            self.assertIn("date=20261102", download_url)
            self.assertIn("token=", download_url)
            self.assertNotIn("crm.bentongland.com.my", download_url)

    def test_download_endpoint_dual_authorization(self):
        """Verifies download_weekly_report endpoint allows valid HMAC tokens and rejects unauthenticated/forged requests."""
        try:
            from fastapi import HTTPException
            if not isinstance(HTTPException, type) or not issubclass(HTTPException, BaseException):
                raise TypeError()
        except Exception:
            class HTTPException(Exception):
                def __init__(self, status_code=400, detail="", headers=None):
                    self.status_code = status_code
                    self.detail = detail
                    self.headers = headers

        from app.api.settings import download_weekly_report
        from app.core.security import generate_report_download_token

        # Create dummy file in test directory
        test_file = os.path.join(self.test_output_dir, "Home_IHC_Weekly_Business_Report_20261102.xlsx")
        with open(test_file, "wb") as f:
            f.write(b"PK\x03\x04test_data")

        valid_token = generate_report_download_token("consolidated", "20261102")

        with patch("app.services.reporting.DEFAULT_REPORTS_DIR", self.test_output_dir):
            # 1. Unauthenticated request without token or bearer raises 401
            with self.assertRaises(HTTPException) as ctx_401:
                download_weekly_report("consolidated", date="20261102", token=None, credentials=None, db=MagicMock())
            self.assertEqual(ctx_401.exception.status_code, 401)

            # 2. Forged token raises 403
            with self.assertRaises(HTTPException) as ctx_403:
                download_weekly_report("consolidated", date="20261102", token="invalid_forged_token", credentials=None, db=MagicMock())
            self.assertEqual(ctx_403.exception.status_code, 403)

            # 3. Valid token allows download and returns FileResponse
            resp = download_weekly_report("consolidated", date="20261102", token=valid_token, credentials=None, db=MagicMock())
            self.assertIsNotNone(resp)
            self.assertEqual(os.path.basename(resp.path), "Home_IHC_Weekly_Business_Report_20261102.xlsx")


if __name__ == "__main__":
    unittest.main()
