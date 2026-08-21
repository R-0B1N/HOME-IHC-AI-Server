import unittest
from app.services.embeddings import build_property_aspect_chunks

class TestEmbeddingsAPI(unittest.TestCase):
    def test_aspect_chunks_generation(self):
        """
        Verifies that all 5 aspect text chunks (location, specs, features, suitability, overview)
        are constructed from property data.
        """
        sample_prop = {
            "id": "test-uuid-123",
            "title": "Raub 10 Ac Musang King Durian Orchard with River Stream",
            "city": "Raub",
            "state": "Pahang",
            "street_address": "Bukit Koman",
            "property_category": ["Agricultural Land", "Durian Land"],
            "property_type_sub": "Durian Orchard",
            "asking_price_myr": 2500000.0,
            "land_area_acres": 10.0,
            "tenure_type": "Freehold",
            "zoning_type": "Agriculture",
            "crop_types": ["Musang King", "Black Thorn"],
            "tree_count_estimate": 400,
            "tree_age_years": "6-8",
            "harvest_readiness": "Harvesting",
            "topography": "Gentle Slope",
            "has_natural_stream": True,
            "has_pond": True,
            "power_supply_amp": 60,
            "road_access_quality": "Tar road direct access",
            "suitable_industries": ["ecotourism", "durian export", "agro farming"],
            "key_highlights": ["400 matured trees", "River stream across land", "Freehold title"]
        }

        chunks = build_property_aspect_chunks(sample_prop)

        self.assertIn("location", chunks)
        self.assertIn("specs", chunks)
        self.assertIn("features", chunks)
        self.assertIn("suitability", chunks)
        self.assertIn("overview", chunks)

        self.assertIn("Raub", chunks["location"])
        self.assertTrue("10.0 acres" in chunks["specs"] or "10 acres" in chunks["specs"])
        self.assertIn("Musang King", chunks["features"])
        self.assertIn("ecotourism", chunks["suitability"])
        self.assertIn("Raub 10 Ac Musang King", chunks["overview"])

if __name__ == "__main__":
    unittest.main()

