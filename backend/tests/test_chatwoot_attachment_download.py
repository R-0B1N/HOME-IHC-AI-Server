"""
Chatwoot attachment downloads must use the internal base URL.

Conv 69 (11 Nov 2026, 21:46–21:47 MYT) logged an image download of the public
Active Storage URL on inbox.bentongland.com.my and failed with Errno 101
(Network is unreachable). Text replies already use CHATWOOT_BASE_URL.
"""

import base64
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.chatwoot import fetch_chatwoot_attachment, rewrite_chatwoot_attachment_url
from app.services.conversation_processor import (
    PHOTO_DOWNLOAD_FALLBACK,
    ConversationQueueProcessor,
)
from app.services.document_parser import extract_text_from_document
from app.services.llm import transcribe_audio

INTERNAL = "http://crm-chatwoot-web:3000"
PUBLIC_IMAGE = (
    "https://inbox.bentongland.com.my/rails/active_storage/blobs/redirect/eyJabc/File.jpg"
    "?disposition=inline"
)
PUBLIC_DISK = "https://inbox.bentongland.com.my/rails/active_storage/disk/eyJdisk/File.jpg"
INTERNAL_IMAGE = (
    "http://crm-chatwoot-web:3000/rails/active_storage/blobs/redirect/eyJabc/File.jpg"
    "?disposition=inline"
)
INTERNAL_DISK = "http://crm-chatwoot-web:3000/rails/active_storage/disk/eyJdisk/File.jpg"


def _response(status_code, content=b"", headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = headers or {}
    response.close = MagicMock()
    response.raise_for_status = MagicMock()
    response.iter_content = MagicMock(return_value=[content] if content else [])
    return response


class TestChatwootAttachmentUrlRewrite(unittest.TestCase):
    def test_public_inbox_prefix_rewritten_to_configured_internal_base(self):
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL):
            rewritten = rewrite_chatwoot_attachment_url(PUBLIC_IMAGE)
        self.assertEqual(rewritten, INTERNAL_IMAGE)
        self.assertNotIn("inbox.bentongland.com.my", rewritten)

    def test_configured_public_host_uses_configured_internal_base(self):
        public = "https://inbox.other.example/rails/active_storage/blobs/redirect/abc/Pic.jpg"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", "http://chatwoot.internal:3000"), patch.dict(
            os.environ, {"CHATWOOT_PUBLIC_URL": "https://inbox.other.example"}
        ):
            rewritten = rewrite_chatwoot_attachment_url(public)
        self.assertEqual(
            rewritten,
            "http://chatwoot.internal:3000/rails/active_storage/blobs/redirect/abc/Pic.jpg",
        )

    def test_active_storage_on_any_public_host_uses_internal_base(self):
        public = "https://files.example.net/rails/active_storage/blobs/proxy/xyz/Plan.pdf"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL):
            rewritten = rewrite_chatwoot_attachment_url(public)
        self.assertEqual(
            rewritten,
            INTERNAL + "/rails/active_storage/blobs/proxy/xyz/Plan.pdf",
        )

    def test_external_url_is_not_rewritten(self):
        original = "https://example.com/photo.jpg"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL):
            self.assertEqual(rewrite_chatwoot_attachment_url(original), original)

    def test_redirect_to_public_host_stays_on_internal_base(self):
        redirect = _response(302, headers={"Location": PUBLIC_DISK})
        body = b"jpeg-after-redirect"
        ok = _response(200, content=body)
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", side_effect=[redirect, ok]) as mock_get:
            response = fetch_chatwoot_attachment(PUBLIC_IMAGE)

        self.assertEqual(response.content, body)
        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(urls, [INTERNAL_IMAGE, INTERNAL_DISK])
        for call in mock_get.call_args_list:
            self.assertNotIn("inbox.bentongland.com.my", call.args[0])
            self.assertEqual(call.kwargs["headers"]["api_access_token"], "internal-token")
            self.assertFalse(call.kwargs["allow_redirects"])

    def test_external_redirect_does_not_receive_api_token(self):
        redirect = _response(302, headers={"Location": "https://s3.amazonaws.com/bucket/File.jpg"})
        ok = _response(200, content=b"object-bytes")
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", side_effect=[redirect, ok]) as mock_get:
            fetch_chatwoot_attachment(PUBLIC_IMAGE)

        self.assertEqual(mock_get.call_args_list[0].kwargs["headers"]["api_access_token"], "internal-token")
        second_headers = mock_get.call_args_list[1].kwargs.get("headers") or {}
        self.assertNotIn("api_access_token", second_headers)
        self.assertEqual(mock_get.call_args_list[1].args[0], "https://s3.amazonaws.com/bucket/File.jpg")


class TestImageAudioAndDocumentDownloads(unittest.TestCase):
    def setUp(self):
        self.processor = ConversationQueueProcessor(
            celery_task=MagicMock(),
            redis_client=MagicMock(),
            timeout_seconds=10,
        )

    def test_public_inbox_image_bytes_are_kept_from_internal_fetch(self):
        body = b"\xff\xd8\xff-photo-bytes"
        ok = _response(200, content=body)
        messages = [
            {
                "content": "",
                "sender": {"name": "Customer", "phone_number": "+60123456789"},
                "attachments": [{"file_type": "image", "data_url": PUBLIC_IMAGE}],
            }
        ]
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", return_value=ok) as mock_get:
            prompt, images, _doc, contact, errors = self.processor.parse_multimodal_content(messages, 69)

        self.assertEqual(errors, [])
        self.assertEqual(images, [base64.b64encode(body).decode("utf-8")])
        self.assertIn("[Customer sent a photo.]", prompt)
        self.assertEqual(contact["name"], "Customer")
        self.assertEqual(mock_get.call_args.args[0], INTERNAL_IMAGE)
        self.assertNotIn("inbox.bentongland.com.my", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["headers"]["api_access_token"], "internal-token")

    def test_image_redirect_stays_internal_and_keeps_bytes(self):
        redirect = _response(302, content=b"", headers={"Location": PUBLIC_DISK})
        body = b"jpeg-after-redirect"
        ok = _response(200, content=body)
        messages = [
            {
                "content": "",
                "attachments": [{"file_type": "image", "data_url": PUBLIC_IMAGE}],
            }
        ]
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", side_effect=[redirect, ok]) as mock_get:
            _prompt, images, _doc, _contact, errors = self.processor.parse_multimodal_content(messages, 69)

        self.assertEqual(errors, [])
        self.assertEqual(images, [base64.b64encode(body).decode("utf-8")])
        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(urls, [INTERNAL_IMAGE, INTERNAL_DISK])
        for url in urls:
            self.assertNotIn("inbox.bentongland.com.my", url)

    def test_audio_download_rewrites_host_and_follows_internal_redirect(self):
        redirect = _response(
            302,
            headers={"Location": "https://inbox.bentongland.com.my/rails/active_storage/disk/eyJdisk/voice.ogg"},
        )
        ok = _response(200, content=b"OggS-audio")
        whisper = MagicMock()
        whisper.status_code = 200
        whisper.json.return_value = {"text": "land in Bentong"}
        audio_url = (
            "https://inbox.bentongland.com.my/rails/active_storage/blobs/redirect/eyJabc/voice.ogg"
        )
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", side_effect=[redirect, ok]) as mock_get, patch(
            "requests.post", return_value=whisper
        ):
            transcript = transcribe_audio(audio_url)

        self.assertEqual(transcript, "land in Bentong")
        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(
            urls,
            [
                INTERNAL + "/rails/active_storage/blobs/redirect/eyJabc/voice.ogg",
                INTERNAL + "/rails/active_storage/disk/eyJdisk/voice.ogg",
            ],
        )
        for url in urls:
            self.assertNotIn("inbox.bentongland.com.my", url)

    def test_document_download_rewrites_host_and_follows_internal_redirect(self):
        pdf = b"%PDF-1.4\n%mock pdf\n%%EOF"
        redirect = _response(
            302,
            headers={"Location": "https://inbox.bentongland.com.my/rails/active_storage/disk/eyJdisk/Plan.pdf"},
        )
        ok = _response(200, content=pdf, headers={"Content-Type": "application/pdf", "Content-Length": str(len(pdf))})
        doc_url = "https://inbox.bentongland.com.my/rails/active_storage/blobs/redirect/eyJabc/Plan.pdf"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", side_effect=[redirect, ok]) as mock_get:
            result = extract_text_from_document(
                doc_url,
                file_name="Plan.pdf",
                content_type="application/pdf",
                extension="pdf",
            )

        self.assertIn("text", result)
        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(
            urls,
            [
                INTERNAL + "/rails/active_storage/blobs/redirect/eyJabc/Plan.pdf",
                INTERNAL + "/rails/active_storage/disk/eyJdisk/Plan.pdf",
            ],
        )
        for url in urls:
            self.assertNotIn("inbox.bentongland.com.my", url)

    def test_document_proxy_fetches_public_active_storage_from_internal_base(self):
        from fastapi.testclient import TestClient

        from app.main import app

        pdf = b"%PDF-1.4\n%mock pdf\n%%EOF"
        ok = _response(
            200,
            content=pdf,
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": 'inline; filename="Plan.pdf"',
                "Content-Length": str(len(pdf)),
                "Accept-Ranges": "bytes",
            },
        )
        public = "https://inbox.bentongland.com.my/rails/active_storage/disk/eyJdisk/Plan.pdf"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch("requests.get", return_value=ok) as mock_get:
            response = TestClient(app).get(
                "/api/v1/documents/proxy",
                params={"url": public},
                headers={"Range": "bytes=0-100"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_get.call_args.args[0],
            INTERNAL + "/rails/active_storage/disk/eyJdisk/Plan.pdf",
        )
        self.assertNotIn("inbox.bentongland.com.my", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Range"], "bytes=0-100")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["api_access_token"], "internal-token")


class TestUndecodedAttachmentFallback(unittest.TestCase):
    def setUp(self):
        self.processor = ConversationQueueProcessor(
            celery_task=MagicMock(),
            redis_client=MagicMock(),
            timeout_seconds=10,
        )

    def test_failed_image_download_sends_one_public_fallback_without_llm(self):
        message = {
            "content": "",
            "sender": {"name": "Customer", "phone_number": "+60123456789"},
            "attachments": [{"file_type": "image", "data_url": PUBLIC_IMAGE}],
        }
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "app.services.chatwoot.CHATWOOT_API_TOKEN", "internal-token"
        ), patch.object(ConversationQueueProcessor, "check_debounce", return_value=None), patch.object(
            ConversationQueueProcessor, "check_master_ai_enabled", return_value=True
        ), patch.object(
            ConversationQueueProcessor, "fetch_queued_messages", return_value=[message]
        ), patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("[Errno 101] Network is unreachable"),
        ) as mock_get, patch(
            "app.services.conversation_processor.toggle_typing_status"
        ) as mock_typing, patch(
            "app.services.conversation_processor.send_message"
        ) as mock_send, patch(
            "app.services.conversation_processor.process_persona_state_machine"
        ) as mock_persona, patch(
            "app.services.conversation_processor.llm_client"
        ) as mock_llm:
            with self.assertLogs("app.services.conversation_processor", level="ERROR") as logs:
                result = self.processor.process(69, 1.0)

        self.assertEqual(result["status"], "fallback_sent")
        self.assertEqual(result["reason"], "attachment download failed")
        self.assertNotEqual(result.get("reason"), "empty aggregated input")
        self.assertNotEqual(result.get("status"), "skipped")
        mock_send.assert_called_once_with(69, PHOTO_DOWNLOAD_FALLBACK)
        self.assertIn("photo", PHOTO_DOWNLOAD_FALLBACK.lower())
        self.assertIn("again", PHOTO_DOWNLOAD_FALLBACK.lower())
        mock_typing.assert_called_once_with(69, "off")
        mock_persona.assert_not_called()
        mock_llm.assert_not_called()
        self.assertEqual(mock_get.call_args.args[0], INTERNAL_IMAGE)
        self.assertNotIn("inbox.bentongland.com.my", mock_get.call_args.args[0])
        logged = "\n".join(logs.output)
        self.assertIn("file_type=image", logged)
        self.assertIn("filename=File.jpg", logged)
        self.assertIn("Network is unreachable", logged)

    def test_caption_only_and_no_attachment_empty_input_still_skips(self):
        cases = {
            "no attachment": [{"content": "", "sender": {"name": "A"}}],
            "empty caption": [{"content": "", "attachments": [], "sender": {"name": "A"}}],
            "whitespace caption": [{"content": "   ", "attachments": [], "sender": {"name": "A"}}],
        }
        with patch.object(ConversationQueueProcessor, "check_debounce", return_value=None), patch.object(
            ConversationQueueProcessor, "check_master_ai_enabled", return_value=True
        ), patch(
            "requests.get", side_effect=AssertionError("attachment download is not expected")
        ), patch(
            "app.services.conversation_processor.toggle_typing_status"
        ) as mock_typing, patch(
            "app.services.conversation_processor.send_message"
        ) as mock_send, patch(
            "app.services.conversation_processor.process_persona_state_machine"
        ) as mock_persona:
            for label, messages in cases.items():
                with self.subTest(label):
                    with patch.object(
                        ConversationQueueProcessor, "fetch_queued_messages", return_value=messages
                    ):
                        result = self.processor.process(69, 1.0)
                    self.assertEqual(result, {"status": "skipped", "reason": "empty aggregated input"})
        mock_send.assert_not_called()
        mock_typing.assert_not_called()
        mock_persona.assert_not_called()

    def test_caption_text_with_failed_image_does_not_send_photo_fallback(self):
        message = {
            "content": "Is this land still available?",
            "sender": {"name": "Buyer", "phone_number": "+60120000000"},
            "attachments": [{"file_type": "image", "data_url": PUBLIC_IMAGE}],
        }
        customer = MagicMock()
        customer.id = "cust-1"
        with patch("app.services.chatwoot.CHATWOOT_BASE_URL", INTERNAL), patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("[Errno 101] Network is unreachable"),
        ), patch.object(ConversationQueueProcessor, "check_debounce", return_value=None), patch.object(
            ConversationQueueProcessor, "check_master_ai_enabled", return_value=True
        ), patch.object(
            ConversationQueueProcessor, "fetch_queued_messages", return_value=[message]
        ), patch.object(
            ConversationQueueProcessor,
            "resolve_customer",
            return_value=(customer, False, "+60120000000", "Buyer", {"inbox_id": 4}),
        ), patch.object(
            ConversationQueueProcessor,
            "build_rbac_and_context",
            return_value=("customer", {"role": "customer", "data": {}}, "", "buyer_search", False, 0.0),
        ), patch.object(
            ConversationQueueProcessor,
            "execute_persona_state_machine",
            return_value=(
                {"response": "Yes, it is available.", "schedule_viewing": False},
                {"current_agent": "BUYER"},
                "buyer",
                "Yes, it is available.",
                False,
                "Warm",
                [],
            ),
        ) as mock_persona, patch.object(
            ConversationQueueProcessor,
            "generate_summary_and_handle_valuer",
            return_value=("Inquiry about land", None),
        ), patch.object(
            ConversationQueueProcessor, "dispatch_media_and_response"
        ), patch.object(
            ConversationQueueProcessor, "persist_state_and_labels"
        ), patch(
            "app.services.conversation_processor.toggle_typing_status"
        ), patch(
            "app.services.conversation_processor.send_message"
        ) as mock_send:
            result = self.processor.process(69, 1.0)

        self.assertEqual(result["status"], "success")
        self.assertNotEqual(result.get("reason"), "empty aggregated input")
        mock_send.assert_not_called()
        mock_persona.assert_called_once()


if __name__ == "__main__":
    unittest.main()
