import unittest
from unittest.mock import MagicMock, patch
from app.services.system_prompts import is_handover_promised
from app.api.settings import (
    get_system_toggle,
    set_system_toggle,
    get_ai_status,
    set_ai_status,
    get_followup_status,
    set_followup_status,
    AIToggleState
)
from app.services.lead_nurturing import LeadNurturingManager


class TestHandoverAndDashboardToggles(unittest.TestCase):

    def test_handover_promise_detection(self):
        """Validates that assistant responses promising senior/specialist trigger is_handover_promised across languages."""
        test_cases = [
            # English
            ("A senior property specialist will contact you shortly to assist directly.", True),
            ("Our senior agent will reach out to you tomorrow morning.", True),
            ("We have generated your viewing acknowledgement.", True),
            ("I will have our senior specialist reach out to schedule an appointment.", True),
            ("Here are the listing details for the durian orchard.", False),
            
            # Chinese
            ("我会安排我们的资深房产专员联系您，为您提供详细解答。", True),
            ("稍后我们的资深主管会致电与您直接联系。", True),
            ("我们正在为您准备官方客户看房确认书。", True),
            ("我们的一位专员会联系您跟进。", True),
            ("稍后会电话联系您。", True),
            ("文冬的榴莲园地目前售价为每英亩 RM 180,000。", False),

            # Malay
            ("Pegawai hartanah kanan kami akan menghubungi anda sebentar lagi.", True),
            ("Pengurus kanan kami akan hubungi anda untuk urusan lawatan.", True),
            ("Kami sedang menyediakan borang pengesahan lawatan rasmi.", True),
            ("Rakan sekerja kami akan hubungi anda esok.", True),
            ("Tanah pertanian di Bentong ini mempunyai sumber air sungai semula jadi.", False)
        ]

        for text, expected in test_cases:
            with self.subTest(text=text):
                self.assertEqual(is_handover_promised(text), expected, f"Failed for text: {text}")

    def test_dashboard_toggle_api_and_fallback(self):
        """Validates /settings/ai-status and /settings/followup-status state synchronization."""
        # 1. Master AI Toggle
        set_ai_status(AIToggleState(enabled=False))
        self.assertFalse(get_ai_status()["enabled"])
        self.assertFalse(get_system_toggle("master_ai_enabled"))

        set_ai_status(AIToggleState(enabled=True))
        self.assertTrue(get_ai_status()["enabled"])
        self.assertTrue(get_system_toggle("master_ai_enabled"))

        # 2. Follow-Up Engine Toggle
        set_followup_status(AIToggleState(enabled=False))
        self.assertFalse(get_followup_status()["enabled"])
        self.assertFalse(get_system_toggle("lead_nurturing_enabled"))

        set_followup_status(AIToggleState(enabled=True))
        self.assertTrue(get_followup_status()["enabled"])
        self.assertTrue(get_system_toggle("lead_nurturing_enabled"))

    def test_lead_nurturing_daemon_gated_by_followup_toggle(self):
        """Validates that LeadNurturingManager skips running cycles when follow-up toggle is disabled."""
        set_system_toggle("lead_nurturing_enabled", False)
        
        manager = LeadNurturingManager(
            db_session=MagicMock(),
            message_sender=MagicMock(),
            note_sender=MagicMock()
        )
        res = manager.run_cycle()
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "followup_disabled")

        # Re-enable
        set_system_toggle("lead_nurturing_enabled", True)


if __name__ == "__main__":
    unittest.main()
