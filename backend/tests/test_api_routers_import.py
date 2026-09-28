"""
Smoke test to ensure FastAPI app and all router modules can be imported without NameError or missing dependency errors.
Guards against runtime startup crash in uvicorn.
"""

import unittest
import importlib

ROUTERS = [
    "app.main",
    "app.api.settings",
    "app.api.auth",
    "app.api.users",
    "app.api.admin",
    "app.api.customers",
    "app.api.properties",
    "app.api.webhooks",
    "app.api.wordpress",
    "app.api.transcripts",
    "app.api.acknowledgements",
    "app.api.documents",
]


class TestApiRoutersImport(unittest.TestCase):
    def test_all_routers_import_successfully(self):
        for mod in ROUTERS:
            with self.subTest(module=mod):
                m = importlib.import_module(mod)
                self.assertIsNotNone(m, f"Failed to import {mod}")

    def test_fastapi_app_object_exists(self):
        from app.main import app
        self.assertIsNotNone(app)
        self.assertEqual(app.title, "Real Estate WhatsApp AI CRM Orchestrator")


if __name__ == "__main__":
    unittest.main()
