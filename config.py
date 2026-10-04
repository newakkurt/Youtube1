import os
from pathlib import Path


def env(k, d=""):
    return (os.environ.get(k) or d).strip()


ROOT = Path(__file__).parent
OUT = ROOT / "out"
QUEUE = ROOT / "queue.json"

TELEGRAM_TOKEN = env("TELEGRAM_TOKEN").removeprefix("bot")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = env("GEMINI_API_KEY")
PEXELS_API_KEY = env("PEXELS_API_KEY")
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")

# true = onay istemeden direkt YouTube'a yükler (varsayılan). false = Telegram'dan onay iste.
AUTO_APPROVE = env("AUTO_APPROVE", "true").lower() == "true"

LANG = env("CONTENT_LANG", "en")  # tr veya en
LANG_NAME = {"tr": "English", "en": "English"}.get(LANG, LANG)
VOICE = env("TTS_VOICE", "tr-TR-AhmetNeural" if LANG == "tr" else "en-US-AndrewNeural")
NICHE = env("NICHE", "network engineering, Cybersecurity, network security, switches and routers, Linux, network automation (practical IT tips)")
CHANNEL_TAG = env("CHANNEL_TAG", "")  # ekranda küçük filigran, örn: @kanaladin
OUTRO = env("OUTRO", "Takip et, her gün sahadan yeni bir not geliyor." if LANG == "tr" else "Follow for a new field note every day.")
AFFILIATE_TEXT = env("AFFILIATE_TEXT", "")
