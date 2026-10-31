import unittest

from platform_captions import build_platform_captions


class PlatformCaptionTests(unittest.TestCase):
    def test_returns_platform_specific_captions(self):
        script = {
            "title": "Fix VLAN Trunk Mismatch",
            "description": "Check both ends of the trunk.",
            "local_tag": "VLAN",
            "global_tags": ["Networking", "Cisco"],
            "scenes": [{"text": "Verify allowed VLANs on both ends."}],
        }

        def fake_ask(prompt, as_json=True, tier="strong"):
            self.assertIn("approved script", prompt.lower())
            return '{"caption":"A trunk mismatch can silently block the VLANs you need. Check both ends and compare the allowed VLAN list. What do you verify first? #Networking"}'

        result = build_platform_captions(script, "Check both ends of the trunk.")
        self.assertIn("instagram_caption", result)
        self.assertIn("linkedin_caption", result)
        self.assertTrue(result["instagram_caption"])
        self.assertTrue(result["linkedin_caption"])

    def test_fallback_when_model_is_unavailable(self):
        script = {
            "title": "Fix VLAN Trunk Mismatch",
            "description": "Check both ends of the trunk.",
            "local_tag": "VLAN",
            "global_tags": ["Networking"],
            "scenes": [{"text": "Verify allowed VLANs on both ends."}],
        }
        result = build_platform_captions(script, "Check both ends of the trunk.")
        self.assertIn("Instagram", result["instagram_caption"] if "Instagram" in result["instagram_caption"] else "Save")
        self.assertTrue(result["linkedin_caption"])


if __name__ == "__main__":
    unittest.main()
