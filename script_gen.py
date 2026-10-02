import json
import random
import urllib.parse

import feedparser
from google import genai

from config import *


def headlines(n=8):
    if LANG == "tr":
        q, loc = "ağ güvenliği OR siber güvenlik OR network when:2d", "hl=tr&gl=TR&ceid=TR:tr"
    else:
        q, loc = "network security OR cybersecurity OR networking when:2d", "hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{loc}")
    return [e.title for e in feed.entries[:n]]


def pick_note():
    lines = [l.strip() for l in (ROOT / "field_notes.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    return random.choice(lines)


def _ask(prompt, as_json=True):
    cfg = {"temperature": 1.0}
    if as_json:
        cfg["response_mime_type"] = "application/json"
    client = genai.Client(api_key=GEMINI_API_KEY)
    return client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg).text


def generate(history):
    note = pick_note()
    prompt = f"""You write 25-35 second YouTube Shorts voiceover scripts for a channel about: {NICHE}.
All output language: {LANG_NAME}.
Build the video around this real field note from the channel owner. It is the unique angle: keep its meaning, and do not invent personal anecdotes beyond it:
"{note}"
Trending context (use only if clearly relevant): {headlines()}
Do NOT repeat these earlier titles: {history[-30:]}
Rules: fully original wording, no quotes from copyrighted sources, no false claims. Scene 1 is a hook (max 12 words). 4 scenes total, each 8-20 words, simple spoken language. Max 80 words in total.
Return ONLY JSON:
{{"title": "curiosity-driven, max 70 chars, honest",
 "scenes": [{{"text": "spoken line", "keyword": "2-3 English words for stock footage, concrete visual like 'server room'"}}],
 "local_tag": "one hashtag in {LANG_NAME}, no spaces",
 "global_tags": ["4 broad English hashtags, no spaces"],
 "description": "2 sentences"}}"""
    last = None
    for _ in range(3):
        try:
            data = json.loads(_ask(prompt))
            assert data["scenes"] and data["title"]
            data["scenes"].append({"text": OUTRO, "keyword": "computer network cables"})
            return data
        except Exception as e:
            last = e
    raise RuntimeError(f"Senaryo üretilemedi: {last}")


def advice(stats_text):
    prompt = (
        "You are a YouTube Shorts growth coach. Based on this weekly report, give exactly 3 short, concrete, "
        f"actionable suggestions in Turkish (what to repeat, what to change, posting tips):\n{stats_text}"
    )
    return _ask(prompt, as_json=False)
