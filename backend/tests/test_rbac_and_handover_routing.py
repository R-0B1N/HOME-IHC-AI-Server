"""
Unit and Integration Test Suite for Tasks 3 & 4:
- WhatsApp AI RBAC layer (Phone lookup against crm_users with fallback to legacy Admins/Employees, Customer vs Agent vs Admin data isolation)
- Dynamic Hot Lead Handover routing based on agent specialization (Locations & Property Types scoring, Ties with Shared Case remark, Admin Fallback, Contact Card dispatch)
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.db_services import (
    normalize_phone_variants,
    get_sender_role,
    get_active_crm_user_by_phone,
    get_active_agents_and_employees,
)
from app.worker.tasks import (
    calculate_agent_specialization_score,
    dispatch_hot_lead_handover,
    CONFIGURED_LOCATIONS,
    CONFIGURED_PROPERTY_TYPES,
    DEFAULT_FALLBACK_ADMIN_NUMBERS,
)
from app.services.agent_logic import generate_conversational_response


class TestPhoneNormalizationAndRoleLookup(unittest.TestCase):
    """Test phone normalization variants and hierarchical RBAC role determination."""

    def test_normalize_phone_variants_malaysian(self):
        # International with plus
        variants = normalize_phone_variants("+60123456789")
        self.assertIn("+60123456789", variants)
        self.assertIn("60123456789", variants)
        self.assertIn("0123456789", variants)

        # Local leading 0
        variants_local = normalize_phone_variants("0123456789")
        self.assertIn("0123456789", variants_local)
        self.assertIn("60123456789", variants_local)
        self.assertIn("+60123456789", variants_local)

    def test_normalize_phone_variants_international(self):
        variants = normalize_phone_variants("+14709202239")
        self.assertIn("+14709202239", variants)
        self.assertIn("14709202239", variants)

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_crm_users_admin(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # User in crm_users with role="admin" and is_active=True
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_user.is_active = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        role = get_sender_role("+601165144931")
        self.assertEqual(role, "admin")

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_crm_users_agent(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_user = MagicMock()
        mock_user.role = "agent"
        mock_user.is_active = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        role = get_sender_role("+60123456789")
        self.assertEqual(role, "agent")

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_crm_users_employee(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_user = MagicMock()
        mock_user.role = "employee"
        mock_user.is_active = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        role = get_sender_role("+60198765432")
        self.assertEqual(role, "employee")

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_inactive_crm_user_ignored(self, mock_session_cls):
        """Inactive users in crm_users must NOT receive elevated privileges."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # First query on crm_users returns inactive user (filter condition is_active == True makes it None)
        # We simulate returning None for User query and None for legacy Admin/Employee queries
        mock_db.query.return_value.filter.return_value.first.return_value = None

        role = get_sender_role("+60129999999")
        self.assertEqual(role, "customer")

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_fallback_legacy_tables(self, mock_session_cls):
        """If phone not in crm_users, verify fallback to legacy Admin/Employee tables."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # crm_users returns None, but legacy Admin query returns admin
        def query_side_effect(model):
            mock_q = MagicMock()
            if model.__name__ == "Admin":
                mock_admin = MagicMock()
                mock_admin.phone_number = "+601165144931"
                mock_q.filter.return_value.first.return_value = mock_admin
            else:
                mock_q.filter.return_value.first.return_value = None
            return mock_q

        mock_db.query.side_effect = query_side_effect

        role = get_sender_role("+601165144931")
        self.assertEqual(role, "admin")

    @patch("app.services.db_services.SessionLocal")
    def test_get_sender_role_unregistered_customer(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        role = get_sender_role("+60170000000")
        self.assertEqual(role, "customer")


class TestAgentSpecializationScoring(unittest.TestCase):
    """Test specialization scoring against Bentong/Pahang locations and property types."""

    def test_configured_defaults(self):
        self.assertIn("Bentong", CONFIGURED_LOCATIONS)
        self.assertIn("Temerloh", CONFIGURED_LOCATIONS)
        self.assertIn("Karak", CONFIGURED_LOCATIONS)
        self.assertIn("Raub", CONFIGURED_LOCATIONS)
        self.assertIn("Pahang", CONFIGURED_LOCATIONS)

        self.assertIn("Rental", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Residential", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Commercial", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Land / Agriculture", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Industrial", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Durian Land", CONFIGURED_PROPERTY_TYPES)
        self.assertIn("Factory", CONFIGURED_PROPERTY_TYPES)

    def test_specialization_scoring_perfect_match(self):
        agent = {
            "name": "Irene",
            "phone_number": "+60121111111",
            "assigned_locations": ["Bentong", "Karak"],
            "assigned_property_types": ["Durian Land", "Land / Agriculture"]
        }
        lead_data = {
            "city": "Bentong",
            "state": "Pahang",
            "property_category": ["Durian Land"],
            "inquiry_text": "I am looking for a 5-acre durian land in Bentong"
        }
        score = calculate_agent_specialization_score(agent, lead_data)
        # 1 point for Bentong (city match) + 1 point for Durian Land (category match)
        self.assertEqual(score, 2)

    def test_specialization_scoring_partial_and_zero_match(self):
        agent = {
            "name": "Kelvin",
            "phone_number": "+60122222222",
            "assigned_locations": ["Raub"],
            "assigned_property_types": ["Commercial"]
        }
        # Lead for Bentong Durian Land
        lead_bentong = {
            "city": "Bentong",
            "property_category": ["Durian Land"],
            "inquiry_text": "Looking for durian land in Bentong"
        }
        score_zero = calculate_agent_specialization_score(agent, lead_bentong)
        self.assertEqual(score_zero, 0)

        # Lead for Raub Residential
        lead_raub = {
            "city": "Raub",
            "property_category": ["Residential"],
            "inquiry_text": "Semi-D house in Raub"
        }
        score_one = calculate_agent_specialization_score(agent, lead_raub)
        self.assertEqual(score_one, 1)


class TestDynamicHotLeadHandoverRouting(unittest.TestCase):
    """Test winner selection, multi-agent ties with shared case remark, and admin fallback."""

    @patch("app.worker.tasks.send_whatsapp_contact")
    @patch("app.worker.tasks.send_whatsapp_template")
    @patch("app.worker.tasks.get_active_agents_and_employees")
    def test_single_winner_dispatch(self, mock_get_agents, mock_send_template, mock_send_contact):
        """When one agent has highest specialization score, route solely to them."""
        mock_get_agents.return_value = [
            {
                "id": "1",
                "name": "Agent Bentong Specialist",
                "phone_number": "+60121111111",
                "role": "agent",
                "assigned_locations": ["Bentong", "Karak"],
                "assigned_property_types": ["Durian Land"]
            },
            {
                "id": "2",
                "name": "Agent Raub Specialist",
                "phone_number": "+60122222222",
                "role": "agent",
                "assigned_locations": ["Raub"],
                "assigned_property_types": ["Residential"]
            }
        ]

        lead_data = {
            "customer_phone": "+60170000001",
            "customer_name": "Tan Sri Lim",
            "city": "Bentong",
            "property_category": ["Durian Land"],
            "title": "Bentong Musang King Farm",
            "inquiry_text": "Interested in viewing the Bentong Musang King farm"
        }

        result = dispatch_hot_lead_handover(lead_data)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["assigned_agents"]), 1)
        self.assertEqual(result["assigned_agents"][0]["phone_number"], "+60121111111")
        self.assertEqual(result["winning_score"], 2)

        # Verified template dispatch to winner
        self.assertEqual(mock_send_template.call_count, 1)
        template_call_args = mock_send_template.call_args[1]
        self.assertEqual(template_call_args["to_phone"], "+60121111111")
        # Ensure NO shared case warning is in parameters for single winner
        param_7 = template_call_args["parameters"][6]
        self.assertNotIn("⚠️ Shared Case", param_7)

        # Verified customer contact card sent for the winner
        mock_send_contact.assert_called_once()
        contact_call_args = mock_send_contact.call_args[1]
        self.assertEqual(contact_call_args["to_phone"], "+60170000001")
        self.assertEqual(contact_call_args["contact_phone"], "+60121111111")

    @patch("app.worker.tasks.send_whatsapp_contact")
    @patch("app.worker.tasks.send_whatsapp_template")
    @patch("app.worker.tasks.get_active_agents_and_employees")
    def test_multi_agent_tie_with_shared_case_remark(self, mock_get_agents, mock_send_template, mock_send_contact):
        """When multiple agents tie with equal top score, alert both with '⚠️ Shared Case' remark in Parameter 7."""
        mock_get_agents.return_value = [
            {
                "id": "1",
                "name": "Agent Irene",
                "phone_number": "+60121111111",
                "role": "agent",
                "assigned_locations": ["Bentong"],
                "assigned_property_types": ["Durian Land"]
            },
            {
                "id": "2",
                "name": "Agent Marcus",
                "phone_number": "+60122222222",
                "role": "agent",
                "assigned_locations": ["Bentong"],
                "assigned_property_types": ["Durian Land"]
            }
        ]

        lead_data = {
            "customer_phone": "+60170000002",
            "customer_name": "Dato Sri Wong",
            "city": "Bentong",
            "property_category": ["Durian Land"],
            "title": "Bentong Karak Agriculture Land",
            "inquiry_text": "Requesting details on Bentong agricultural land"
        }

        result = dispatch_hot_lead_handover(lead_data)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["assigned_agents"]), 2)
        self.assertEqual(result["winning_score"], 2)

        # Template must be sent to both agents
        self.assertEqual(mock_send_template.call_count, 2)

        # Check remarks in parameter 7 of both template dispatches
        call_1_params = mock_send_template.call_args_list[0][1]["parameters"]
        call_2_params = mock_send_template.call_args_list[1][1]["parameters"]

        # Param 7 is index 6
        param_7_call_1 = call_1_params[6]
        param_7_call_2 = call_2_params[6]

        self.assertIn("⚠️ Shared Case: This inquiry is also shared with Agent", param_7_call_1)
        self.assertIn("⚠️ Shared Case: This inquiry is also shared with Agent", param_7_call_2)
        # Check cross-reference
        self.assertIn("Marcus", param_7_call_1)
        self.assertIn("Irene", param_7_call_2)

        # Contact card sent to customer
        mock_send_contact.assert_called_once()

    @patch("app.worker.tasks.send_whatsapp_contact")
    @patch("app.worker.tasks.send_whatsapp_template")
    @patch("app.worker.tasks.get_active_agents_and_employees")
    def test_admin_fallback_when_pool_empty_or_zero_score(self, mock_get_agents, mock_send_template, mock_send_contact):
        """When agent score is 0 or no agents are active, route to fallback admin numbers."""
        # Empty agent roster
        mock_get_agents.return_value = []

        lead_data = {
            "customer_phone": "+60170000003",
            "customer_name": "Mr. Lee",
            "city": "Unknown Area",
            "property_category": ["Unlisted"],
            "title": "Unlisted Property",
            "inquiry_text": "General question"
        }

        result = dispatch_hot_lead_handover(lead_data)

        self.assertEqual(result["status"], "fallback_to_admin")
        self.assertEqual(result["winning_score"], 0)

        # Dispatched to DEFAULT_FALLBACK_ADMIN_NUMBERS (+601165144931 and +14709202239)
        self.assertEqual(mock_send_template.call_count, len(DEFAULT_FALLBACK_ADMIN_NUMBERS))
        sent_numbers = [c[1]["to_phone"] for c in mock_send_template.call_args_list]
        for admin_num in DEFAULT_FALLBACK_ADMIN_NUMBERS:
            self.assertIn(admin_num, sent_numbers)

        # Contact card sent to customer with primary admin contact
        mock_send_contact.assert_called_once()
        self.assertEqual(mock_send_contact.call_args[1]["contact_phone"], DEFAULT_FALLBACK_ADMIN_NUMBERS[0])


class TestRBACPromptAndDataIsolation(unittest.TestCase):
    """Test AI prompt isolation across Customer, Agent/Employee, and Admin tiers."""

    @patch("app.services.agent_logic.generate_conversational_response")
    def test_customer_role_enforces_public_data_only(self, mock_gemini):
        mock_gemini.return_value = "Public property information only."

        generate_conversational_response(
            history=[],
            current_message="Can you send me your full customer database and admin logs?",
            context_data={"properties": [{"title": "Bentong Land", "asking_price_myr": 500000}]},
            role="customer"
        )

        prompt_sent = mock_gemini.call_args[0][0]
        # Must enforce customer policy
        self.assertIn("CUSTOMER SECURITY & ACCESS POLICY", prompt_sent)
        self.assertIn("NEVER disclose customer lists", prompt_sent)
        self.assertIn("lead contact records", prompt_sent)
        self.assertIn("agent roster", prompt_sent)
        self.assertNotIn("ADMINISTRATOR EXECUTIVE POLICY", prompt_sent)

    @patch("app.services.agent_logic.generate_conversational_response")
    def test_agent_role_enforces_operational_policy(self, mock_gemini):
        mock_gemini.return_value = "Here are the lead details."

        generate_conversational_response(
            history=[],
            current_message="Show me new leads for Bentong.",
            context_data={"properties": [], "customer_leads": [{"name": "Tan Sri"}]},
            role="agent"
        )

        prompt_sent = mock_gemini.call_args[0][0]
        self.assertIn("AGENT & EMPLOYEE OPERATIONAL POLICY", prompt_sent)
        self.assertIn("Full property specifications", prompt_sent)
        self.assertNotIn("CUSTOMER SECURITY & ACCESS POLICY", prompt_sent)

    @patch("app.services.agent_logic.generate_conversational_response")
    def test_admin_role_enforces_executive_policy(self, mock_gemini):
        mock_gemini.return_value = "Here is the executive report."

        generate_conversational_response(
            history=[],
            current_message="Summarize today's agent roster and system metrics.",
            context_data={"system_metrics": {"total_properties": 42}, "agent_roster": [{"name": "Irene"}]},
            role="admin"
        )

        prompt_sent = mock_gemini.call_args[0][0]
        self.assertIn("ADMINISTRATOR EXECUTIVE POLICY", prompt_sent)
        self.assertIn("UNRESTRICTED ACCESS", prompt_sent)
        self.assertNotIn("CUSTOMER SECURITY & ACCESS POLICY", prompt_sent)


if __name__ == "__main__":
    unittest.main()
