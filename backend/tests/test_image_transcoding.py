import io
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class TestImageTranscoding(unittest.TestCase):
    def test_pillow_webp_to_jpeg_transcoding(self):
        """
        Validates that RGBA or RGB WebP images are converted to valid JPEG byte streams
        compatible with Meta WhatsApp Cloud API and Chatwoot.
        """
        if not HAS_PIL:
            self.skipTest("Pillow not installed in local test environment (runs inside Docker container)")

        # 1. Create synthetic in-memory RGBA image and save as WebP
        img = Image.new("RGBA", (100, 100), color=(255, 120, 0, 200))
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP")
        webp_bytes = webp_buffer.getvalue()
        self.assertGreater(len(webp_bytes), 0)

        # 2. Transcode in-memory from WebP bytes to JPEG bytes
        loaded_img = Image.open(io.BytesIO(webp_bytes))
        if loaded_img.mode in ("RGBA", "P", "LA"):
            loaded_img = loaded_img.convert("RGB")
        
        jpeg_buffer = io.BytesIO()
        loaded_img.save(jpeg_buffer, format="JPEG", quality=85, optimize=True)
        jpeg_bytes = jpeg_buffer.getvalue()

        # 3. Verify output
        self.assertGreater(len(jpeg_bytes), 0)
        # JPEG magic header bytes: 0xFF, 0xD8
        self.assertEqual(jpeg_bytes[:2], b'\xff\xd8')
        
        # 4. Verify PIL can reopen transcoded bytes as valid JPEG
        reopened = Image.open(io.BytesIO(jpeg_bytes))
        self.assertEqual(reopened.format, "JPEG")
        self.assertEqual(reopened.mode, "RGB")
        self.assertEqual(reopened.size, (100, 100))

if __name__ == "__main__":
    unittest.main()

