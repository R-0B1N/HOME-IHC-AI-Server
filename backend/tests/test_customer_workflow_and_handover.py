"""
Unit and Integration Tests for 4-Step Customer Conversation & Handover Workflow:
1. Customer Ingress: AI asks specifically which category they belong to, adhering to Step 2 of the Router Workflow.
   If first message explicitly specifies role or property info, role is auto-assigned.
2. Role Assignment & Premature Questions: AI assigns role and asks premature questions if no property information was provided.
3. Qualified Handover: Once enough information is gathered, handover proceeds to specialist agent or Irene Leong.
4. Out-of-Scope Redirection: If not enough information was gathered and query is out of scope, immediately redirect
   to Irene Leong (+60 11-6514 4931) and active admin numbers registered in crm_users (never generic email).
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.system_prompts import (
    IRENE_MAIN_PHONE,
    IRENE_DISPLAY_PHONE,
    DIGITAL_NAME_CARD_URL,
    get_multilingual_greeting,
    get_multilingual_premature_questions,
    get_multilingual_out_of_scope_redirect,
    get_multilingual_fallback,
    build_system_prompt,
)
from app.services.agent_logic import process_persona_state_machine
from app.services.lead_handover import LeadHandoverService, AgentSpecializationScorer


class TestCustomerWorkflowStep1Ingress(unittest.TestCase):
    """Step 1: Customer Ingress and Step 2 Category Prompting."""

    def test_greeting_presents_step2_categories_multilingual(self):
        # English greeting
        en_greet = get_multilingual_greeting("en")
        self.assertIn("Irene Leong", en_greet)
        self.assertIn(DIGITAL_NAME_CARD_URL, en_greet)
        self.assertIn("Personal Buyer", en_greet)
        self.assertIn("Property Agent / Broker", en_greet)
        self.assertIn("Seller / Property Owner", en_greet)

        # Chinese greeting
        zh_greet = get_multilingual_greeting("zh")
        self.assertIn("Irene Leong", zh_greet)
        self.assertIn(DIGITAL_NAME_CARD_URL, zh_greet)
        self.assertIn("个人买家", zh_greet)
        self.assertIn("房产经纪 / 中介", zh_greet)
        self.assertIn("业主 / 卖家", zh_greet)

        # Malay greeting
        ms_greet = get_multilingual_greeting("ms")
        self.assertIn("Irene Leong", ms_greet)
        self.assertIn(DIGITAL_NAME_CARD_URL, ms_greet)
        self.assertIn("Pembeli Peribadi", ms_greet)
        self.assertIn("Ejen Hartanah / Broker", ms_greet)
        self.assertIn("Penjual / Pemilik Hartanah", ms_greet)

    def test_vague_first_message_returns_step2_categories(self):
        session = {}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="Hi, good morning",
            session=session,
            conversation_history="",
            contact_name="Tan",
        )
        resp = result.get("response", "")
        self.assertIn("Irene Leong", resp)
        self.assertIn("Personal Buyer", resp)
        self.assertIn("Property Agent / Broker", resp)
        self.assertIn("Seller / Property Owner", resp)
        self.assertFalse(result.get("handover", True))
        self.assertTrue(result.get("updated_session", {}).get("introduced"))

    @patch("app.services.agent_logic.generate_conversational_response")
    def test_explicit_first_message_auto_assigns_role_without_category_menu(self, mock_llm_gen):
        mock_llm_gen.return_value = {
            "response": "We have great durian land options in Bentong!",
            "intent": "buyer",
            "extracted_data": {"buyer_location": "Bentong", "buyer_property_type": "Durian Land"},
        }
        session = {}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="Hi Irene, I want to buy 5 acres durian land in Bentong with RM 1 million budget",
            session=session,
            conversation_history="",
            contact_name="David",
        )
        up_sess = result.get("updated_session", {})
        self.assertEqual(up_sess.get("current_agent"), "BUYER")
        self.assertEqual(up_sess.get("collected_data", {}).get("customer_category"), "buyer")
        # LLM was invoked because property details were explicitly provided
        mock_llm_gen.assert_called_once()


class TestCustomerWorkflowStep2RoleAssignmentAndPrematureQuestions(unittest.TestCase):
    """Step 2: Role Assignment & Premature Qualification Questions."""

    def test_assign_buyer_role_and_ask_premature_questions(self):
        # Customer selects "Personal Buyer" or "1" without property details
        session = {"introduced": True}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="🙋 Personal Buyer",
            session=session,
            conversation_history="User: Hi\nAssistant: May I know which category you belong to?",
            contact_name="John",
        )
        up_sess = result.get("updated_session", {})
        self.assertEqual(up_sess.get("current_agent"), "BUYER")
        self.assertEqual(up_sess.get("collected_data", {}).get("customer_category"), "buyer")
        resp = result.get("response", "")
        # Checks premature buyer questions
        self.assertTrue(any(kw in resp.lower() for kw in ["area", "budget", "property", "looking", "bentong"]))
        self.assertFalse(result.get("handover", True))

    def test_assign_seller_role_and_ask_premature_questions(self):
        # Customer selects "3" or "Seller / Property Owner"
        session = {"introduced": True}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="3",
            session=session,
            conversation_history="User: Hi\nAssistant: May I know which category you belong to?",
            contact_name="Uncle Lee",
        )
        up_sess = result.get("updated_session", {})
        self.assertEqual(up_sess.get("current_agent"), "SELLER")
        self.assertEqual(up_sess.get("collected_data", {}).get("customer_category"), "seller")
        resp = result.get("response", "")
        # Checks premature seller questions (location, type/size, asking price, geran)
        self.assertTrue(any(kw in resp.lower() for kw in ["asking price", "geran", "located", "size", "property"]))
        self.assertFalse(result.get("handover", True))

    def test_assign_agent_role_and_ask_premature_questions(self):
        # Customer selects "2" or "Property Agent / Broker"
        session = {"introduced": True}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="🤝 Property Agent / Broker",
            session=session,
            conversation_history="User: Hi\nAssistant: May I know which category you belong to?",
            contact_name="Ken",
        )
        up_sess = result.get("updated_session", {})
        self.assertEqual(up_sess.get("current_agent"), "AGENT")
        self.assertEqual(up_sess.get("collected_data", {}).get("customer_category"), "agent")
        resp = result.get("response", "")
        # Checks premature agent questions (agency, REN, client requirements)
        self.assertTrue(any(kw in resp.lower() for kw in ["agency", "ren", "co-broking", "client", "requirements"]))
        self.assertFalse(result.get("handover", True))


class TestCustomerWorkflowStep3QualifiedHandover(unittest.TestCase):
    """Step 3: Qualified Handover to Specialist Agent or Irene Leong."""

    def test_buyer_qualified_handover_routes_to_top_specialist(self):
        scorer = AgentSpecializationScorer()
        mock_agents = [
            {
                "name": "Ah Tuck",
                "phone_number": "+60129663589",
                "assigned_locations": ["Bentong", "Karak"],
                "assigned_property_types": ["Land / Agriculture", "Commercial"],
            },
            {
                "name": "General Agent",
                "phone_number": "+60121111111",
                "assigned_locations": ["Kuantan"],
                "assigned_property_types": ["Residential"],
            },
        ]
        mock_template = MagicMock()
        mock_contact = MagicMock()
        mock_note = MagicMock()
        mock_label = MagicMock()

        service = LeadHandoverService(
            scorer=scorer,
            get_active_agents_func=lambda: mock_agents,
            send_template_func=mock_template,
            send_contact_func=mock_contact,
            send_private_note_func=mock_note,
            apply_label_func=mock_label,
            set_priority_func=MagicMock(),
            update_status_func=MagicMock(),
            get_or_create_contact_func=MagicMock(return_value=123),
            create_conversation_func=MagicMock(return_value=456),
        )

        res = service.dispatch(
            conversation_id=999,
            customer_name="Mr. Wong",
            customer_phone="+60179998888",
            intent="BUYER",
            location="Bentong",
            property_type="Land / Agriculture",
            budget="RM 800,000",
            conversation_summary="Looking for 3-acre agricultural land in Bentong with RM 800k budget.",
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("+60129663589", res["routed_to"])
        self.assertIn("+601165144931", res["routed_to"])  # Irene Leong admin copy
        self.assertEqual(len(res["assigned_agents"]), 1)
        self.assertEqual(res["assigned_agents"][0]["name"], "Ah Tuck")
        # Template dispatch to specialist agent and admin copy using approved template
        self.assertEqual(mock_template.call_count, 3)
        first_call_kwargs = mock_template.call_args_list[0][1]
        self.assertEqual(first_call_kwargs["template_name"], "new_lead_alert_utility")
        self.assertEqual(first_call_kwargs["language_code"], "en")
        # WhatsApp contact card of winner sent to customer
        mock_contact.assert_called_once_with(
            inbox_id=3,
            to_phone="+60179998888",
            contact_name="Ah Tuck",
            contact_phone="+60129663589",
            override_phone_number_id="1039310802596891",
        )

    def test_agent_co_broke_routes_directly_to_irene_main_number(self):
        mock_template = MagicMock()
        mock_contact = MagicMock()
        mock_note = MagicMock()
        mock_label = MagicMock()

        service = LeadHandoverService(
            send_template_func=mock_template,
            send_contact_func=mock_contact,
            send_private_note_func=mock_note,
            apply_label_func=mock_label,
            set_priority_func=MagicMock(),
            update_status_func=MagicMock(),
            get_or_create_contact_func=MagicMock(return_value=123),
            create_conversation_func=MagicMock(return_value=456),
        )

        res = service.dispatch(
            conversation_id=888,
            customer_name="REN Agent David",
            customer_phone="+60198887777",
            intent="AGENT",
            location="Bentong",
            property_type="Commercial",
            budget="Co-Broke",
            conversation_summary="REN 54321 looking to co-broke commercial lot in Bentong.",
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("+601165144931", res["routed_to"])
        mock_contact.assert_called_once()
        args, kwargs = mock_contact.call_args
        self.assertEqual(kwargs["contact_phone"], "+601165144931")
        self.assertEqual(kwargs["contact_name"], "Irene Leong (Main Number)")

    def test_unmatched_specialist_fallback_routes_to_irene_and_active_admins(self):
        mock_template = MagicMock()
        mock_contact = MagicMock()

        # Mock DB with active admin users
        mock_db = MagicMock()
        admin1 = MagicMock()
        admin1.role = "admin"
        admin1.is_active = True
        admin1.phone_number = "+60123334444"
        admin1.full_name = "Admin Bob"
        mock_db.query.return_value.filter.return_value.all.return_value = [admin1]

        service = LeadHandoverService(
            get_active_agents_func=lambda: [],  # 0 matching agents
            send_template_func=mock_template,
            send_contact_func=mock_contact,
            send_private_note_func=MagicMock(),
            apply_label_func=MagicMock(),
            set_priority_func=MagicMock(),
            update_status_func=MagicMock(),
            get_or_create_contact_func=MagicMock(return_value=123),
            create_conversation_func=MagicMock(return_value=456),
        )

        res = service.dispatch(
            conversation_id=777,
            customer_name="Inquirer",
            customer_phone="+60165554433",
            intent="BUYER",
            location="Unmatched Area",
            property_type="Unmatched Type",
            budget="RM 100k",
            conversation_summary="General unmatched inquiry",
            db=mock_db,
        )

        self.assertEqual(res["status"], "fallback_to_admin")
        self.assertTrue(res["is_fallback"])
        # Irene Leong is ALWAYS primary at index 0
        self.assertIn("+601165144931", res["routed_to"])
        self.assertIn("+60123334444", res["routed_to"])
        self.assertEqual(res["routed_to"][0], "+601165144931")


class TestCustomerWorkflowStep4OutOfScopeRedirection(unittest.TestCase):
    """Step 4: Out-of-Scope Redirection to Irene Leong and Active Admins."""

    def test_out_of_scope_message_redirects_to_irene_and_never_email(self):
        # Chinese out-of-scope redirection
        zh_ooc = get_multilingual_out_of_scope_redirect("zh", "张先生")
        self.assertIn("Irene Leong", zh_ooc)
        self.assertIn(IRENE_DISPLAY_PHONE, zh_ooc)
        self.assertNotIn("homeihc13@gmail.com", zh_ooc)
        self.assertNotIn("@", zh_ooc)

        # English out-of-scope redirection
        en_ooc = get_multilingual_out_of_scope_redirect("en", "Mr. Tan")
        self.assertIn("Irene Leong", en_ooc)
        self.assertIn(IRENE_DISPLAY_PHONE, en_ooc)
        self.assertNotIn("homeihc13@gmail.com", en_ooc)

        # Malay out-of-scope redirection
        ms_ooc = get_multilingual_out_of_scope_redirect("ms", "Encik Ali")
        self.assertIn("Irene Leong", ms_ooc)
        self.assertIn(IRENE_DISPLAY_PHONE, ms_ooc)
        self.assertNotIn("homeihc13@gmail.com", ms_ooc)

    def test_state_machine_intercepts_job_vacancy_out_of_scope(self):
        session = {}
        result = process_persona_state_machine(
            phone_number="+60123456789",
            raw_text="Hi, ada kerja kosong tak? Saya nak cari kerja part time",
            session=session,
            conversation_history="",
            contact_name="Ahmad",
        )
        self.assertTrue(result.get("handover"))
        self.assertEqual(result.get("intent"), "OUT_OF_SCOPE")
        resp = result.get("response", "")
        self.assertIn("Irene Leong", resp)
        self.assertIn(IRENE_DISPLAY_PHONE, resp)
        self.assertNotIn("homeihc13@gmail.com", resp)
        self.assertEqual(result.get("assignee_phone"), IRENE_MAIN_PHONE)

    def test_out_of_scope_dispatch_routes_to_irene_and_crm_admins(self):
        mock_template = MagicMock()
        mock_contact = MagicMock()
        mock_note = MagicMock()
        mock_label = MagicMock()

        # Mock DB with active admin users
        mock_db = MagicMock()
        admin1 = MagicMock()
        admin1.role = "admin"
        admin1.is_active = True
        admin1.phone_number = "+60192223333"
        admin1.full_name = "Admin Sarah"
        mock_db.query.return_value.filter.return_value.all.return_value = [admin1]

        service = LeadHandoverService(
            send_template_func=mock_template,
            send_contact_func=mock_contact,
            send_private_note_func=mock_note,
            apply_label_func=mock_label,
            set_priority_func=MagicMock(),
            update_status_func=MagicMock(),
            get_or_create_contact_func=MagicMock(return_value=123),
            create_conversation_func=MagicMock(return_value=456),
        )

        res = service.dispatch(
            conversation_id=555,
            customer_name="Job Seeker",
            customer_phone="+60123456789",
            intent="OUT_OF_SCOPE",
            location="N/A",
            property_type="N/A",
            budget="N/A",
            conversation_summary="User asked for job vacancy/employment.",
            db=mock_db,
        )

        self.assertEqual(res["status"], "success")
        # Dispatches to Irene Leong primary (+601165144931) and active admin (+60192223333)
        self.assertIn("+601165144931", res["routed_to"])
        self.assertIn("+60192223333", res["routed_to"])
        self.assertEqual(res["routed_to"][0], "+601165144931")

        # Sends Irene's contact card to customer
        mock_contact.assert_called_once()
        _, kwargs = mock_contact.call_args
        self.assertEqual(kwargs["contact_phone"], "+601165144931")

        # Labels include 'out-of-scope' and 'human-handover'
        mock_label.assert_called_once_with(555, ["out-of-scope", "human-handover"])


class TestConversationProcessorAndReportingAttribution(unittest.TestCase):
    """
    Verifies that:
    1. Customer state persistence preserves assigned agent attribution and bypass_ai.
    2. Customer response text explicitly introduces the matched specialist agent.
    3. BuyerReportGenerator extracts the assigned agent and fallback heuristic works.
    """

    @patch("app.services.conversation_processor.apply_label")
    @patch("app.services.conversation_processor.set_priority")
    @patch("app.services.conversation_processor.assign_agent")
    def test_persist_state_and_labels_saves_assigned_agent(self, mock_assign, mock_priority, mock_label):
        from app.services.conversation_processor import ConversationQueueProcessor

        mock_customer = MagicMock()
        mock_customer.id = "601116921383"

        mock_db_customer = MagicMock()
        mock_db_customer.id = "601116921383"
        mock_db_customer.metadata_json = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_db_customer

        processor = ConversationQueueProcessor(session_factory=lambda: mock_db)
        processor.persist_state_and_labels(
            conversation_id=202,
            customer=mock_customer,
            lead_temp="hot",
            handover_initiated=True,
            role="customer",
            intent="tenant",
            assignee_email="ahtat@bentongland.com.my",
            assigned_agent="Ah Tat",
            assigned_agent_phone="+60129663589",
        )

        self.assertTrue(mock_db_customer.metadata_json.get("bypass_ai"))
        self.assertEqual(mock_db_customer.metadata_json.get("assigned_agent"), "Ah Tat")
        self.assertEqual(mock_db_customer.metadata_json.get("assigned_agent_phone"), "+60129663589")
        self.assertEqual(mock_db_customer.metadata_json.get("lead_temp"), "hot")
        mock_db.commit.assert_called_once()
        mock_label.assert_called_once()

    def test_buyer_report_generator_formats_assigned_agent(self):
        from app.services.reporting import BuyerReportGenerator

        gen = BuyerReportGenerator()

        c_assigned = MagicMock()
        c_assigned.id = "601116921383"
        c_assigned.contact_name = "Wong"
        c_assigned.email = ""
        c_assigned.phone_number = "+601116921383"
        c_assigned.created_at = None
        c_assigned.last_interaction = None
        c_assigned.updated_at = None
        c_assigned.metadata_json = {
            "intent": "tenant",
            "location": "Bentong",
            "property_type": "Rental",
            "budget": "RM 2,000",
            "lead_temp": "hot",
            "bypass_ai": True,
            "assigned_agent": "Ah Tat",
            "assigned_agent_phone": "+60129663589",
        }

        row = gen._format_buyer_row(c_assigned)
        self.assertIsNotNone(row)
        self.assertEqual(row[9], "Ah Tat (+60129663589)")
        self.assertEqual(row[10], "Yes")

    def test_buyer_report_generator_historical_fallback_for_bentong_tenant(self):
        from app.services.reporting import BuyerReportGenerator

        gen = BuyerReportGenerator()

        c_historical = MagicMock()
        c_historical.id = "601116921383"
        c_historical.contact_name = "Tenant Lead"
        c_historical.email = ""
        c_historical.phone_number = "+601116921383"
        c_historical.created_at = None
        c_historical.last_interaction = None
        c_historical.updated_at = None
        c_historical.metadata_json = {
            "intent": "tenant",
            "location": "Bentong",
            "property_type": "Property Inquiry",
            "lead_temp": "hot",
            "bypass_ai": True,
        }

        row = gen._format_buyer_row(c_historical)
        self.assertIsNotNone(row)
        # Should fallback to Ah Tat via Bentong + Tenant heuristic
        self.assertEqual(row[9], "Ah Tat (+60129663589)")


if __name__ == "__main__":
    unittest.main()
