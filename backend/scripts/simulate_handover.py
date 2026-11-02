#!/usr/bin/env python3
"""
CLI Script to simulate hot lead handover template dispatch strictly to admin numbers.
Usage:
    python scripts/simulate_handover.py
"""
import os
import sys

# Ensure backend root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.services.lead_handover import LeadHandoverService


def main():
    print("================================================================================")
    print("         HOME IHC - HANDOVER SIMULATION (ADMIN NUMBERS ONLY)                    ")
    print("================================================================================")
    service = LeadHandoverService()
    admin_list = service.get_admin_recipients()
    print(f"Target Admin Numbers: {[a['phone'] for a in admin_list]}\n")

    test_lead = {
        "conversation_id": 202,
        "customer_name": "[TEST] Admin Verification Lead",
        "customer_phone": "",  # Empty: No customer contact card dispatched
        "intent": "TENANT",
        "city": "Bentong",
        "property_category": ["Rental / Commercial"],
        "budget": "RM 2,500 / month",
        "title": "Bentong Rental Inquiry (Simulation)",
        "inquiry_text": "🧪 Verification Test: Testing Meta Template 'new_lead_alert_utility' to Admin oversight line.",
        "admin_only": True,
    }

    print("Dispatching handover simulation via Meta WhatsApp Cloud API...")
    result = service.dispatch(test_lead, admin_only=True)
    print("\nResult:")
    print(f"Status: {result.get('status')}")
    print(f"Routed To: {result.get('routed_to')}")
    print(f"Winning Score: {result.get('winning_score')}")
    print("================================================================================")


if __name__ == "__main__":
    main()

