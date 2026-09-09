"""
TDD Test Suite for Sprint 1: Security, Webhook Isolation, and Data Safety.
Follows strict RED-GREEN-REFACTOR cycle.
"""
import re
import unittest

class TestSprint1SecurityAndIsolation(unittest.TestCase):
    def test_reset_staging_customers_is_strictly_scoped(self):
        """
        P0-2: reset_staging_customers must NEVER delete all customers unconditionally.
        It must filter strictly by inbox_id = '3' (or test inbox).
        """
        with open("app/api/customers.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Extract the reset_staging_customers function block
        match = re.search(r"def reset_staging_customers\(.*?\):\n(.*?)(?=\n(?:def|@|\Z))", content, re.DOTALL)
        self.assertIsNotNone(match, "Could not find reset_staging_customers function")
        func_body = match.group(1)

        # Must NOT have unconditional delete()
        self.assertNotIn("db.query(Customer).delete()", func_body, 
                         "Security Hazard: reset_staging_customers still calls unconditional delete()!")
        # Must filter on inbox_id
        self.assertTrue("inbox_id" in func_body and "filter" in func_body,
                        "reset_staging_customers must filter by inbox_id before deleting!")

    def test_staging_drops_production_inbox_webhooks(self):
        """
        P0-3: Staging webhook must drop incoming messages for production inboxes (e.g. Inbox 3).
        """
        with open("app/api/webhooks.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Staging environment must explicitly drop production inboxes
        self.assertTrue("staging_ignores_production_inbox" in content or "ENVIRONMENT" in content and "inbox_id" in content,
                        "Staging environment must explicitly filter and drop production inboxes!")
        self.assertNotIn("# Removed strict inbox ID filtering so test/production inboxes both work", content,
                         "Webhooks.py still has comment disabling inbox filtering!")

    def test_chatwoot_hmac_signature_rejection_enforced(self):
        """
        P0-5: Invalid Chatwoot webhook signature must be rejected, not bypassed.
        """
        with open("app/api/webhooks.py", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("Bypassing signature validation for staging testing", content,
                         "Security Hazard: Webhook signature bypass is still active in webhooks.py!")

    def test_hardcoded_admin_password_removed(self):
        """
        P0-6: main.py must NOT contain fallback 'Admin12345!'.
        """
        with open("app/main.py", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("Admin12345!", content,
                         "Security Hazard: Hardcoded default admin password 'Admin12345!' still present in main.py!")

    def test_duplicate_country_attribute_removed(self):
        """
        P3-5 (Ponytail): Remove duplicate country attribute declarations in customers.py.
        """
        with open("app/api/customers.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Check CustomerCreate model for duplicate country
        match = re.search(r"class CustomerCreate\(.*?\):\n(.*?)(?=\nclass|\Z)", content, re.DOTALL)
        self.assertIsNotNone(match)
        create_body = match.group(1)
        country_count = len(re.findall(r"^\s+country\s*:", create_body, re.MULTILINE))
        self.assertEqual(country_count, 1, f"CustomerCreate has {country_count} 'country' attributes; should be 1!")

    def test_sql_migration_004_exists_and_contains_hnsw(self):
        """
        P1-2: 004_consolidated_hardening.sql must exist and create HNSW and GIN indexes.
        """
        import os
        migration_path = "migrations/004_consolidated_hardening.sql"
        self.assertTrue(os.path.exists(migration_path), "004_consolidated_hardening.sql migration file does not exist!")
        with open(migration_path, "r", encoding="utf-8") as f:
            sql = f.read()
        self.assertIn("USING hnsw (embedding_overview vector_cosine_ops)", sql)
        self.assertIn("USING GIN (property_category)", sql)
        self.assertIn("idx_customers_last_interaction", sql)

    def test_models_engine_pool_pre_ping_configured(self):
        """
        P1-4: models.py must configure pool_pre_ping and pool_recycle.
        """
        with open("app/db/models.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("pool_pre_ping=True", content, "Engine lacks pool_pre_ping=True in models.py!")
        self.assertIn("pool_recycle=", content, "Engine lacks pool_recycle in models.py!")

if __name__ == "__main__":
    unittest.main()
