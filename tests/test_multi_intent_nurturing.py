"""
Unit & Integration Tests for Multi-Intent Lead Nurturing & Meta Template Parameter Resolution.
Verifies Buyer, Seller, Landlord, Tenant, and Agent persona adaptation across:
1. HotCadenceStrategy, WarmCadenceStrategy, ColdCadenceStrategy
2. ReengagementTemplateDispatcher parameter mapping
3. Meta 24-hour compliance window guard
4. LeadNurturingManager evaluation and dispatch orchestration
"""

import sys
import os
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

# Ensure backend path is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.services.lead_nurturing import (
    HotCadenceStrategy,
    WarmCadenceStrategy,
    ColdCadenceStrategy,
    MetaPolicyWindowGuard,
    ReengagementTemplateDispatcher,
    LeadNurturingManager,
)


def test_cadence_message_generation_per_intent():
    """Verify that all strategies generate persona-tailored conversational messages."""
    hot = HotCadenceStrategy()
    warm = WarmCadenceStrategy()
    cold = ColdCadenceStrategy()

    intents = ["buyer", "seller", "landowner", "landlord", "tenant", "agent"]

    for intent in intents:
        msg_hot = hot.get_message_content("Nick", "Bentong", intent=intent)
        msg_warm = warm.get_message_content("Nick", "Bentong", intent=intent)
        msg_cold = cold.get_message_content("Nick", "Bentong", intent=intent)

        assert "Nick" in msg_hot
        assert "Nick" in msg_warm
        assert "Nick" in msg_cold

        if intent in ["seller", "landowner"]:
            assert "valuation" in msg_hot.lower() or "price" in msg_hot.lower()
            assert "sell" in msg_warm.lower() or "buyers" in msg_warm.lower()
            assert "valuation" in msg_cold.lower() or "sale marketing" in msg_cold.lower()

        elif intent == "landlord":
            assert "rental property" in msg_hot.lower() or "tenants" in msg_hot.lower()
            assert "tenant" in msg_warm.lower()
            assert "tenancy" in msg_cold.lower()

        elif intent == "tenant":
            assert "rental search" in msg_hot.lower() or "rent" in msg_hot.lower()
            assert "rental" in msg_warm.lower()
            assert "tenancy" in msg_cold.lower()

        elif intent == "agent":
            assert "co-agency" in msg_hot.lower() or "co-broke" in msg_hot.lower()
            assert "co-agency" in msg_warm.lower() or "collaborate" in msg_warm.lower()
            assert "co-broke" in msg_cold.lower() or "joint agency" in msg_cold.lower()

        elif intent == "buyer":
            assert "viewing" in msg_hot.lower() or "properties" in msg_hot.lower()
            assert "listings" in msg_warm.lower()
            assert "land" in msg_cold.lower() or "residential" in msg_cold.lower()

    print("✅ All intent-tailored cadence messages passed assertion checks.")


def test_reengagement_template_dispatcher_parameter_mapping():
    """Verify that ReengagementTemplateDispatcher formats variable {{2}} properly for all intents."""
    dispatcher = ReengagementTemplateDispatcher()

    # Test context phrase resolution
    buyer_phrase = dispatcher.resolve_context_phrase("buyer", "Raub")
    assert buyer_phrase == "property search in Raub"

    seller_phrase = dispatcher.resolve_context_phrase("seller", "Mukim Bentong")
    assert seller_phrase == "property listing & valuation in Mukim Bentong"

    landowner_phrase = dispatcher.resolve_context_phrase("landowner", "Karak")
    assert landowner_phrase == "land listing & valuation in Karak"

    landlord_phrase = dispatcher.resolve_context_phrase("landlord", "Bentong Town")
    assert landlord_phrase == "rental property listing in Bentong Town"

    tenant_phrase = dispatcher.resolve_context_phrase("tenant", "Mentakab")
    assert tenant_phrase == "rental search in Mentakab"

    agent_phrase = dispatcher.resolve_context_phrase("agent", "Pahang")
    assert agent_phrase == "co-agency collaboration in Pahang"

    # Test dispatch mock
    mock_send = MagicMock(return_value={"messages": [{"id": "wamid.test"}]})
    import app.services.lead_nurturing as ln_module
    original_send = ln_module.send_whatsapp_template
    ln_module.send_whatsapp_template = mock_send

    try:
        res = dispatcher.dispatch(
            to_phone="+601165144931",
            customer_name="Mr. Lee",
            location="Bentong",
            template_name="lead_reengagement_utility",
            intent="seller"
        )
        assert res["status"] == "success"
        assert res["parameters"] == ["Mr. Lee", "property listing & valuation in Bentong"]
        mock_send.assert_called_once()
    finally:
        ln_module.send_whatsapp_template = original_send

    print("✅ Template dispatcher multi-intent parameter bindings passed.")


def test_meta_policy_window_guard():
    """Verify that 24h compliance boundary strictly switches between free-form and template."""
    assert MetaPolicyWindowGuard.is_within_24h(0.5) is True
    assert MetaPolicyWindowGuard.is_within_24h(23.9) is True
    assert MetaPolicyWindowGuard.is_within_24h(24.0) is True
    assert MetaPolicyWindowGuard.is_within_24h(24.1) is False
    assert MetaPolicyWindowGuard.is_within_24h(72.0) is False
    print("✅ Meta 24-hour compliance window guard passed.")


def test_lead_nurturing_manager_evaluation():
    """Verify manager correctly parses customer intent and routes within vs outside 24h window."""
    mock_customer = MagicMock()
    mock_customer.id = "+60128767882"
    mock_customer.contact_name = "Shukri Ahmad"
    mock_customer.conversation_ids = [401]
    mock_customer.intent_category = "seller"
    now = datetime.now(timezone.utc)
    mock_customer.last_interaction = now - timedelta(hours=2)  # within 24h
    mock_customer.metadata_json = {
        "lead_temp": "hot",
        "collected_data": {"location": "Bentong"},
        "requirements_profile": {"active_inquiry": {"intent": "seller"}}
    }

    mock_msg_sender = MagicMock()
    mock_note_sender = MagicMock()
    mock_dispatcher = MagicMock()

    manager = LeadNurturingManager(
        message_sender=mock_msg_sender,
        note_sender=mock_note_sender,
        template_dispatcher=mock_dispatcher,
        is_staging=True
    )

    # 1. Evaluation within 24h (staging acceleration)
    eval_res = manager.evaluate_customer(mock_customer, now=now, force_due=True)
    assert eval_res is not None
    assert eval_res["intent"] == "seller"
    assert eval_res["is_within_24h"] is True
    assert "valuation" in eval_res["message_text"].lower() or "price" in eval_res["message_text"].lower()

    # 2. Dispatch within 24h
    action = manager.dispatch_nurture(mock_customer, eval_res, now=now)
    assert action == "message_sent"
    mock_msg_sender.assert_called_once_with(401, eval_res["message_text"])

    # 3. Simulate > 24 hours inactive (outside window)
    mock_customer.last_interaction = now - timedelta(hours=36)
    eval_res_outside = manager.evaluate_customer(mock_customer, now=now, force_due=True)
    assert eval_res_outside["is_within_24h"] is False

    mock_dispatcher.dispatch.return_value = {"status": "success"}
    action_outside = manager.dispatch_nurture(mock_customer, eval_res_outside, now=now)
    assert action_outside in ["template_dispatched", "private_note_posted"]
    mock_dispatcher.dispatch.assert_called_once_with(
        to_phone="+60128767882",
        customer_name="Shukri Ahmad",
        location="Bentong",
        template_name="lead_reengagement_utility",
        intent="seller"
    )
    # Note sender was called with private note documenting intent
    mock_note_sender.assert_called_once()
    assert "SELLER" in mock_note_sender.call_args[0][1]

    print("✅ LeadNurturingManager full lifecycle and intent routing passed.")


if __name__ == "__main__":
    test_cadence_message_generation_per_intent()
    test_reengagement_template_dispatcher_parameter_mapping()
    test_meta_policy_window_guard()
    test_lead_nurturing_manager_evaluation()
    print("\n🎉 ALL MULTI-INTENT NURTURING TESTS PASSED SUCCESSFULLY!")
