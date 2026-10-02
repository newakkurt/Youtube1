import os
from pathlib import Path


def env(k, d=""):
    return os.environ.get(k) or d


ROOT = Path(__file__).parent
OUT = ROOT / "out"
QUEUE = ROOT / "queue.json"

TELEGRAM_TOKEN = env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.8-flash")
PEXELS_API_KEY = env("PEXELS_API_KEY")
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")

# false = Telegram'dan onay iste, true = %100 otomatik yayınla
AUTO_APPROVE = env("AUTO_APPROVE", "false").lower() == "true"

LANG = env("CONTENT_LANG", "tr")  # tr veya en
LANG_NAME = {"tr": "Turkish", "en": "English"}.get(LANG, LANG)
VOICE = env("TTS_VOICE", "tr-TR-AhmetNeural" if LANG == "tr" else "en-US-AndrewNeural")
NICHE = env("NICHE", "network engineering, network security, switches and routers, Linux, network automation (practical IT tips)")
CHANNEL_TAG = env("CHANNEL_TAG", "")  # ekranda küçük filigran, örn: @kanaladin
OUTRO = env("OUTRO", "Takip et, her gün sahadan yeni bir not geliyor." if LANG == "tr" else "Follow for a new field note every day.")
AFFILIATE_TEXT = env("AFFILIATE_TEXT", "")  # açıklamaya eklenir, örn: "📘 Önerdiğim kitap: https://..."
