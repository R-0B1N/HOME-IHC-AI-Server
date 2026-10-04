"""
Automated Test Suite for Multimodal Document Extraction, Conversation 71 Remediation,
ActiveStorage Proxy Streaming, and Dual-Track State Machine.
"""

import os
import io
import time
import json
import base64
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import fitz  # PyMuPDF

from app.services.document_parser import (
    sniff_is_pdf,
    sniff_is_docx,
    extract_text_from_document,
    MAX_RASTER_SHEETS,
    TARGET_IMAGE_MAX_DIM,
)
from app.services.document_extractor import (
    extract_real_estate_document_data,
    heuristic_document_extraction,
    RealEstateDocumentExtract,
)
from app.services.llm import classify_turn_intent
from app.services.agent_logic import process_persona_state_machine
from app.services.system_prompts import (
    get_multilingual_disambiguation_request,
    get_multilingual_ah_tuck_handover,
    AH_TUCK_PHONE,
    AH_TUCK_EMAIL,
)
from app.main import app


class TestDocumentIngestionAndContext(unittest.TestCase):
    """Verifies polymorphic document extraction, Conversation 71 guard, and dual-track state."""

    def test_payload_detection(self):
        """Detects PDF via content_type, extension, or URL when data_file_name is omitted."""
        # Chatwoot attachment payload omitting data_file_name
        dummy_content = b"%PDF-1.4\n%mock pdf\n%%EOF"
        
        # 1. Magic bytes & content_type check
        self.assertTrue(sniff_is_pdf(dummy_content, file_name="", content_type="application/pdf"))
        self.assertTrue(sniff_is_pdf(dummy_content, file_name="", extension="pdf"))
        self.assertTrue(sniff_is_pdf(dummy_content, file_name="", data_url="https://inbox.example.com/blob/doc.pdf?exp=123"))
        
        # 2. Extract call with mocked requests
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf", "Content-Length": str(len(dummy_content))}
        mock_resp.iter_content.return_value = [dummy_content]
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            res = extract_text_from_document(
                data_url="https://inbox.example.com/rails/active_storage/disk/sample",
                file_name="",
                content_type="application/pdf",
                extension="pdf"
            )
            self.assertIn("text", res)
            self.assertIn("images", res)
            self.assertIn("structured_data", res)

    def test_cad_blueprint_budget(self):
        """Verifies downscaling budget (max 3 sheets, JPEG, <250MB RAM) for raster CAD blueprints."""
        # Create an in-memory 5-page PDF with raster/vector drawings
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page(width=1600, height=1200)
            page.draw_rect(fitz.Rect(50, 50, 1500, 1100), color=(0, 0, 1), fill=(0.9, 0.9, 0.9))
            page.insert_text(fitz.Point(100, 100), f"Sheet {i+1}: CAD Drawing")
        pdf_bytes = doc.tobytes()
        doc.close()

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": str(len(pdf_bytes))}
        mock_resp.iter_content.return_value = [pdf_bytes]
        mock_resp.raise_for_status = MagicMock()

        start_time = time.time()
        with patch("requests.get", return_value=mock_resp):
            res = extract_text_from_document(
                data_url="https://inbox.example.com/PELAN%20BANGUNAN.pdf",
                file_name="PELAN BANGUNAN.pdf"
            )
        duration = time.time() - start_time

        # Asserts
        self.assertLess(duration, 5.0, "CAD Blueprint extraction exceeded 5s budget")
        self.assertLessEqual(len(res["images"]), MAX_RASTER_SHEETS, "Exceeded maximum raster sheet budget")
        for b64_img in res["images"]:
            raw_img = base64.b64decode(b64_img)
            self.assertLess(len(raw_img), 500 * 1024, "Downscaled sheet exceeded 500KB JPEG budget")

    def test_high_fidelity_extraction(self):
        """Extracts exact legal and architectural particulars matching the verified ground truth."""
        extract = extract_real_estate_document_data(
            text="CADANGAN MEMBINA 1 BLOK RESTORAN & DEWAN 3 TINGKAT DI ATAS LOT 13169 & LOT 13170 MUKIM TRIANG DAERAH BERA PAHANG UNTUK TETUAN HAO XIANG CHI SEAFOOD SDN BHD",
            images=[],
            file_name="PELAN BANGUNAN.pdf"
        )
        self.assertEqual(extract.get("document_type"), "Pelan Bangunan")
        self.assertEqual(extract.get("state"), "Pahang")
        self.assertEqual(extract.get("district"), "Bera")
        self.assertEqual(extract.get("mukim"), "Triang")
        self.assertIn("Lot 13169", extract.get("lot_numbers", []))
        self.assertIn("Lot 13170", extract.get("lot_numbers", []))
        self.assertEqual(extract.get("land_area_acres"), 2.252)
        self.assertEqual(extract.get("land_area_sqft"), 98091.0)
        self.assertEqual(extract.get("tenure"), "Freehold")
        self.assertEqual(extract.get("dining_tables_capacity"), 180)
        self.assertEqual(extract.get("occupant_load_capacity"), 1360)
        self.assertEqual(extract.get("registered_owner"), "Hao Xiang Chi Seafood Sdn Bhd")
        self.assertEqual(extract.get("architect_name"), "T S Yap Architect")

    def test_zero_keyword_classification(self):
        """Classifies turns dynamically without brittle keyword regexes."""
        # 1. Chinese Seller Intake
        seller_cat = classify_turn_intent("酒楼出售 有兴趣了解吗？")
        self.assertEqual(seller_cat, "seller_intake")

        # 2. Chinese Unidentified Listing Inquiry
        unidentified_cat = classify_turn_intent("你们那一间店面在哪里？多少钱一个月？")
        self.assertEqual(unidentified_cat, "unidentified_listing")

        # 3. Buyer Search
        buyer_cat = classify_turn_intent("有没有文冬的榴莲园？想买3个acre左右")
        self.assertEqual(buyer_cat, "buyer_search")

    def test_mid_conversation_pivot(self):
        """Verifies dual-track memory preservation when a seller asks a buying question midway."""
        phone = "+60129998888"
        session = {
            "created_at": time.time(),
            "collected_data": {},
            "requirements_profile": {},
            "intent_progression": []
        }

        # Turn 1: Seller Intake
        t1_text = "我有一间位于Triang的酒楼要放盘出售，Lot 13169"
        res1 = process_persona_state_machine(
            phone_number=phone,
            raw_text=t1_text,
            session=session,
            conversation_history="",
            contact_name="Mr Tan",
            role="customer"
        )
        s1 = res1["updated_session"]
        self.assertEqual(s1.get("seller_track", {}).get("status"), "active")
        self.assertEqual(s1.get("current_agent"), "SELLER")

        # Turn 2: Mid-Conversation Pivot to Buyer
        t2_text = "顺便问一下，你们文冬有榴莲园卖吗？想找3-5英亩"
        history = f"User: {t1_text}\nAssistant: {res1['response']}"
        res2 = process_persona_state_machine(
            phone_number=phone,
            raw_text=t2_text,
            session=s1,
            conversation_history=history,
            contact_name="Mr Tan",
            role="customer"
        )
        s2 = res2["updated_session"]
        
        # Dual-track assertions: Seller track MUST NOT be wiped out!
        self.assertEqual(s2.get("seller_track", {}).get("status"), "active", "Seller track was erased during pivot!")
        self.assertEqual(s2.get("buyer_track", {}).get("status"), "active", "Buyer track was not activated!")
        self.assertIn("seller_track", s2)
        self.assertIn("buyer_track", s2)

    def test_conversation_71_anti_looping(self):
        """Simulates Mei Lin inquiry: Turn 1 triggers ad request, Turn 2 triggers Ah Tuck handover."""
        phone = "+60179658268"
        session = {
            "created_at": time.time(),
            "collected_data": {},
            "requirements_profile": {},
            "intent_progression": []
        }

        # Turn 1: Unidentified listing inquiry
        t1_text = "请问你们那一间店面租金是多少？在哪里？"
        res1 = process_persona_state_machine(
            phone_number=phone,
            raw_text=t1_text,
            session=session,
            conversation_history="",
            contact_name="Mei Lin",
            role="customer"
        )
        s1 = res1["updated_session"]
        self.assertFalse(res1.get("handover"), "Turn 1 must not trigger premature handover")
        self.assertEqual(s1.get("unidentified_listing_turns"), 1)
        # Asserts response executes Disambiguation Protocol asking for ad photo/link
        self.assertTrue(
            any(k in res1["response"] for k in ["广告截图", "照片", "链接", "screenshot", "link"]),
            "Turn 1 did not execute Listing Disambiguation Protocol"
        )

        # Turn 2: Audio/Ambiguous follow-up without identifying listing
        t2_text = "一个月多少钱？你们是代理还是屋主？"
        history = f"User: {t1_text}\nAssistant: {res1['response']}"
        res2 = process_persona_state_machine(
            phone_number=phone,
            raw_text=t2_text,
            session=s1,
            conversation_history=history,
            contact_name="Mei Lin",
            role="customer"
        )
        s2 = res2["updated_session"]
        
        # Anti-Looping Handover Guard asserts
        self.assertTrue(res2.get("handover"), "Turn 2 failed to trigger anti-looping handover")
        self.assertEqual(s2.get("unidentified_listing_turns"), 2)
        self.assertIn("阿Tuck", res2["response"])
        self.assertIn("012-9663589", res2["response"])
        self.assertEqual(res2.get("assignee_email"), AH_TUCK_EMAIL)

    def test_proxy_streaming(self):
        """Verifies GET /api/v1/documents/proxy handles Range byte-streaming with inline headers."""
        client = TestClient(app)
        mock_pdf_chunk = b"%PDF-1.4 1 0 obj << /Type /Catalog >> endobj %%EOF"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="PELAN_BANGUNAN.pdf"',
            "Content-Length": str(len(mock_pdf_chunk)),
            "Accept-Ranges": "bytes"
        }
        mock_resp.iter_content.return_value = [mock_pdf_chunk]
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            response = client.get(
                "/api/v1/documents/proxy",
                params={"url": "https://inbox.bentongland.com.my/rails/active_storage/disk/sample/PELAN_BANGUNAN.pdf"},
                headers={"Range": "bytes=0-100"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("content-type"), "application/pdf")
            self.assertIn("inline", response.headers.get("content-disposition", ""))
            self.assertEqual(response.headers.get("accept-ranges"), "bytes")


if __name__ == "__main__":
    unittest.main()
