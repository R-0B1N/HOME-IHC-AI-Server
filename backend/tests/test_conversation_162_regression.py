"""
Regression test suite for Conversation 162 root cause fixes.
Verifies that:
1. "tq", "lot", "solar", "boss" do not trigger false-positive Malay detection.
2. English sentences with Malaysian abbreviations remain classified as English.
3. Language sticky-latch is eliminated: English utterances restore session["language"] to "en".
4. MultiIntentMemoryTracker inherits existing seller role during neutral turns.
5. Seller track is strictly preserved across multi-turn inquiries without reverting to BUYER.
6. Seller sessions never match buyer inventory properties or cache ghost properties.
7. Seller intake turns never dispatch property listing images (images_to_send is empty).
8. get_multilingual_fallback returns seller-specific intake text rather than buyer budget qualification.
"""

import unittest
from unittest.mock import patch, MagicMock
from app.services.system_prompts import (
    MALAY_KEYWORDS,
    detect_customer_language,
    get_multilingual_fallback,
)
from app.services.agent_logic import (
    MultiIntentMemoryTracker,
    process_persona_state_machine,
)


class TestConversation162Regression(unittest.TestCase):
    def test_malay_keywords_exclusions(self):
        """Ensure common English/Manglish words are not in MALAY_KEYWORDS."""
        self.assertNotIn("tq", MALAY_KEYWORDS)
        self.assertNotIn("lot", MALAY_KEYWORDS)
        self.assertNotIn("solar", MALAY_KEYWORDS)
        self.assertNotIn("boss", MALAY_KEYWORDS)

    def test_detect_customer_language_heng_utterances(self):
        """Verify Heng's exact utterances in Conversation 162 are classified correctly."""
        # Turn 1
        t1 = "Hi there, I wish to sell off a house in Kampung Repas, Bentong. Are you interested?"
        self.assertEqual(detect_customer_language(t1), "en")

        # Turn 2
        t2 = "Besides, may I know you area of focus in Bentong?"
        self.assertEqual(detect_customer_language(t2), "en")

        # Turn 3 (previously falsely triggered Malay because of 'TQ')
        t3 = "Shall get these info in a while. TQ for reply"
        self.assertEqual(detect_customer_language(t3), "en")

        # Turn 4
        t4 = "Address is 67 Lorong Sentosa Kampung Repas, Bentong. (Read from Map)"
        self.assertEqual(detect_customer_language(t4), "en")

    def test_detect_customer_language_genuine_malay_and_chinese(self):
        """Verify genuine Malay and Chinese are correctly identified."""
        self.assertEqual(detect_customer_language("Saya nak jual tanah di Bentong"), "ms")
        self.assertEqual(detect_customer_language("Terima kasih atas bantuan"), "ms")
        self.assertEqual(detect_customer_language("Ada bilik sewa kosong?"), "ms")
        self.assertEqual(detect_customer_language("你好，请问你们有文冬的排屋吗？"), "zh")

    def test_language_sticky_lock_recovery(self):
        """Verify that a session previously marked 'ms' can switch back to 'en' upon English message."""
        session = {
            "language": "ms",
            "state": "IN_PROGRESS",
            "collected_data": {"name": "Heng"},
            "current_agent": "SELLER",
            "seller_track": {"status": "active"},
        }
        
        # When user types in English, session language should recover to 'en'
        actual_text = "Address is 67 Lorong Sentosa Kampung Repas, Bentong. (Read from Map)"
        with patch("app.services.agent_logic.generate_conversational_response") as mock_gen:
            mock_gen.return_value = {
                "response": "Received address.",
                "intent": "general",
                "asked_photos": False,
                "asked_specs": False,
                "asked_meeting": False,
                "promises_handover": False,
                "is_out_of_context": False,
                "extracted_data": {"location": "Kampung Repas, Bentong"}
            }
            res = process_persona_state_machine(
                phone_number="+60178754316",
                text=actual_text,
                session=session,
                conversation_history="User: Shall get these info in a while. TQ for reply\nAssistant: Terima kasih"
            )
            self.assertEqual(res["updated_session"].get("language"), "en")

    def test_role_inheritance_in_neutral_turn(self):
        """Verify MultiIntentMemoryTracker does not reset role to 'buyer' when customer is already a seller."""
        session = {
            "current_agent": "SELLER",
            "collected_data": {"customer_category": "seller"},
            "requirements_profile": {
                "active_inquiry": {
                    "role": "seller",
                    "category": "residential",
                    "property_type_label": "Residential House",
                    "location": "Kampung Repas, Bentong",
                }
            }
        }
        # Neutral inquiry: "Besides, may I know you area of focus in Bentong?"
        neutral_text = "Besides, may I know you area of focus in Bentong?"
        mem = MultiIntentMemoryTracker.update_session_memory(session, neutral_text)
        self.assertEqual(mem["active_inquiry"]["role"], "seller")

    def test_seller_track_persistence_across_neutral_turns(self):
        """Verify seller track and current_agent stay SELLER even on neutral questions."""
        session = {
            "current_agent": "SELLER",
            "collected_data": {"customer_category": "seller", "name": "Heng"},
            "seller_track": {"status": "active"},
        }
        neutral_text = "Besides, may I know you area of focus in Bentong?"
        with patch("app.services.agent_logic.generate_conversational_response") as mock_gen:
            mock_gen.return_value = {
                "response": "Home IHC focuses across Bentong and surrounding Pahang areas.",
                "intent": "general",
                "asked_photos": False,
                "asked_specs": False,
                "asked_meeting": False,
                "promises_handover": False,
                "is_out_of_context": False,
                "extracted_data": {}
            }
            res = process_persona_state_machine(
                phone_number="+60178754316",
                text=neutral_text,
                session=session,
                conversation_history="User: I wish to sell off a house\nAssistant: Hello Irene Leong here"
            )
            updated = res["updated_session"]
            self.assertEqual(updated.get("current_agent"), "SELLER")
            self.assertEqual(updated.get("seller_track", {}).get("status"), "active")
            self.assertEqual(updated.get("collected_data", {}).get("customer_category"), "seller")
            # Must NOT cache an inventory property into interested_property
            self.assertIsNone(updated.get("interested_property"))

    def test_seller_photo_shield(self):
        """Verify that when a seller sends photos or documents, inventory photos are never dispatched."""
        session = {
            "current_agent": "SELLER",
            "collected_data": {"customer_category": "seller", "name": "Heng"},
            "seller_track": {"status": "active"},
            # Even if interested_property was somehow in session, it must be purged and suppressed
            "interested_property": {
                "id": 99,
                "title": "Bera, Taman Chengal House",
                "image_urls": ["https://bentongland.com.my/wp-content/uploads/2026/06/IMG-20240328-WA0012.webp"]
            }
        }
        with patch("app.services.agent_logic.generate_conversational_response") as mock_gen:
            mock_gen.return_value = {
                "response": "Thank you, we received your document.",
                "intent": "general",
                "asked_photos": True,
                "asked_specs": False,
                "asked_meeting": False,
                "promises_handover": False,
                "is_out_of_context": False,
                "extracted_data": {}
            }
            res = process_persona_state_machine(
                phone_number="+60178754316",
                text="Here is the Geran 67 Kg Repas for REF.pdf",
                session=session,
                conversation_history="User: I wish to sell\nAssistant: Ok"
            )
            self.assertEqual(res["images_to_send"], [])
            self.assertIsNone(res["updated_session"].get("interested_property"))

    def test_get_multilingual_fallback_seller_vs_buyer(self):
        """Verify fallback returns seller valuation text for sellers, not buyer budget inquiry."""
        history = "User: I want to sell\nAssistant: Hello Irene Leong here"
        
        # Buyer fallback
        buyer_fallback_en = get_multilingual_fallback("en", history, is_seller=False)
        self.assertIn("budget range", buyer_fallback_en)

        # Seller fallback
        seller_fallback_en = get_multilingual_fallback("en", history, is_seller=True)
        self.assertNotIn("budget range", seller_fallback_en)
        self.assertIn("valuation", seller_fallback_en)

        # Seller fallback in Chinese
        seller_fallback_zh = get_multilingual_fallback("zh", history, is_seller=True)
        self.assertNotIn("预算", seller_fallback_zh)
        self.assertIn("评估", seller_fallback_zh)


if __name__ == "__main__":
    unittest.main()
