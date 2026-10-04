import os
import json
import urllib.parse
import feedparser
import requests

# Yapılandırma değişkenleri
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

KEYWORDS = [
    "cisco switch configuration",
    "network security best practices",
    "dhcp snooping tutorial",
    "enterprise networking",
    "cybersecurity for beginners",
]

def get_latest_videos(max_results=3):
    """Google News RSS üzerinden güncel YouTube videolarını tarar."""
    found_topics = []
    for kw in KEYWORDS:
        query = f"site:youtube.com/watch {kw} when:2d"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        
        for entry in feed.entries[:1]:
            if "youtube.com/watch" in entry.link or "youtube.com/watch" in entry.guidislink:
                found_topics.append({
                    "title": entry.title,
                    "link": entry.link,
                    "keyword": kw
                })
            if len(found_topics) >= max_results:
                break
        if len(found_topics) >= max_results:
            break
    return found_topics

def generate_comment_draft(video_title, keyword):
    """Gemini API kullanarak profesyonel yorum hazırlar."""
    if not GEMINI_API_KEY:
        return "Great insights on network security! Thanks for sharing."
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""You are a senior network and systems engineer. 
Write a natural, insightful, and highly professional YouTube comment in English for a video titled: "{video_title}" (Topic: {keyword}).

Rules:
- Max 2-3 sentences.
- Sound like a real expert adding genuine value to the discussion (e.g., mention practical field experience or a related L2/L3 security nuance).
- NEVER sound like a bot, spam, or self-promotion. Do NOT say "Check out my channel" or "Great video".
- Return ONLY the comment text."""

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            res = r.json()
            return res["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"AI Yorum Üretme Hatası: {e}")
    
    return "Great breakdown of the network topology and security principles!"

def send_telegram_lead(title, link, comment):
    """Yorum önerisini Telegram grubuna gönderer."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram kimlik bilgileri eksik.")
        return

    text = (
        f"🎯 **Yeni Hedef Video Bulundu!**\n\n"
        f"📌 **Başlık:** {title}\n"
        f"🔗 **Link:** {link}\n\n"
        f"💬 **Önerilen Yorum (Dokun & Kopyala):**\n"
        f"`{comment}`\n\n"
        f"👉 Linke tıkla, yorumu yapıştır ve organik etkileşimini al!"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload, timeout=10)

def run_lead_finder():
    print("Hedef videolar taranıyor...")
    videos = get_latest_videos(max_results=3)
    if not videos:
        print("Yeni video bulunamadı.")
        return
    
    for v in videos:
        try:
            comment = generate_comment_draft(v["title"], v["keyword"])
            send_telegram_lead(v["title"], v["link"], comment)
            print(f"Gönderildi: {v['title']}")
        except Exception as e:
            print(f"Hata ({v['title']}): {e}")

if __name__ == "__main__":
    run_lead_finder()
