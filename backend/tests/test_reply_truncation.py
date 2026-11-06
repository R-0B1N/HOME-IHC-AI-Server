"""
Conversation 233: the public seller Turn-1 reply was cut off mid-sentence at
"Kuantan and Bentong".

The full system prompt estimates above the 2048-token vLLM window, so the old
allocator requested max_tokens=50. The unfinished JSON "response" string was
then parsed and sent to WhatsApp. These tests lock the budget and the refusal
to publish a cut-off sentence.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import app.services.agent_logic as agent_logic
from app.services.llm import _parse_json_from_llm
from app.services.system_prompts import build_system_prompt, is_handover_promised


SELLER_TEXT = (
    "Hi Irene.I am Miss Lee talked to you just now."
    "I will send u the piece of land and the 1 residence info in Kuantan.\n"
    "Bentong Pahang land"
)
TRUNCATED_REPLY = (
    '{"response": "Hi Miss Lee! Since you mentioned that you have land and a '
    'residential property in Kuantan and Bentong'
)
COMPLETE_REPLY = (
    "Hi Miss Lee! Thank you for telling me about the land and the residence in "
    "Kuantan and Bentong. Could you share the title details and your asking price for each?"
)


def _completion(content, finish_reason):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    response = MagicMock()
    response.choices = [choice]
    return response


def _estimated_input_tokens(messages):
    chars = 0
    image_count = 0
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    chars += len(part.get("text") or "")
                elif part.get("type") == "image_url":
                    image_count += 1
    return int(chars / 2.5) + (agent_logic.IMAGE_TOKEN_RESERVE if image_count else 0)


class ReplyTruncationTests(unittest.TestCase):
    def test_full_prompt_legacy_budget_is_fifty_tokens(self):
        prompt = build_system_prompt(
            collected_data={"name": "Miss Lee", "customer_category": "seller"},
            customer_name="Miss Lee",
            customer_language="en",
            conversation_history="",
            role="customer",
        )
        estimated = int((len(prompt) + len(SELLER_TEXT)) / 2.5)
        legacy_max_tokens = min(450, max(50, 2030 - estimated))
        self.assertGreater(estimated, 2030)
        self.assertEqual(legacy_max_tokens, 50)

    def test_seller_turn1_completion_budget_can_finish_the_reply(self):
        complete = json.dumps({
            "response": COMPLETE_REPLY,
            "intent": "seller",
            "extracted_data": {"location": "Kuantan and Bentong"},
        })
        mock_create = MagicMock(return_value=_completion(complete, "stop"))
        with patch.object(agent_logic.llm_client.chat.completions, "create", mock_create):
            result = agent_logic.generate_conversational_response(
                text=SELLER_TEXT,
                customer_name="Miss Lee",
                collected_data={"name": "Miss Lee", "customer_category": "seller"},
                customer_language="en",
                is_seller=True,
                images=["land-title-bytes"],
            )

        self.assertEqual(result["response"], COMPLETE_REPLY)
        self.assertEqual(mock_create.call_count, 1)
        call = mock_create.call_args.kwargs
        estimated = _estimated_input_tokens(call["messages"])
        self.assertGreaterEqual(call["max_tokens"], agent_logic.MIN_COMPLETION_TOKENS)
        self.assertLessEqual(estimated + call["max_tokens"], agent_logic.CONTEXT_TOKEN_BUDGET)
        system_text = call["messages"][0]["content"]
        self.assertLess(len(system_text), 4500)
        self.assertIn("Never stop mid-sentence", system_text)

    def test_unclosed_mid_sentence_json_is_not_a_customer_reply(self):
        self.assertIsNone(_parse_json_from_llm(TRUNCATED_REPLY))
        self.assertIsNone(agent_logic._interpret_llm_content(TRUNCATED_REPLY, "length"))

        closed_but_unfinished = json.dumps({
            "response": (
                "Hi Miss Lee! Since you mentioned that you have land and a "
                "residential property in Kuantan and Bentong"
            ),
            "intent": "seller",
        })
        self.assertIsNone(agent_logic._interpret_llm_content(closed_but_unfinished, "length"))

    def test_truncated_seller_turn1_retries_and_publishes_the_full_sentence(self):
        complete = json.dumps({"response": COMPLETE_REPLY, "intent": "seller"})
        mock_create = MagicMock(side_effect=[
            _completion(TRUNCATED_REPLY, "length"),
            _completion(complete, "stop"),
        ])
        with patch.object(agent_logic.llm_client.chat.completions, "create", mock_create):
            result = agent_logic.generate_conversational_response(
                text=SELLER_TEXT,
                customer_name="Miss Lee",
                collected_data={"name": "Miss Lee", "customer_category": "seller"},
                customer_language="en",
                is_seller=True,
                images=["land-title-bytes", "residence-bytes", "extra-bytes"],
            )

        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(result["response"], COMPLETE_REPLY)
        self.assertTrue(result["response"].rstrip().endswith((".", "!", "?")))
        self.assertNotIn("Kuantan and Bentong\"", result["response"])
        self.assertFalse(result["response"].rstrip().endswith("Bentong"))
        self.assertFalse(is_handover_promised(result["response"]))
        first_images = [
            part for message in mock_create.call_args_list[0].kwargs["messages"]
            if isinstance(message["content"], list)
            for part in message["content"] if part.get("type") == "image_url"
        ]
        second_images = [
            part for message in mock_create.call_args_list[1].kwargs["messages"]
            if isinstance(message["content"], list)
            for part in message["content"] if part.get("type") == "image_url"
        ]
        self.assertEqual(len(first_images), 1)
        self.assertEqual(second_images, [])

    def test_still_truncated_seller_reply_falls_back_to_a_finished_sentence(self):
        mock_create = MagicMock(return_value=_completion(TRUNCATED_REPLY, "length"))
        with patch.object(agent_logic.llm_client.chat.completions, "create", mock_create):
            result = agent_logic.generate_conversational_response(
                text=SELLER_TEXT,
                customer_name="Miss Lee",
                collected_data={"name": "Miss Lee", "customer_category": "seller"},
                customer_language="en",
                is_seller=True,
            )

        reply = result["response"]
        self.assertGreaterEqual(mock_create.call_count, 2)
        self.assertNotIn("Since you mentioned that you have land", reply)
        self.assertTrue(reply.rstrip().endswith((".", "!", "?")))
        self.assertIn("Miss Lee", reply)
        self.assertIn("asking price", reply.lower())
        self.assertFalse(is_handover_promised(reply))
        self.assertFalse(result["promises_handover"])


if __name__ == "__main__":
    unittest.main()
