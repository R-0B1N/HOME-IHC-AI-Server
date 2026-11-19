"""
Session checkout and conversation-queue retry guarantees.

The nurturing scan used to leave a SQLAlchemy connection checked out forever.
Conversation processing used to delete the Redis batch before the work finished,
so a pool timeout retried against an empty queue.
"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from celery.app.task import Context
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.db.models import Customer
from app.services.conversation_processor import (
    PROCESSING_ERROR_FALLBACK,
    ConversationQueueProcessor,
)
from app.services.lead_nurturing import LeadNurturingManager
from app.worker.tasks import process_conversation_queue, run_lead_nurturing_daemon


class FakeRedis:
    """Just enough of Redis for the conversation list and reply guards."""

    def __init__(self):
        self.values = {}
        self.lists = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
            if key in self.lists:
                del self.lists[key]
                removed += 1
        return removed

    def expire(self, key, seconds):
        return True

    def rpush(self, key, *items):
        bucket = self.lists.setdefault(key, [])
        bucket.extend(items)
        return len(bucket)

    def lrange(self, key, start, end):
        bucket = self.lists.get(key, [])
        if end == -1:
            end = len(bucket) - 1
        if start >= len(bucket) or end < start:
            return []
        return list(bucket[start:end + 1])

    def ltrim(self, key, start, end):
        bucket = self.lists.get(key, [])
        if end == -1:
            end = len(bucket) - 1
        if start >= len(bucket) or end < start:
            self.lists[key] = []
        else:
            self.lists[key] = bucket[start:end + 1]
        return True

    def llen(self, key):
        return len(self.lists.get(key, []))


class SessionCheckoutTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1,
            connect_args={"check_same_thread": False},
        )
        Customer.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _insert_due_customer(self):
        db = self.Session()
        try:
            db.add(Customer(
                id="+60120000001",
                contact_name="Aina",
                conversation_ids=[11],
                metadata_json={
                    "lead_temp": "hot",
                    "conversation_id": 11,
                    "bypass_ai": False,
                    "intent_category": "buyer",
                },
                last_interaction=datetime.now(timezone.utc) - timedelta(hours=20),
            ))
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.engine.pool.checkedout(), 0)

    def _run(self, sender):
        with patch("app.services.lead_nurturing.SessionLocal", self.Session), \
             patch("app.services.db_services.get_sender_role", return_value="customer"), \
             patch("app.api.settings.get_system_toggle", return_value=True):
            manager = LeadNurturingManager(
                message_sender=sender,
                note_sender=MagicMock(),
                template_dispatcher=MagicMock(),
                is_staging=False,
            )
            return manager.run_cycle()

    def test_run_cycle_checks_connection_back_in_on_success_and_exception(self):
        self._insert_due_customer()
        sender = MagicMock()
        result = self._run(sender)
        self.assertEqual(result["nurtured_messages"], 1)
        self.assertEqual(self.engine.pool.checkedout(), 0)
        sender.assert_called_once()

        # A leaked checkout would make this 1-slot pool time out.
        db = self.Session()
        try:
            row = db.query(Customer).one()
            meta = dict(row.metadata_json or {})
            meta.pop("last_nurtured_at", None)
            row.metadata_json = meta
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.engine.pool.checkedout(), 0)

        with patch.object(LeadNurturingManager, "dispatch_nurture", side_effect=RuntimeError("chatwoot down")):
            with self.assertRaises(RuntimeError):
                self._run(sender)
        self.assertEqual(self.engine.pool.checkedout(), 0)

        db = self.Session()
        try:
            self.assertEqual(db.query(Customer).count(), 1)
        finally:
            db.close()
        self.assertEqual(self.engine.pool.checkedout(), 0)

    @patch("app.services.db_services.get_sender_role", return_value="customer")
    @patch("app.services.lead_nurturing.SessionLocal")
    @patch("app.worker.tasks.send_private_note")
    @patch("app.worker.tasks.send_message")
    def test_daemon_does_not_keep_a_session(self, mock_msg, mock_note, mock_session_local, mock_role):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query.return_value.all.return_value = []
        with patch("app.api.settings.get_system_toggle", return_value=True):
            result = run_lead_nurturing_daemon()
        self.assertEqual(result["status"], "success")
        mock_db.close.assert_called()
        mock_msg.assert_not_called()


class SeedSessionTests(unittest.TestCase):
    @patch("scripts.seed_workflows.Base")
    @patch("scripts.seed_workflows.SessionLocal")
    def test_seed_workflows_closes_on_success(self, session_local, base):
        from scripts.seed_workflows import seed_workflows

        db = MagicMock()
        session_local.return_value = db
        seed_workflows()
        db.commit.assert_called()
        db.close.assert_called_once()


class QueueRetryTests(unittest.TestCase):
    def _processor(self, redis):
        task = MagicMock()
        task.request.id = "task-69"
        return ConversationQueueProcessor(
            celery_task=task,
            redis_client=redis,
            session_factory=MagicMock(),
            timeout_seconds=10,
        )

    def test_acknowledge_keeps_messages_that_arrive_during_processing(self):
        redis = FakeRedis()
        redis.rpush(
            "convo_queue_69",
            json.dumps({"id": 1, "content": "photo"}),
            json.dumps({"id": 2, "content": "caption"}),
        )
        processor = self._processor(redis)
        messages = processor.fetch_queued_messages(69)
        self.assertEqual([m["id"] for m in messages], [1, 2])
        redis.rpush("convo_queue_69", json.dumps({"id": 3, "content": "arrived later"}))

        remaining = processor.acknowledge_fetched_batch()
        self.assertEqual(remaining, 1)
        left = [json.loads(item)["id"] for item in redis.lrange("convo_queue_69", 0, -1)]
        self.assertEqual(left, [3])
        self.assertNotIn("convo_processing_69", redis.values)

    def test_failure_after_fetch_keeps_batch_and_success_removes_it(self):
        redis = FakeRedis()
        redis.set("convo_active_69", str(__import__("time").time() - 30))
        redis.rpush(
            "convo_queue_69",
            json.dumps({
                "id": 501,
                "content": "hello",
                "sender": {"phone_number": "+60120000000", "name": "Aina"},
            }),
        )
        state = {"fail": True}

        def resolve(self, conversation_id, contact_info, messages, latest_doc):
            if state["fail"]:
                raise RuntimeError("QueuePool timeout")
            customer = MagicMock()
            customer.id = "+60120000000"
            customer.contact_name = "Aina"
            customer.metadata_json = {}
            return customer, False, "+60120000000", "Aina", {"inbox_id": 4}

        with patch("app.worker.tasks.redis_client", redis), \
             patch("app.worker.tasks.toggle_typing_status"), \
             patch("app.api.settings.get_system_toggle", return_value=True), \
             patch("app.services.conversation_processor.toggle_typing_status"), \
             patch.object(ConversationQueueProcessor, "_processing_owner_id", return_value="task-69"), \
             patch.object(ConversationQueueProcessor, "resolve_customer", resolve), \
             patch.object(
                 ConversationQueueProcessor,
                 "build_rbac_and_context",
                 return_value=("customer", {"role": "customer", "data": {}}, "", "general", False, 0.0),
             ), \
             patch.object(
                 ConversationQueueProcessor,
                 "execute_persona_state_machine",
                 return_value=(
                     {"response": "ok", "schedule_viewing": False},
                     {"current_agent": "BUYER"},
                     "buyer",
                     "ok",
                     False,
                     "Warm",
                     [],
                 ),
             ), \
             patch.object(
                 ConversationQueueProcessor,
                 "generate_summary_and_handle_valuer",
                 return_value=("summary", None),
             ), \
             patch.object(ConversationQueueProcessor, "dispatch_media_and_response"), \
             patch.object(ConversationQueueProcessor, "persist_state_and_labels"):
            with self.assertRaises(RuntimeError):
                process_conversation_queue(69, 1.0)
            self.assertEqual(redis.llen("convo_queue_69"), 1)

            state["fail"] = False
            result = process_conversation_queue(69, 1.0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(redis.llen("convo_queue_69"), 0)
        self.assertNotIn("convo_queue_69", redis.lists)
        self.assertNotIn("convo_active_69", redis.values)

    def test_public_reply_is_sent_once_for_the_same_batch(self):
        redis = FakeRedis()
        processor = self._processor(redis)
        processor._fetched_messages = [{"id": 501, "content": "hello"}]
        processor._fetched_batch_count = 1
        processor._fetched_conversation_id = 69
        customer = MagicMock()
        customer.contact_name = "Aina"
        with patch("app.services.conversation_processor.send_message") as send_message, \
             patch("app.services.conversation_processor.toggle_typing_status"):
            processor.dispatch_media_and_response(
                conversation_id=69,
                images_to_send=[],
                response_text="Here is the land.",
                agent_result={},
                customer=customer,
                phone_number="+60120000000",
                contact_name="Aina",
            )
            processor.dispatch_media_and_response(
                conversation_id=69,
                images_to_send=[],
                response_text="Here is the land.",
                agent_result={},
                customer=customer,
                phone_number="+60120000000",
                contact_name="Aina",
            )
        send_message.assert_called_once_with(69, "Here is the land.")

    def test_unrecoverable_error_sends_one_fallback_and_turns_typing_off(self):
        redis = FakeRedis()
        processor = self._processor(redis)
        processor._fetched_messages = [{"id": 501, "content": "photo"}]
        processor._fetched_batch_count = 1
        processor._fetched_conversation_id = 69
        redis.rpush("convo_queue_69", json.dumps({"id": 501, "content": "photo"}))
        redis.set("convo_processing_69", "task-69")
        with patch("app.services.conversation_processor.send_message") as send_message, \
             patch("app.services.conversation_processor.toggle_typing_status") as typing, \
             patch("app.api.settings.get_system_toggle", return_value=True):
            first = processor.fail_unrecoverable(69, RuntimeError("QueuePool timeout"))
            # Batch was dropped, so a second call must not send again even if re-armed.
            processor._fetched_messages = [{"id": 501, "content": "photo"}]
            processor._fetched_batch_count = 1
            processor._fetched_conversation_id = 69
            second = processor.fail_unrecoverable(69, RuntimeError("QueuePool timeout"))
        self.assertTrue(first["fallback_sent"])
        self.assertFalse(second["fallback_sent"])
        send_message.assert_called_once_with(69, PROCESSING_ERROR_FALLBACK)
        typing.assert_any_call(69, "off")
        self.assertEqual(redis.llen("convo_queue_69"), 0)

    def test_task_sends_one_fallback_when_retries_are_exhausted(self):
        redis = FakeRedis()
        redis.set("convo_active_72", str(time.time() - 30))
        redis.rpush(
            "convo_queue_72",
            json.dumps({
                "id": 9,
                "content": "hi",
                "sender": {"name": "Aina", "phone_number": "+60120000000"},
            }),
        )

        def resolve(self, conversation_id, contact_info, messages, latest_doc):
            raise RuntimeError("QueuePool timeout")

        with patch("app.worker.tasks.redis_client", redis), \
             patch("app.worker.tasks.toggle_typing_status"), \
             patch("app.api.settings.get_system_toggle", return_value=True), \
             patch("app.services.conversation_processor.toggle_typing_status") as typing, \
             patch("app.services.conversation_processor.send_message") as send_message, \
             patch.object(ConversationQueueProcessor, "_processing_owner_id", return_value="task-72"), \
             patch.object(ConversationQueueProcessor, "resolve_customer", resolve):
            real_init = Context.__init__

            def _exhausted(self, *args, **kwargs):
                kwargs["retries"] = 3
                return real_init(self, *args, **kwargs)

            with patch.object(Context, "__init__", _exhausted):
                result = process_conversation_queue(72, 1.0)
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["fallback_sent"])
        self.assertEqual(result["batch_size"], 1)
        send_message.assert_called_once_with(72, PROCESSING_ERROR_FALLBACK)
        typing.assert_any_call(72, "off")
        self.assertEqual(redis.llen("convo_queue_72"), 0)

    def test_fallback_not_sent_when_manual_bypass_or_master_ai_off(self):
        redis = FakeRedis()
        processor = self._processor(redis)
        processor._fetched_messages = [{"id": 7, "content": "hi"}]
        processor._fetched_batch_count = 1
        processor._fetched_conversation_id = 70
        processor._manual_bypass = True
        with patch("app.services.conversation_processor.send_message") as send_message, \
             patch("app.services.conversation_processor.toggle_typing_status") as typing, \
             patch("app.api.settings.get_system_toggle", return_value=True):
            bypassed = processor.fail_unrecoverable(70, RuntimeError("boom"))
        self.assertFalse(bypassed["fallback_sent"])
        send_message.assert_not_called()
        typing.assert_called_with(70, "off")

        processor = self._processor(redis)
        processor._fetched_messages = [{"id": 8, "content": "hi"}]
        processor._fetched_batch_count = 1
        processor._fetched_conversation_id = 71
        with patch("app.services.conversation_processor.send_message") as send_message, \
             patch("app.services.conversation_processor.toggle_typing_status"), \
             patch("app.api.settings.get_system_toggle", return_value=False):
            disabled = processor.fail_unrecoverable(71, RuntimeError("boom"))
        self.assertFalse(disabled["fallback_sent"])
        send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
