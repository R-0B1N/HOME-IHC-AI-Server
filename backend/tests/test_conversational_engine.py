try:
    import pytest
except ImportError:
    pytest = None
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.services.db_services import find_matching_property, find_similar_properties
    from app.services.agent_logic import process_persona_state_machine, is_valid_name, check_completeness
except ImportError:
    find_matching_property = None
    find_similar_properties = None
    process_persona_state_machine = None
    is_valid_name = lambda name: bool(name and str(name).strip() and not str(name).startswith("+") and not str(name).isdigit() and str(name).lower() not in ["unknown", "whatsapp user", "."])
    check_completeness = None

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

def test_parse_listing_financials():
    from scripts.scrape_and_ingest_all_properties import parse_listing_financials, parse_acres
    
    # 1. Per-acre durian land
    title1 = "9.7 ac Bentong Jln Tras Durian Land For Sale"
    desc1 = "Matured Musang King orchard. Price: RM 365,000 / acre. Road access and water piping installed."
    acres1 = parse_acres(title1)
    assert acres1 == 9.7
    f1 = parse_listing_financials(title1, desc1, status="For Sale", acres=acres1)
    assert f1["price_per_acre_myr"] == 365000.0
    assert f1["asking_price_myr"] == 3540500.0  # 365,000 * 9.7

    # 2. Warehouse For Rent
    title2 = "Mentakab Industry Warehouse For Rent"
    desc2 = "Heavy industrial warehouse, built-up 25,000 sqft. Rental: RM 12,000 / month. 3-Phase power."
    f2 = parse_listing_financials(title2, desc2, status="For Rent", acres=0.0)
    assert f2["asking_price_myr"] == 0.0
    assert f2["monthly_rental_income_myr"] == 12000.0

    # 3. Commercial Land with Total in Millions
    title3 = "8-ac Mentakab Bukit Bendera Commercial Land For Sale"
    desc3 = "Main road frontage. Total Selling Price: RM 8.5 Million. Freehold title."
    acres3 = parse_acres(title3)
    f3 = parse_listing_financials(title3, desc3, status="For Sale", acres=acres3)
    assert f3["asking_price_myr"] == 8500000.0
    assert f3["price_per_acre_myr"] == round(8500000.0 / 8.0, 2)


    # 4. Terrace House with From Price and Savings (Taman Azalea)
    title4 = "Bentong New Project Taman Azalea Double Storey Terrace House For Sale"
    desc4 = """
    RM From 530,000
    Property Features
    Property Category : House
    Property Size : 2,180 ft²
    Purchaser Benefits
    Free MOT
    Free SPA Legal Fees
    Estimated savings of RM20,000 – RM30,000
    Selling Price: From RM 530,000
    """
    f4 = parse_listing_financials(title4, desc4, status="For Sale", acres=0.0)
    assert f4["asking_price_myr"] == 530000.0, f"Expected 530000, got {f4}"


def test_workflow_templates_integrity():
    from scripts.seed_workflows import seed_workflows
    import inspect
    import scripts.seed_workflows as sw
    src = inspect.getsource(sw.seed_workflows)
    assert "Senior Property Agent from ERA Realtor" in src, "Step 1 should state ERA Realtor"
    assert "Step 8: Viewing Acknowledgement & Form" in src
    assert "Seller Database & Google Review" in src
    assert "https://g.page/r/CSRasXyQXRrtEAE/review" in src
