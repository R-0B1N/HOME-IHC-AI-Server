"""
Caption-less shopfront photos must be read before the reply.

A photo used to be replaced with "[Customer sent a photo.]", classified as
unidentified_listing from that placeholder, and answered with the screenshot
template. The image was only attached on the reply call, which that early
return never reached. Text-only "is it still available???" still uses the
template.
"""
import json
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import app.services.llm as llm_service
from app.services.agent_logic import (
    generate_conversational_response,
    process_persona_state_machine,
    restore_image_turn_reply,
)
from app.services.conversation_processor import ConversationQueueProcessor
from app.services.llm import (
    PHOTO_VISION_MAX_TOKENS,
    append_photo_description,
    classify_turn_intent,
    describe_customer_photos,
)
from app.services.role_contract import sanitize_unverified_reply
from app.services.system_prompts import (
    IMAGE_TURN_NO_MEDIA_REQUEST,
    build_system_prompt,
    get_multilingual_disambiguation_request,
)

VISION_TEXT = "FOR RENT, 012-3456789, Jalan Bilut, Bentong, shop"
PHOTO_B64 = "aGVsbG8="
MODEL_REPLY = (
    "Could you share a screenshot, photo, or link of the advertisement you saw? "
    "The sign reads FOR RENT on Jalan Bilut."
)
ASK_ONLY = "Could you share a screenshot, photo, or link, and I'll verify it right away!"


def _completion(content, finish_reason="stop"):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    response = MagicMock()
    response.choices = [choice]
    return response


def _system_text(messages):
    content = messages[0]["content"]
    return content if isinstance(content, str) else ""


def _user_content(messages):
    return messages[-1]["content"]


def _image_parts(messages):
    content = _user_content(messages)
    if not isinstance(content, list):
        return []
    return [part for part in content if part.get("type") == "image_url"]


def _blob(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text") or ""
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


@contextmanager
def _lock(*_args, **_kwargs):
    yield


class _MemoryRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return 1

    def expire(self, key, seconds):
        return True


class VisionPhotoReplyTests(unittest.TestCase):
    def _llm(self, vision_error=False, reply_text=MODEL_REPLY):
        calls = []

        def fake_create(**kwargs):
            messages = kwargs["messages"]
            system = _system_text(messages)
            user = _user_content(messages)
            calls.append({"system": system, "user": user, "max_tokens": kwargs.get("max_tokens")})
            if kwargs.get("max_tokens") == PHOTO_VISION_MAX_TOKENS and isinstance(user, list):
                if vision_error:
                    raise TimeoutError("vision timed out")
                return _completion(VISION_TEXT)
            if "unidentified_listing" in system:
                return _completion('{"category": "unidentified_listing"}')
            if "real estate search parser" in system:
                return _completion(
                    '{"location": "Bentong", "property_type": "shop", '
                    '"category": "commercial", "max_price": null}'
                )
            if "Summarize this customer" in system:
                return _completion("Customer sent a for-rent shop photo.")
            return _completion(json.dumps({"response": reply_text, "intent": "buyer"}))

        return calls, fake_create

    def _run_process(self, fake_create):
        sent = []
        saved = []
        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        patches = [
            patch.dict(os.environ, {"PHOTO_VISION_ENABLED": "1"}),
            patch.object(ConversationQueueProcessor, "check_debounce", return_value=None),
            patch.object(ConversationQueueProcessor, "check_master_ai_enabled", return_value=True),
            patch.object(
                ConversationQueueProcessor,
                "fetch_queued_messages",
                return_value=[{"id": 1, "content": ""}],
            ),
            patch.object(
                ConversationQueueProcessor,
                "parse_multimodal_content",
                return_value=(
                    "[Customer sent a photo.]",
                    [PHOTO_B64],
                    None,
                    {"name": "Alex", "phone_number": "+601200000001"},
                    [],
                ),
            ),
            patch.object(
                ConversationQueueProcessor,
                "resolve_customer",
                return_value=(None, False, "+601200000001", "Alex", {"inbox_id": 1}),
            ),
            patch("app.services.conversation_processor.get_sender_role", return_value="customer"),
            patch("app.services.conversation_processor.get_conversation_messages", return_value=[]),
            patch("app.services.conversation_processor.SessionManager.lock_session", side_effect=_lock),
            patch("app.services.conversation_processor.SessionManager.get_session", return_value={}),
            patch(
                "app.services.conversation_processor.SessionManager.save_session",
                side_effect=lambda phone, session: saved.append(session),
            ),
            patch("app.services.conversation_processor.search_properties", return_value=[]),
            patch("app.services.agent_logic.find_matching_property", return_value=None),
            patch("app.services.agent_logic.search_properties", return_value=[]),
            patch("app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"),
            patch("app.services.conversation_processor.toggle_typing_status"),
            patch("app.services.conversation_processor.apply_label"),
            patch("app.services.conversation_processor.set_priority"),
            patch(
                "app.services.conversation_processor.send_message",
                side_effect=lambda conversation_id, content, **kwargs: sent.append(content),
            ),
            patch.object(llm_service.llm_client.chat.completions, "create", side_effect=fake_create),
        ]
        for item in patches:
            item.start()
        try:
            result = processor.process(conversation_id=71, task_scheduled_time=1.0)
        finally:
            for item in reversed(patches):
                item.stop()
        return result, sent, saved

    def test_captionless_photo_is_read_and_the_reply_keeps_the_image(self):
        calls, fake_create = self._llm()
        result, sent, saved = self._run_process(fake_create)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(sent), 1)
        reply = sent[0]
        self.assertIn("Jalan Bilut", reply)
        self.assertIn("FOR RENT", reply)
        lowered = reply.lower()
        self.assertNotIn("screenshot", lowered)
        self.assertNotIn("photo, or link", lowered)
        self.assertNotIn("share a photo", lowered)
        self.assertNotIn("share a link", lowered)
        self.assertNotIn("could you share", lowered)

        vision_calls = [call for call in calls if call["max_tokens"] == PHOTO_VISION_MAX_TOKENS]
        self.assertEqual(len(vision_calls), 1)
        self.assertEqual(len(_image_parts_from_call(vision_calls[0])), 1)

        classifiers = [call for call in calls if "unidentified_listing" in call["system"]]
        self.assertEqual(len(classifiers), 1)
        for call in classifiers:
            self.assertIn("[Photo shows:", _blob(call["user"]))
            self.assertIn("Jalan Bilut", _blob(call["user"]))
            self.assertIn("012-3456789", _blob(call["user"]))

        criteria = [call for call in calls if "real estate search parser" in call["system"]]
        self.assertEqual(len(criteria), 1)
        self.assertIn("[Photo shows:", _blob(criteria[0]["user"]))
        self.assertIn(VISION_TEXT, _blob(criteria[0]["user"]))

        reply_calls = [
            call for call in calls
            if call["max_tokens"] != PHOTO_VISION_MAX_TOKENS and _image_parts_from_call(call)
        ]
        self.assertGreaterEqual(len(reply_calls), 1)
        reply_call = reply_calls[0]
        self.assertIn("data:image/jpeg;base64," + PHOTO_B64, json.dumps(reply_call["user"]))
        self.assertIn("[Photo shows:", _blob(reply_call["user"]))
        self.assertIn("Do not request another image", reply_call["system"])
        self.assertNotIn("ask for a screenshot, photo, or link", reply_call["system"])

        self.assertTrue(saved)
        self.assertEqual(saved[-1].get("turn_intent"), "unidentified_listing")
        self.assertFalse(saved[-1].get("unidentified_listing_turns"))

    def test_vision_failure_still_finishes_the_turn(self):
        calls, fake_create = self._llm(vision_error=True, reply_text=ASK_ONLY)
        result, sent, saved = self._run_process(fake_create)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(sent), 1)
        reply = sent[0]
        self.assertNotIn("screenshot", reply.lower())
        self.assertNotIn("photo, or link", reply.lower())
        self.assertNotIn("right away", reply.lower())
        self.assertIn("photo", reply.lower())
        self.assertTrue(saved)
        self.assertFalse(saved[-1].get("unidentified_listing_turns"))

        classifiers = [call for call in calls if "unidentified_listing" in call["system"]]
        self.assertGreaterEqual(len(classifiers), 1)
        for call in classifiers:
            self.assertNotIn("[Photo shows:", _blob(call["user"]))

        reply_calls = [
            call for call in calls
            if call["max_tokens"] != PHOTO_VISION_MAX_TOKENS and _image_parts_from_call(call)
        ]
        self.assertGreaterEqual(len(reply_calls), 1)

    def test_text_only_availability_still_returns_the_template(self):
        expected = get_multilingual_disambiguation_request("en", "Alex")
        create = MagicMock(return_value=_completion('{"category": "unidentified_listing"}'))
        with patch.dict(os.environ, {"PHOTO_VISION_ENABLED": "1"}), patch(
            "app.services.agent_logic.find_matching_property", return_value=None
        ), patch(
            "app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"
        ), patch.object(llm_service.llm_client.chat.completions, "create", create):
            result = process_persona_state_machine(
                phone_number="+601200000099",
                raw_text="is it still available???",
                session={},
                conversation_history="",
                contact_name="Alex",
            )
        self.assertEqual(result["response"], expected)
        self.assertIn("screenshot, photo, or link", result["response"])
        self.assertEqual(create.call_count, 1)
        self.assertFalse(_image_parts(create.call_args.kwargs["messages"]))

        processor = ConversationQueueProcessor(
            redis_client=_MemoryRedis(),
            session_factory=lambda: MagicMock(),
        )
        with patch(
            "app.services.conversation_processor.SessionManager.lock_session", side_effect=_lock
        ), patch(
            "app.services.conversation_processor.SessionManager.get_session", return_value={}
        ), patch(
            "app.services.conversation_processor.SessionManager.save_session"
        ), patch(
            "app.services.agent_logic.find_matching_property", return_value=None
        ), patch(
            "app.services.agent_logic.MultiIntentMemoryTracker.persist_customer_memory"
        ), patch.object(llm_service.llm_client.chat.completions, "create", create):
            _agent, _session, _intent, response, handover, _temp, _images = (
                processor.execute_persona_state_machine(
                    phone_number="+601200000099",
                    contact_name="Alex",
                    role="customer",
                    final_prompt_text="is it still available???",
                    conversation_history="",
                    latest_doc_struct=None,
                    turn_intent="unidentified_listing",
                    combined_images=[],
                    db_context={"role": "customer", "data": {}},
                    is_seller_intent=False,
                    reset_cutoff_ts=0.0,
                )
            )
        self.assertFalse(handover)
        self.assertEqual(response, sanitize_unverified_reply(expected))
        self.assertIn("screenshot, photo, or link", response)

    def test_promise_sanitizer_does_not_gut_an_image_turn_into_another_photo_ask(self):
        source = append_photo_description("[Customer sent a photo.]", VISION_TEXT)
        sanitized = sanitize_unverified_reply(ASK_ONLY)
        restored = restore_image_turn_reply(sanitized, source)
        self.assertNotIn("screenshot", restored.lower())
        self.assertNotIn("right away", restored.lower())
        self.assertNotIn("specialist", restored.lower())
        self.assertIn("Jalan Bilut", restored)
        self.assertNotEqual(restored, sanitize_unverified_reply("I'll verify it right away!"))

    def test_photo_note_keyword_fallback_is_not_seller_intake(self):
        prompt = append_photo_description("[Customer sent a photo.]", "出售 sign, Jalan Bilut, shop")
        with patch.object(
            llm_service.llm_client.chat.completions, "create", side_effect=TimeoutError("down")
        ):
            category = classify_turn_intent(prompt)
        self.assertEqual(category, "buyer_search")

    def test_vision_toggle_off_skips_the_call_and_returns_empty(self):
        with patch.dict(os.environ, {"PHOTO_VISION_ENABLED": "0"}), patch.object(
            llm_service.llm_client.chat.completions, "create"
        ) as create:
            self.assertEqual(describe_customer_photos([PHOTO_B64]), "")
        create.assert_not_called()
        self.assertEqual(
            append_photo_description("[Customer sent a photo.]", ""),
            "[Customer sent a photo.]",
        )

    def test_overflow_retry_keeps_the_image_when_the_vision_note_fits(self):
        note = append_photo_description("[Customer sent a photo.]", VISION_TEXT)
        truncated = '{"response": "The sign reads FOR RENT on Jalan Bilut'
        complete = json.dumps({
            "response": "The sign reads FOR RENT on Jalan Bilut.",
            "intent": "buyer",
        })
        create = MagicMock(side_effect=[
            _completion(truncated, "length"),
            _completion(complete, "stop"),
        ])
        with patch.object(llm_service.llm_client.chat.completions, "create", create):
            result = generate_conversational_response(
                text=note,
                images=[PHOTO_B64],
                customer_language="en",
                conversation_history="",
            )
        self.assertEqual(create.call_count, 2)
        self.assertIn("Jalan Bilut", result["response"])
        self.assertNotIn("screenshot", result["response"].lower())
        self.assertEqual(len(_image_parts(create.call_args_list[0].kwargs["messages"])), 1)
        self.assertEqual(len(_image_parts(create.call_args_list[1].kwargs["messages"])), 1)
        self.assertIn("[Photo shows:", _blob(_user_content(create.call_args_list[1].kwargs["messages"])))
        self.assertIn(IMAGE_TURN_NO_MEDIA_REQUEST, create.call_args_list[0].kwargs["messages"][0]["content"])

    def test_context_overflow_keeps_the_vision_note_if_the_image_will_not_fit(self):
        note = append_photo_description("[Customer sent a photo.]", VISION_TEXT)
        complete = json.dumps({
            "response": "The sign reads FOR RENT on Jalan Bilut.",
            "intent": "buyer",
        })
        create = MagicMock(side_effect=[
            RuntimeError("Error code: 400 maximum context length exceeded"),
            RuntimeError("Error code: 400 maximum context length exceeded"),
            _completion(complete, "stop"),
        ])
        with patch.object(llm_service.llm_client.chat.completions, "create", create):
            result = generate_conversational_response(
                text=note,
                images=[PHOTO_B64],
                customer_language="en",
                conversation_history="",
            )
        self.assertIn("Jalan Bilut", result["response"])
        self.assertNotIn("screenshot", result["response"].lower())
        self.assertGreaterEqual(create.call_count, 2)
        last_messages = create.call_args_list[-1].kwargs["messages"]
        self.assertEqual(_image_parts(last_messages), [])
        self.assertIn("[Photo shows:", _blob(_user_content(last_messages)))
        self.assertIn("Jalan Bilut", _blob(_user_content(last_messages)))

    def test_image_prompt_omits_the_screenshot_request(self):
        prompted = build_system_prompt(customer_language="en", role="customer", customer_sent_image=True)
        self.assertNotIn("ask for a screenshot, photo, or link", prompted)
        self.assertIn("Do not request another image", prompted)
        plain = build_system_prompt(customer_language="en", role="customer", customer_sent_image=False)
        self.assertIn("ask for a screenshot, photo, or link", plain)


def _image_parts_from_call(call):
    user = call["user"]
    if not isinstance(user, list):
        return []
    return [part for part in user if isinstance(part, dict) and part.get("type") == "image_url"]


if __name__ == "__main__":
    unittest.main()
