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

    @patch("app.services.agent_logic.generate_conversational_response")
    @patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory")
    def test_dynamic_llm_promises_handover_triggers_state_completion(self, mock_persist, mock_gen):
        """Validates that dynamic sparse LLM key 'promises_handover: true' triggers handover without regex reliance."""
        from app.services.agent_logic import process_persona_state_machine

        mock_gen.return_value = {
            "response": "Hello, I will arrange for our lead to follow up with you.",
            "intent": "buyer",
            "promises_handover": True,
            "asked_meeting": False,
            "asked_photos": False,
            "asked_specs": False,
            "asked_alternatives": False,
            "is_out_of_context": False,
            "extracted_data": {}
        }

        res = process_persona_state_machine(
            phone_number="+60129998888",
            text="Can someone check on this property?",
            conversation_history="",
            session={"state": "INITIAL", "collected_data": {}}
        )

        self.assertTrue(res["handover"], "Handover must be True when LLM sets promises_handover=True")
        self.assertTrue(res["promises_handover"], "promises_handover must be True in return dict")
        self.assertEqual(res["updated_session"]["state"], "COMPLETED", "Session state must transition to COMPLETED")

    @patch("requests.post")
    def test_update_conversation_status(self, mock_post):
        """Validates that update_conversation_status calls toggle_status endpoint with status=open."""
        from app.services.chatwoot import update_conversation_status
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": 456, "status": "open"}
        mock_post.return_value = mock_resp

        res = update_conversation_status(456, "open")
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "open")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("/conversations/456/toggle_status", args[0])
        self.assertEqual(kwargs["json"], {"status": "open"})

    @patch("app.services.db_services.get_sender_role")
    def test_lead_nurturing_skips_internal_staff(self, mock_get_role):
        """Validates that evaluate_customer suppresses follow-up messages for employees, agents, and admins."""
        from datetime import datetime, timezone, timedelta
        from app.db.models import Customer
        
        manager = LeadNurturingManager(
            db_session=MagicMock(),
            message_sender=MagicMock(),
            note_sender=MagicMock()
        )
        now = datetime.now(timezone.utc)
        
        # Staff Employee Customer
        emp_cust = MagicMock(spec=Customer)
        emp_cust.id = "+60198765432"
        emp_cust.phone_number = "+60198765432"
        emp_cust.contact_name = "Staff Member"
        emp_cust.created_at = now - timedelta(days=4)
        emp_cust.updated_at = now - timedelta(days=4)
        emp_cust.last_interaction = now - timedelta(days=4)
        emp_cust.metadata_json = {"lead_temp": "warm", "conversation_id": 2001, "bypass_ai": False}
        
        # 1. Staff Employee: Suppressed
        mock_get_role.return_value = "employee"
        res_emp = manager.evaluate_customer(emp_cust, now=now)
        self.assertIsNone(res_emp, "Employee must NEVER be evaluated for lead follow-up")
        
        # 2. Staff Agent: Suppressed
        mock_get_role.return_value = "agent"
        res_agent = manager.evaluate_customer(emp_cust, now=now)
        self.assertIsNone(res_agent, "Internal agent must NEVER be evaluated for lead follow-up")
        
        # 3. Staff Admin: Suppressed
        mock_get_role.return_value = "admin"
        res_admin = manager.evaluate_customer(emp_cust, now=now)
        self.assertIsNone(res_admin, "Admin must NEVER be evaluated for lead follow-up")
        
        # 4. Genuine Customer: Successfully evaluated
        mock_get_role.return_value = "customer"
        res_cust = manager.evaluate_customer(emp_cust, now=now)
        self.assertIsNotNone(res_cust, "Genuine prospective customer must be evaluated for follow-up")
        self.assertEqual(res_cust["conversation_id"], 2001)


if __name__ == "__main__":
    unittest.main()

