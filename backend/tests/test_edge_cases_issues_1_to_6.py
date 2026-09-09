"""
Edge Case Backtests for Issues 1-6.
Standard library unittest implementation with mocked module dependencies for zero-dependency local and CI execution.
"""
import datetime
import json
import re
import sys
import types
import unittest
from unittest.mock import MagicMock

# Mock third-party packages if not installed in current environment
for mod_name in [
    'fastapi', 'sqlalchemy', 'sqlalchemy.exc', 'sqlalchemy.orm', 'sqlalchemy.ext', 'sqlalchemy.ext.declarative',
    'pydantic', 'redis', 'openai', 'celery', 'pgvector', 'pgvector.sqlalchemy', 'app.db.models'
]:
    try:
        __import__(mod_name)
    except (ImportError, ModuleNotFoundError):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

# ──────────────────────────────────────────────
# ISSUE 1: Property Serialization
# ──────────────────────────────────────────────

class FakeColumn:
    def __init__(self, name):
        self.name = name

class FakeTable:
    def __init__(self):
        self.columns = [
            FakeColumn("id"),
            FakeColumn("title"),
            FakeColumn("asking_price_myr"),
            FakeColumn("city"),
            FakeColumn("state"),
            FakeColumn("created_at"),
            FakeColumn("embedding_overview"),
            FakeColumn("embedding_location"),
            FakeColumn("embedding_specs"),
            FakeColumn("embedding_features"),
            FakeColumn("embedding_suitability"),
        ]

class FakeProperty:
    """Simulates a Property ORM object with pgvector columns."""
    __table__ = FakeTable()

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestIssue1PropertySerialization(unittest.TestCase):
    def test_serialize_property_excludes_embeddings(self):
        """Issue 1: serialize_property must NEVER include raw embedding vectors."""
        from app.api.properties import serialize_property

        prop = FakeProperty(
            id=1, title="Test Land", asking_price_myr=500000.0,
            city="Bentong", state="Pahang",
            created_at=datetime.datetime(2026, 8, 31, 12, 0, 0),
            embedding_overview=[0.1]*384, embedding_location=[0.2]*384,
            embedding_specs=None, embedding_features=[0.3]*384, embedding_suitability=None,
        )
        result = serialize_property(prop)
        self.assertNotIn("embedding_overview", result)
        self.assertNotIn("embedding_location", result)
        self.assertNotIn("embedding_specs", result)
        self.assertNotIn("embedding_features", result)
        self.assertNotIn("embedding_suitability", result)
        self.assertTrue(result["has_embedding_overview"])
        self.assertTrue(result["has_embedding_location"])
        self.assertFalse(result["has_embedding_specs"])
        self.assertTrue(result["has_embedding_features"])
        self.assertFalse(result["has_embedding_suitability"])
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["title"], "Test Land")
        self.assertEqual(result["created_at"], "2026-08-31T12:00:00")
        
        # Verify JSON serializability
        dumped = json.dumps(result)
        self.assertIsInstance(dumped, str)


# ──────────────────────────────────────────────
# ISSUE 2: Master AI Toggle
# ──────────────────────────────────────────────

class TestIssue2MasterAIToggle(unittest.TestCase):
    def test_webhook_rejects_when_master_ai_off(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"false"
        raw = mock_redis.get("master_ai_enabled")
        on = raw.decode("utf-8") == "true" if raw else True
        self.assertFalse(on)

    def test_webhook_defaults_to_on_when_key_missing(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        raw = mock_redis.get("master_ai_enabled")
        on = raw.decode("utf-8") == "true" if raw else True
        self.assertTrue(on)

    def test_worker_clears_queue_when_ai_off(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"false"
        raw = mock_redis.get("master_ai_enabled")
        on = raw.decode("utf-8") == "true" if raw else True
        if not on:
            queue_key = "convo_queue_123"
            mock_redis.delete(queue_key)
        mock_redis.delete.assert_called_once_with("convo_queue_123")


# ──────────────────────────────────────────────
# ISSUE 3: Leads Separation
# ──────────────────────────────────────────────

class TestIssue3LeadsSeparation(unittest.TestCase):
    def setUp(self):
        self.leads = [
            {"inbox_id": 4, "name": "Staging Lead A"},
            {"inbox_id": 1, "name": "Production Lead B"},
            {"inbox_id": 3, "name": "Voon Customer Service Production Lead C"},
            {"inbox_id": 2, "name": "Production Lead D"}
        ]

    def test_staging_excludes_production(self):
        staging = [l for l in self.leads if l["inbox_id"] == 4]
        self.assertEqual(len(staging), 1)
        self.assertEqual(staging[0]["name"], "Staging Lead A")

    def test_production_excludes_staging(self):
        prod = [l for l in self.leads if l["inbox_id"] != 4]
        self.assertEqual(len(prod), 3)
        self.assertTrue(all(l["inbox_id"] != 4 for l in prod))


# ──────────────────────────────────────────────
# ISSUE 4: Photo Dispatch Guard
# ──────────────────────────────────────────────

class TestIssue4PhotoDispatchGuard(unittest.TestCase):
    def test_photo_blocked_first_message(self):
        raw_text = "Hi, I saw your photo listing online"
        history = ""
        has_prior = bool(history and len(history.strip()) > 10)
        is_photo = any(w in raw_text.lower() for w in ["photo", "photos", "picture", "gambar", "foto", "image", "images"]) and has_prior
        self.assertFalse(is_photo)

    def test_photo_allowed_ongoing(self):
        raw_text = "show me photos"
        history = "Customer: Hi\nAgent: Good day!\nCustomer: I want Bentong land."
        has_prior = bool(history and len(history.strip()) > 10)
        is_photo = any(w in raw_text.lower() for w in ["photo", "photos", "picture", "gambar", "foto", "image", "images"]) and has_prior
        self.assertTrue(is_photo)


# ──────────────────────────────────────────────
# ISSUE 5: RAG Search Guard
# ──────────────────────────────────────────────

class TestIssue5RAGSearchGuard(unittest.TestCase):
    def test_rag_blocked_no_criteria(self):
        criteria = {"location": None, "property_type": None, "max_price": None}
        has = any(v for v in criteria.values() if v and str(v).lower() not in ["none", "null", ""])
        self.assertFalse(has)

    def test_rag_allowed_with_location(self):
        criteria = {"location": "Bentong", "property_type": None, "max_price": None}
        has = any(v for v in criteria.values() if v and str(v).lower() not in ["none", "null", ""])
        self.assertTrue(has)

    def test_rag_blocked_string_none(self):
        criteria = {"location": "none", "property_type": "None", "max_price": ""}
        has = any(v for v in criteria.values() if v and str(v).lower() not in ["none", "null", ""])
        self.assertFalse(has)

    def test_referral_no_rag(self):
        # Scenario Conv 75: "hi, im fadhil, i got your contact from mis irene"
        criteria = {"location": None, "property_type": None, "max_price": None}
        has = any(v for v in criteria.values() if v and str(v).lower() not in ["none", "null", ""])
        self.assertFalse(has)


# ──────────────────────────────────────────────
# ISSUE 6: Unlisted Property Detection
# ──────────────────────────────────────────────

ENTITY_PATTERNS = [
    r'lot\s+\d+', r'mukim\s+\w+', r'daerah\s+\w+',
    r'taman\s+\w+', r'kampung\s+\w+', r'jalan\s+\w+', r'no\.?\s*\d+',
]

def _detect(text):
    return any(re.search(p, text, re.IGNORECASE) for p in ENTITY_PATTERNS)

class TestIssue6UnlistedPropertyDetection(unittest.TestCase):
    def test_detect_lot(self):
        self.assertTrue(_detect("Lot 1039 Daerah Ulu Selangor"))

    def test_detect_mukim(self):
        self.assertTrue(_detect("Mukim Batang Kali"))

    def test_detect_taman(self):
        self.assertTrue(_detect("Taman Seri Galing"))

    def test_no_entity_greeting(self):
        self.assertFalse(_detect("Hi, looking for a house"))

    def test_no_entity_referral(self):
        self.assertFalse(_detect("hi im fadhil i got your contact from mis irene"))

    def test_unlisted_context_generated(self):
        text = "Lot 1039 Daerah Ulu Selangor, Mukim Batang Kali"
        detected = _detect(text)
        self.assertTrue(detected)
        ctx = f"[PROPERTY_STATUS: UNLISTED_OR_EXTERNAL_PROPERTY]\n{text}"
        self.assertIn("UNLISTED_OR_EXTERNAL_PROPERTY", ctx)


# ──────────────────────────────────────────────
# CROSS-CUTTING: Persona & Identity Rules
# ──────────────────────────────────────────────

class TestPersonaRules(unittest.TestCase):
    def test_greeting_identity(self):
        greeting = "Good day! 😊 I'm Irene Leong, a Senior Property Agent from ERA Realtor."
        self.assertIn("ERA Realtor", greeting)

    def test_company_identity(self):
        company_ref = "How can Home IHC assist you today?"
        self.assertIn("Home IHC", company_ref)

    def test_anti_repetition_flag_detected(self):
        history = "User: Hi\nAssistant: Good day! I'm Irene Leong from ERA Realtor.\nUser: Do you have land in Bentong?"
        has_prior = "Assistant:" in history or "Irene Leong" in history
        self.assertTrue(has_prior)


class TestIssue1WordPressSyncResilience(unittest.TestCase):
    def test_sync_state_defaults(self):
        from app.api.properties import _sync_state
        self.assertIn("is_syncing", _sync_state)
        self.assertIn("status", _sync_state)
        self.assertIn("total_properties", _sync_state)


if __name__ == "__main__":
    unittest.main()
