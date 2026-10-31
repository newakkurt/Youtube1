import unittest

from platform_captions import build_platform_captions


class PlatformCaptionTests(unittest.TestCase):
    def setUp(self):
        self.script = {
            "title": "Fix VLAN Trunk Mismatch",
            "description": "Check both ends of the trunk.",
            "local_tag": "VLAN",
            "global_tags": ["Networking", "Cisco"],
            "scenes": [{"text": "Verify allowed VLANs on both ends."}],
        }

    def test_generates_separate_platform_captions(self):
        def fake_ask(prompt, as_json=True, tier="strong"):
            self.assertIn("approved script", prompt.lower())
            return '{"caption":"A trunk mismatch can silently block the VLANs you need. Check both ends and compare the allowed VLAN list. What do you verify first? #Networking"}'

        result = build_platform_captions(
            self.script,
            "Check both ends of the trunk.",
            ask_fn=fake_ask,
            linkedin_fn=lambda title, desc: "LinkedIn version: " + title + ". " + desc,
        )
        self.assertIn("allowed VLAN list", result["instagram_caption"])
        self.assertTrue(result["linkedin_caption"].startswith("LinkedIn version:"))
        self.assertNotEqual(result["instagram_caption"], result["linkedin_caption"])

    def test_fallback_when_instagram_model_fails(self):
        def broken_ask(*args, **kwargs):
            raise RuntimeError("model unavailable")

        result = build_platform_captions(
            self.script,
            "Check both ends of the trunk.",
            ask_fn=broken_ask,
            linkedin_fn=lambda title, desc: title + " — " + desc,
        )
        self.assertIn("Save this", result["instagram_caption"])
        self.assertIn("Fix VLAN", result["linkedin_caption"])


if __name__ == "__main__":
    unittest.main()
