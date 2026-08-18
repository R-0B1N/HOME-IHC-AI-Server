import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_services import find_matching_property, find_similar_properties
from app.services.agent_logic import process_persona_state_machine, is_valid_name, check_completeness

def test_is_valid_name():
    assert is_valid_name("Nick") is True
    assert is_valid_name("Chelsea Lee") is True
    assert is_valid_name("Dr. Ahmad") is True
    assert is_valid_name("+601165144931") is False
    assert is_valid_name("0123456789") is False
    assert is_valid_name("Unknown") is False
    assert is_valid_name("WhatsApp User") is False
    assert is_valid_name(".") is False
    assert is_valid_name("") is False
    assert is_valid_name(None) is False

def test_find_matching_property_real_db():
    # Test searching for Raub Taman Bukit Idaman
    prop = find_matching_property("can i get some information about Raub Taman Bukit Idaman 2-Storey Semi-D House For Sale")
    if prop:
        assert "Raub" in prop["title"] or "Bukit Idaman" in prop["title"]
        assert "price" in prop
        assert "image_urls" in prop

def test_find_similar_properties_real_db():
    similars = find_similar_properties(city="Raub", max_price=1000000, limit=3)
    assert isinstance(similars, list)
    if similars:
        for item in similars:
            assert item["status"] in ["Available", "For Sale", "For Rent"]

def test_conversational_state_machine_initial_property_mention():
    session = {"state": "INIT", "collected_data": {}}
    result = process_persona_state_machine(
        phone_number="+60123456789",
        text="can i get some information about Raub Taman Bukit Idaman 2-Storey Semi-D House For Sale",
        session=session,
        conversation_history="",
        contact_name="Nick"
    )
    
    assert result["handover"] is False
    assert "Home IHC" in result["response"]
    assert "ERA Realtor" not in result["response"]
    assert "Would you like to know more about it?" in result["response"]
    assert session.get("interested_property") is not None
    assert session["collected_data"].get("name") == "Nick"

def test_conversational_state_machine_photos_request():
    session = {
        "state": "IN_PROGRESS",
        "current_agent": "BUYER",
        "collected_data": {"name": "Nick"},
        "interested_property": {
            "title": "Raub Taman Bukit Idaman 2-Storey Semi-D House For Sale",
            "price": 800000,
            "city": "Raub",
            "image_urls": ["https://bentongland.com.my/sample1.jpg", "https://bentongland.com.my/sample2.jpg"],
            "status": "Available"
        }
    }
    result = process_persona_state_machine(
        phone_number="+60123456789",
        text="do you have some pictures for it",
        session=session,
        conversation_history="User: I want info on Raub Semi-D\nAI: Would you like to know more?",
        contact_name="Nick"
    )
    
    assert result["handover"] is False
    assert len(result.get("images_to_send", [])) > 0
    assert "photos" in result["response"].lower() or "pictures" in result["response"].lower() or "viewing" in result["response"].lower()

def test_conversational_state_machine_meeting_request():
    session = {
        "state": "IN_PROGRESS",
        "current_agent": "BUYER",
        "collected_data": {"name": "Nick"},
        "interested_property": {
            "title": "Raub Taman Bukit Idaman 2-Storey Semi-D House For Sale",
            "price": 800000,
            "status": "Available"
        }
    }
    result = process_persona_state_machine(
        phone_number="+60123456789",
        text="can we arrange a site visit this Saturday at 3pm?",
        session=session,
        conversation_history="User: do you have pictures\nAI: Here are photos",
        contact_name="Nick"
    )
    
    assert result["handover"] is True
    assert "Home IHC" in result["response"]
    assert "contact you shortly" in result["response"] or "confirm" in result["response"]
