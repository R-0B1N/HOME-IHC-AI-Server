"""Recategorization rules, local-LLM fallback, dry-run, apply, and admin auth."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.recategorize import router as recategorize_router
from app.core.security import generate_report_download_token
from app.services.classification_config import backfill_lock_allows_override
from app.services.customer_classification import (
    canonical_category_name,
    classify_customer_messages,
    classify_transcript,
    enforce_classification_lock,
    explicit_role_from_statement,
    mask_phone,
    reconcile_rule_and_llm,
)
from app.services.recategorize_service import (
    CSV_COLUMNS,
    MemoryJobStore,
    ReadOnlyViolation,
    assert_sql_is_read_only,
    chatwoot_read,
    execute_apply,
    execute_dry_run,
    execute_rollback,
    merge_labels,
    paginate_messages,
)


def _incoming(text, message_id, attachments=None, document_extract=None):
    message = {"id": message_id, "message_type": 0, "private": False, "content": text}
    if attachments is not None:
        message["attachments"] = attachments
    if document_extract is not None:
        message["document_extract"] = document_extract
    return message


def _customer(phone, name, conv_ids, metadata):
    return SimpleNamespace(
        id=phone,
        contact_name=name,
        conversation_ids=list(conv_ids),
        metadata_json=dict(metadata),
    )


class CanonicalRoleTests(unittest.TestCase):
    def test_all_six_categories_and_renter_maps_to_tenant(self):
        cases = {
            "seller": "I want to sell my land in Bentong, asking price is RM 500,000",
            "buyer": "I want to buy a house in Bentong, my budget is RM 400,000",
            "agent": "I am a property agent",
            "tenant": "I want to rent a house in Raub, rent budget RM 1500",
            "landlord": "I want to rent out my shop in Bentong, asking rent is RM 2000",
            "uncertain": "hello there",
        }
        for expected, text in cases.items():
            result = classify_customer_messages([text])
            self.assertEqual(result["category"], expected, text)
        landlord = classify_customer_messages(["nak sewakan rumah saya"])
        self.assertEqual(landlord["category"], "landlord")
        self.assertNotIn(landlord["category"], {"tenant", "seller"})
        self.assertEqual(canonical_category_name("renter"), "tenant")
        self.assertEqual(canonical_category_name("landlord"), "landlord")

    def test_listing_question_and_photo_are_not_seller(self):
        listing = classify_customer_messages(["is it for rent?"])
        self.assertEqual(listing["category"], "uncertain")
        self.assertIsNone(explicit_role_from_statement("is it for rent?"))
        photo = classify_customer_messages([_incoming("", 1, attachments=[{"file_type": "image"}])])
        self.assertEqual(photo["category"], "uncertain")
        self.assertEqual(photo["reason"], "photo_only_not_seller")

    def test_agent_beats_buyer(self):
        both = classify_customer_messages(["I am a property agent", "I want to buy land in Raub"])
        self.assertEqual(both["category"], "agent")
        self.assertEqual(both["reason"], "agent_beats_buyer")

    def test_rule_first_skips_llm_and_fallback_uses_it(self):
        called = []

        def llm(texts):
            called.append(list(texts))
            return "landlord"

        ruled = classify_transcript(["I want to sell my land in Bentong"], llm_classify=llm)
        self.assertEqual(ruled["category"], "seller")
        self.assertEqual(ruled["decided_by"], "rules")
        self.assertEqual(called, [])

        fallback = classify_transcript(["hello"], llm_classify=llm)
        self.assertEqual(fallback["category"], "landlord")
        self.assertEqual(fallback["decided_by"], "llm")
        self.assertEqual(len(called), 1)

    def test_disagreement_is_uncertain(self):
        result = reconcile_rule_and_llm(
            {"category": "buyer", "confidence": "low", "evidence_quote": "buy", "reason": "guess"},
            "seller",
            ["I want to buy"],
        )
        self.assertEqual(result["category"], "uncertain")
        self.assertEqual(result["reason"], "rule_llm_disagreement")
        self.assertEqual(mask_phone("+60123456789"), "*******6789")


class LockOverrideTests(unittest.TestCase):
    def _locked(self, role, text):
        return {
            "classification_locked": True,
            "locked_category": role,
            "classification_source": "backfill",
            "last_customer_text": text,
            "collected_data": {},
            "current_agent": role.upper(),
        }

    def test_explicit_statement_records_previous_role(self):
        session = self._locked("buyer", "I want to rent out my shop")
        outcome = enforce_classification_lock(session)
        self.assertEqual(outcome["action"], "override")
        self.assertEqual(outcome["category"], "landlord")
        self.assertEqual(outcome["previous_role"], "buyer")
        self.assertEqual(outcome["previous_role_source"], "backfill")
        self.assertIn("T", outcome["previous_role_at"])
        self.assertNotEqual(outcome["category"], "tenant")

    def test_photo_does_not_override(self):
        session = self._locked("buyer", "")
        session["current_agent"] = "SELLER"
        outcome = enforce_classification_lock(session)
        self.assertEqual(outcome["action"], "keep")
        self.assertEqual(session["current_agent"], "BUYER")

    def test_flag_off_queues(self):
        session = self._locked("buyer", "I want to sell my land")
        with patch.dict(os.environ, {"BACKFILL_LOCK_ALLOW_OVERRIDE": "0"}):
            self.assertFalse(backfill_lock_allows_override())
            outcome = enforce_classification_lock(session)
        self.assertEqual(outcome["action"], "queue_for_review")
        self.assertNotIn("previous_role", session)

    def test_default_allows_override(self):
        os.environ.pop("BACKFILL_LOCK_ALLOW_OVERRIDE", None)
        self.assertTrue(backfill_lock_allows_override())


class DryRunAndApplyTests(unittest.TestCase):
    def _run(self, directory, customers, fetch_page, llm):
        store = MemoryJobStore()
        job = store.create_job(
            output_csv=os.path.join(directory, "batch.csv"),
            output_xlsx=os.path.join(directory, "batch.xlsx"),
        )
        outcome = execute_dry_run(
            customers=customers,
            fetch_page=fetch_page,
            fetch_details=lambda conversation_id: {"labels": ["human-handover", "buyer", "hot"]},
            store=store,
            batch_id=job["batch_id"],
            llm_classify=llm,
        )
        return store, job, outcome

    def test_dry_run_writes_files_and_no_side_effects(self):
        pages = {
            None: [_incoming("hello", message_id) for message_id in range(120, 100, -1)],
            101: [_incoming("I want to sell my land in Bentong, asking price is RM 500,000", 80)],
        }

        def fetch_page(conversation_id, before):
            return pages.get(before, [])

        customer = _customer("+60111222333", "Mei", [9], {"intent_category": "buyer", "classification_source": "manual"})
        silent = _customer("+60199888777", "No Thread", [], {"intent": "seller"})
        with patch("app.services.chatwoot.apply_label") as labels, \
                patch("app.services.chatwoot.assign_agent") as assign, \
                patch("app.services.chatwoot.send_message") as send:
            with tempfile.TemporaryDirectory() as directory:
                store, job, outcome = self._run(directory, [customer, silent], fetch_page, llm=lambda texts: "tenant")
                self.assertTrue(os.path.exists(outcome["output_csv"]))
                self.assertTrue(os.path.exists(outcome["output_xlsx"]))
                saved = {row["contact"]: row for row in outcome["rows"]}
                self.assertEqual(saved["Mei"]["proposed_category"], "seller")
                self.assertEqual(saved["Mei"]["previous_role"], "buyer")
                self.assertEqual(saved["Mei"]["previous_role_at"], "")
                self.assertEqual(saved["Mei"]["decided_by"], "rules")
                self.assertEqual(saved["No Thread"]["reason"], "no_transcript")
                with open(outcome["output_csv"], encoding="utf-8") as handle:
                    header = handle.readline().strip().split(",")
                self.assertEqual(header, CSV_COLUMNS)
            labels.assert_not_called()
            assign.assert_not_called()
            send.assert_not_called()
        with self.assertRaises(ReadOnlyViolation):
            chatwoot_read("POST", "http://chatwoot.example/labels")
        with self.assertRaises(ReadOnlyViolation):
            chatwoot_read("PUT", "http://chatwoot.example/x")
        with self.assertRaises(ReadOnlyViolation):
            chatwoot_read("PATCH", "http://chatwoot.example/x")
        with self.assertRaises(ReadOnlyViolation):
            chatwoot_read("DELETE", "http://chatwoot.example/x")
        assert_sql_is_read_only("SELECT id FROM customers")
        assert_sql_is_read_only("SET TRANSACTION READ ONLY")
        with self.assertRaises(ReadOnlyViolation):
            assert_sql_is_read_only("UPDATE customers SET metadata_json = '{}'")

    def test_resume_skips_checkpointed_conversations(self):
        def fetch_page(conversation_id, before):
            return [_incoming("I want to buy a house in Raub, my budget is RM 200000", 1)] if before is None else []

        customers = [
            _customer("60100000001", "A", [1], {}),
            _customer("60100000002", "B", [2], {}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryJobStore()
            job = store.create_job(
                output_csv=os.path.join(directory, "resume.csv"),
                output_xlsx=os.path.join(directory, "resume.xlsx"),
            )
            first = execute_dry_run(
                customers=customers,
                fetch_page=fetch_page,
                fetch_details=lambda conversation_id: {},
                store=store,
                batch_id=job["batch_id"],
                llm_classify=lambda texts: "uncertain",
                limit=1,
            )
            self.assertEqual(len(first["rows"]), 1)
            second = execute_dry_run(
                customers=customers,
                fetch_page=fetch_page,
                fetch_details=lambda conversation_id: {},
                store=store,
                batch_id=job["batch_id"],
                llm_classify=lambda texts: "uncertain",
                resume=True,
            )
            self.assertEqual([row["conversation_id"] for row in second["rows"]], ["2"])

    def test_apply_snapshots_merges_and_rolls_back_idempotently(self):
        customer = _customer("60123450000", "Lee", [42], {"intent_category": "buyer", "classification_source": "manual", "lead_temp": "Warm"})
        saved = {}
        resets = []
        writes = []

        def save(person):
            saved[person.id] = dict(person.metadata_json)

        def write_labels(conversation_id, labels):
            writes.append((str(conversation_id), list(labels)))

        def reset(phone):
            resets.append(phone)

        with tempfile.TemporaryDirectory() as directory:
            store, job, _outcome = self._run(
                directory,
                [customer],
                lambda conversation_id, before: [_incoming("I want to sell my land in Bentong, asking price is RM 500,000", 3)] if before is None else [],
                llm=lambda texts: "tenant",
            )
            merged = merge_labels(["human-handover", "buyer", "hot"], "seller", "hot")
            self.assertEqual(merged, ["human-handover", "seller", "hot"])
            self.assertIn("landlord", merge_labels(["vip"], "landlord", "warm"))
            self.assertNotIn("buyer", merge_labels(["buyer", "vip"], "landlord", "warm"))

            first = execute_apply(
                store=store,
                batch_id=job["batch_id"],
                accepted_conversation_ids=["42"],
                customers=[customer],
                read_labels=lambda conversation_id: ["human-handover", "buyer", "hot"],
                write_labels=write_labels,
                save_customer=save,
                reset_session=reset,
            )
            self.assertEqual(first["applied"], ["42"])
            self.assertEqual(saved["60123450000"]["intent_category"], "seller")
            self.assertEqual(saved["60123450000"]["previous_role"], "buyer")
            self.assertEqual(saved["60123450000"]["previous_role_source"], "manual")
            self.assertTrue(saved["60123450000"]["classification_locked"])
            self.assertEqual(saved["60123450000"]["classification_batch"], job["batch_id"])
            self.assertEqual(writes[-1][1], ["human-handover", "seller", "hot"])
            self.assertEqual(resets, ["60123450000"])
            snap = store.get_snapshot(job["batch_id"], "42")
            self.assertEqual(snap["previous_metadata"]["intent_category"], "buyer")
            self.assertEqual(snap["previous_labels"], ["human-handover", "buyer", "hot"])

            again = execute_apply(
                store=store,
                batch_id=job["batch_id"],
                accepted_conversation_ids=["42"],
                customers=[customer],
                read_labels=lambda conversation_id: ["human-handover", "seller", "hot"],
                write_labels=write_labels,
                save_customer=save,
                reset_session=reset,
            )
            self.assertEqual(again["skipped"][0]["reason"], "already_applied")
            self.assertEqual(len(writes), 1)

            customer.metadata_json = dict(saved["60123450000"])
            rolled = execute_rollback(
                store=store,
                batch_id=job["batch_id"],
                customers=[customer],
                write_labels=write_labels,
                save_customer=save,
                reset_session=reset,
            )
            self.assertEqual(rolled["restored"], ["42"])
            self.assertEqual(saved["60123450000"]["intent_category"], "buyer")
            self.assertNotIn("classification_locked", saved["60123450000"])
            self.assertEqual(writes[-1][1], ["human-handover", "buyer", "hot"])

    def test_pagination_does_not_loop(self):
        def fetch_page(conversation_id, before):
            return [_incoming("hello", 5)]

        self.assertEqual(len(list(paginate_messages(1, fetch_page, page_size=1))), 1)


class AdminEndpointTests(unittest.TestCase):
    def test_start_and_download_require_admin_or_hmac(self):
        app = FastAPI()
        app.include_router(recategorize_router, prefix="/api/v1/recategorize")
        client = TestClient(app)
        denied = client.post("/api/v1/recategorize/jobs", json={"mode": "dry_run"})
        self.assertEqual(denied.status_code, 401)
        missing = client.get("/api/v1/recategorize/jobs/abc/download")
        self.assertEqual(missing.status_code, 401)

        token = generate_report_download_token("recategorize", "batch-hmac")
        with tempfile.TemporaryDirectory() as directory:
            csv_path = os.path.join(directory, "batch-hmac.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("conversation_id\n1\n")
            fake_job = {
                "batch_id": "batch-hmac",
                "output_csv": csv_path,
                "output_xlsx": csv_path,
            }
            with patch("app.api.recategorize._store") as store_factory:
                store = store_factory.return_value
                store.get_job.return_value = fake_job
                response = client.get(
                    "/api/v1/recategorize/jobs/batch-hmac/download",
                    params={"token": token},
                )
            self.assertEqual(response.status_code, 200)
            self.assertIn("conversation_id", response.text)


if __name__ == "__main__":
    unittest.main()
