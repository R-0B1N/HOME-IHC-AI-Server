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
            metadata_json={"intent": "buyer", "lead_temp": "hot", "buyer_budget": "RM 500,000"}
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

        # 3. Assert Chatwoot attachment is strictly an internal private note
        self.assertEqual(mock_send_att.call_count, 2)
        for att_call in mock_send_att.call_args_list:
            self.assertTrue(att_call[1].get("is_private"))

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


if __name__ == "__main__":
    unittest.main()
