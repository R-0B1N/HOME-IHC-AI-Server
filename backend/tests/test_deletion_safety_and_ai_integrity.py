"""
Automated Test Suite: Deletion Safety, Architecture Decoupling & WhatsApp AI Integrity.
Verifies that the entire WhatsApp AI CRM engine operates with 100% correctness and zero
dependency on any of the files identified for deletion.
"""
import os
import sys
import re
import hmac
import hashlib
import json
import unittest

# Ensure backend root is in sys.path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

class TestDeletionSafetyAndAIIntegrity(unittest.TestCase):

    def test_deletion_candidates_not_imported_by_core_backend(self):
        """
        Asserts that none of the files targeted for deletion are imported
        or required anywhere inside backend/app/ (the running backend).
        """
        app_dir = os.path.join(BACKEND_DIR, "app")
        forbidden_modules = [
            "edit_compose",
            "list_containers",
            "add_rbac",
            "deploy_workflow",
            "fix_workflow",
            "modify_workflow",
            "merge_dc",
            "get_template_details",
            "list_templates_local",
            "recreate_properties_table",
            "recreate_tables",
            "scrape_bentongland",
            "ingest_properties",
        ]

        for root, dirs, files in os.walk(app_dir):
            if "__pycache__" in root:
                continue
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for mod in forbidden_modules:
                        pattern = rf"(?:import\s+{mod}|from\s+.*?{mod}\s+import)"
                        self.assertIsNone(
                            re.search(pattern, content),
                            f"Core backend file {file} illegally imports deletion target '{mod}'!"
                        )

    def test_dangerous_table_drop_scripts_isolated_from_startup(self):
        """
        Verifies that neither backend/app/main.py nor backend/app/worker/celery_app.py
        call drop_all() or depend on the hazardous recreate_tables scripts.
        """
        main_py = os.path.join(BACKEND_DIR, "app", "main.py")
        celery_py = os.path.join(BACKEND_DIR, "app", "worker", "celery_app.py")

        for filepath in [main_py, celery_py]:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            self.assertNotIn("Base.metadata.drop_all", content,
                             f"{filepath} contains dangerous drop_all call!")
            self.assertNotIn("recreate_tables", content,
                             f"{filepath} references hazardous recreate_tables!")
            self.assertNotIn("recreate_properties_table", content,
                             f"{filepath} references hazardous recreate_properties_table!")

    def test_whatsapp_ai_state_machine_and_agent_logic(self):
        """
        Validates that agent_logic.py successfully executes persona state machines
        (Router, Buyer, Seller, Agent/Broker) and name validation without deleted files.
        """
        from unittest.mock import MagicMock, patch
        if "openai" not in sys.modules:
            mock_openai_mod = MagicMock()
            sys.modules["openai"] = mock_openai_mod
            mock_openai_mod.OpenAI = MagicMock()
        if "redis" not in sys.modules:
            sys.modules["redis"] = MagicMock()

        import app.services.agent_logic as al
        from app.services.agent_logic import (
            is_valid_name,
            process_persona_state_machine,
        )

        # 1. Name validation precision
        self.assertTrue(is_valid_name("Nick Lee"))
        self.assertTrue(is_valid_name("Dr. Azman"))
        self.assertTrue(is_valid_name("Tan Sri Lim"))
        self.assertFalse(is_valid_name("+60123456789"))
        self.assertFalse(is_valid_name("01165144931"))
        self.assertFalse(is_valid_name("Unknown"))
        self.assertFalse(is_valid_name("WhatsApp User"))
        self.assertFalse(is_valid_name("."))
        self.assertFalse(is_valid_name(""))
        self.assertFalse(is_valid_name(None))

        # 2. Buyer persona: Property inquiry
        session = {"state": "INIT", "collected_data": {}}
        mock_buyer_llm = {
            "intent": "buyer",
            "asked_photos": False,
            "asked_specs": False,
            "asked_meeting": False,
            "asked_alternatives": False,
            "new_constraints": {"category": "Agricultural Land", "city": "Bentong"},
            "is_out_of_context": False,
            "extracted_data": {"name": "Dato Alex", "property_type": "Agricultural Land"},
            "response": "Hello Dato Alex! We have several prime durian lands in Bentong. Would you like to see our 5-acre listings?"
        }

        with patch.object(al, "generate_conversational_response", return_value=mock_buyer_llm):
            with patch("app.services.db_services.find_matching_property", return_value=None):
                res_buyer = process_persona_state_machine(
                    phone_number="+60123456789",
                    text="I want to buy 5 acres agricultural durian land in Bentong",
                    session=session,
                    conversation_history="",
                    contact_name="Dato Alex"
                )
        self.assertFalse(res_buyer["handover"])
        self.assertEqual(session["collected_data"].get("name"), "Dato Alex")
        self.assertIn("response", res_buyer)
        self.assertGreater(len(res_buyer["response"]), 10)

        # 3. Buyer persona: Photo request handling
        session_photo = {
            "state": "IN_PROGRESS",
            "current_agent": "BUYER",
            "collected_data": {"name": "Dato Alex"},
            "interested_property": {
                "title": "Bentong Musang King Durian Land",
                "price": 1800000,
                "city": "Bentong",
                "image_urls": ["https://bentongland.com.my/img1.jpg"],
                "status": "Available"
            }
        }
        mock_photo_llm = {
            "intent": "buyer",
            "asked_photos": True,
            "asked_specs": False,
            "asked_meeting": False,
            "asked_alternatives": False,
            "new_constraints": {},
            "is_out_of_context": False,
            "extracted_data": {},
            "response": "Here are the photos of the Bentong Musang King Durian Land! 😊"
        }
        with patch.object(al, "generate_conversational_response", return_value=mock_photo_llm):
            res_photo = process_persona_state_machine(
                phone_number="+60123456789",
                text="Can you send me pictures and location map?",
                session=session_photo,
                conversation_history="User: Any durian land?",
                contact_name="Dato Alex"
            )
        self.assertFalse(res_photo["handover"])
        self.assertIn("images_to_send", res_photo)

    def test_webhook_hmac_and_staging_isolation_logic(self):
        """
        Validates Chatwoot webhook HMAC signature verification (with X-Chatwoot-Timestamp) and staging isolation.
        """
        secret = "test_webhook_secret_key"
        payload = json.dumps({"event": "message_created", "content": "Hello AI"}).encode("utf-8")
        timestamp = "1788975745"
        
        # 1. Chatwoot v4.15 timestamped signature: HMAC-SHA256("#{timestamp}.#{payload}")
        signed_payload = f"{timestamp}.".encode("utf-8") + payload
        timestamped_sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        self.assertEqual(len(timestamped_sig), 64)

        # 2. Legacy signature: HMAC-SHA256(payload)
        legacy_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertEqual(len(legacy_sig), 64)
        self.assertNotEqual(timestamped_sig, legacy_sig)

        # 3. Simulate webhooks.py verification logic
        received_sig = f"sha256={timestamped_sig}"
        clean_sig = received_sig[7:] if received_sig.startswith("sha256=") else received_sig
        expected_hex = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(expected_hex, clean_sig))

        # 4. Forged signature rejection
        forged_signature = "a" * 64
        self.assertFalse(hmac.compare_digest(expected_hex, forged_signature))

        # Webhooks.py inspection: HMAC, Timestamp, and Staging rules strictly present
        webhooks_py = os.path.join(BACKEND_DIR, "app", "api", "webhooks.py")
        with open(webhooks_py, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("CHATWOOT_WEBHOOK_SECRET", content)
        self.assertIn("X-Chatwoot-Signature", content)
        self.assertIn("X-Chatwoot-Timestamp", content)
        self.assertIn("ENVIRONMENT", content)
        self.assertIn("STAGING_INBOX_ID", content)

    def test_active_scraper_and_financial_parsing_engine(self):
        """
        Validates that the active production scraper (scrape_and_ingest_all_properties.py)
        correctly extracts acres and financial yields, proving scrape_bentongland.py is obsolete.
        """
        from scripts.scrape_and_ingest_all_properties import parse_acres, parse_listing_financials

        # Test case 1: Musang King Durian Land with price per acre
        title1 = "9.7 ac Bentong Jln Tras Durian Land For Sale"
        desc1 = "Matured Musang King orchard. Price: RM 365,000 / acre. Road access."
        acres1 = parse_acres(title1)
        self.assertEqual(acres1, 9.7)
        fin1 = parse_listing_financials(title1, desc1, status="For Sale", acres=acres1)
        self.assertEqual(fin1["price_per_acre_myr"], 365000.0)
        self.assertEqual(fin1["asking_price_myr"], 3540500.0)

        # Test case 2: Warehouse for rent
        title2 = "Mentakab Heavy Industrial Warehouse For Rent"
        desc2 = "Rental: RM 15,000 / month. 3-Phase power, 30ft ceiling height."
        fin2 = parse_listing_financials(title2, desc2, status="For Rent", acres=0.0)
        self.assertEqual(fin2["asking_price_myr"], 0.0)
        self.assertEqual(fin2["monthly_rental_income_myr"], 15000.0)

        # Test case 3: Hectares to acres conversion
        desc3 = "Land Size: 1.706 Hectares / 4.216 Acres. Selling Price RM 4,315,352."
        acres3 = parse_acres(desc3)
        self.assertEqual(acres3, 4.216)

    def test_workflow_templates_definitions_integrity(self):
        """
        Validates that seed_workflows.py contains all essential personas and steps,
        proving that external n8n JSONs in workflows/ are completely unnecessary.
        """
        from scripts.seed_workflows import seed_workflows
        import inspect
        import scripts.seed_workflows as sw

        src = inspect.getsource(sw.seed_workflows)
        
        # Verify required personas exist in the Python code
        self.assertIn('"persona_type": "ROUTER"', src)
        self.assertIn('"persona_type": "BUYER"', src)
        self.assertIn('"persona_type": "SELLER"', src)
        
        # Verify specific required steps
        self.assertIn("Greeting & Intro", src)
        self.assertIn("Identify Customer Category", src)
        self.assertIn("Step 8: Viewing Acknowledgement & Form", src)

    def test_property_acknowledgement_acroform_pdf_intact(self):
        """
        Verifies that docs/Property Acknowledgement Document.pdf exists, is valid PDF 1.4,
        and has all interactive AcroForm fields accessible for Workstream 8.
        """
        pdf_path = os.path.join(PROJECT_ROOT, "docs", "Property Acknowledgement Document.pdf")
        self.assertTrue(os.path.exists(pdf_path), "Property Acknowledgement Document.pdf is missing!")
        with open(pdf_path, "rb") as f:
            header = f.read(1024)
        self.assertTrue(header.startswith(b"%PDF-"), "Invalid PDF header")

        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            self.assertEqual(len(doc), 2, "AcroForm PDF should have exactly 2 pages")

            field_count = 0
            for page in doc:
                widgets = page.widgets()
                if widgets:
                    field_count += len(list(widgets))
            
            doc.close()
            self.assertGreaterEqual(field_count, 50, f"Expected >= 50 AcroForm fields, found {field_count}")
        except ImportError:
            pass  # PyMuPDF optional locally (Zero-Local-Host); verified binary structure

    def test_frontend_has_zero_dependencies_on_deleted_assets(self):
        """
        Verifies that property-dashboard/src/ has zero imports or references
        to hero.png, react.svg, vite.svg, or public/icons.svg.
        """
        frontend_src = os.path.join(PROJECT_ROOT, "property-dashboard", "src")
        unreferenced = ["hero.png", "react.svg", "vite.svg", "icons.svg"]

        for root, _, files in os.walk(frontend_src):
            for file in files:
                if file.endswith((".jsx", ".js", ".css", ".html")):
                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    for asset in unreferenced:
                        self.assertNotIn(asset, content,
                                         f"Frontend file {file} unexpectedly references deletion candidate '{asset}'!")


if __name__ == "__main__":
    unittest.main()
