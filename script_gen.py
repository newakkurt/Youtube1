import json
import random
import re
import time
import urllib.parse

import feedparser
import requests
from google import genai

from config import *

# ---------- Sağlayıcı ayarları ----------
GEMINI_MODEL = "gemini-3.8-flash"  # sabit
GROQ_MODELS = [m.strip() for m in env(
    "GROQ_MODELS",
    "llama-3.3-70b-versatile,openai/gpt-oss-120b,llama-3.1-8b-instant",
).split(",") if m.strip()]
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GROQ_KEY = env("GROQ_API_KEY")
OPENROUTER_KEY = env("OPENROUTER_API_KEY")

_dead = set()  # bu çalışmada kotası dolan / bulunamayan modeller


# ---------- Haber başlıkları / not ----------
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


# ---------- Model çağrıları ----------
def _gemini(prompt, as_json):
    cfg = {"temperature": 1.0}
    if as_json:
        cfg["response_mime_type"] = "application/json"
    client = genai.Client(api_key=GEMINI_API_KEY)
    return client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg).text


def _chat(url, key, model, prompt):
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 1.0},
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:150]}")
    return r.json()["choices"][0]["message"]["content"]


def _chain(as_json):
    """Sıra: Gemini 3.8 -> Groq (3 model) -> OpenRouter. Key'i olmayan atlanır."""
    chain = []
    if GEMINI_API_KEY:
        chain.append((f"gemini:{GEMINI_MODEL}", lambda p: _gemini(p, as_json)))
    if GROQ_KEY:
        for m in GROQ_MODELS:
            chain.append((
                f"groq:{m}",
                lambda p, m=m: _chat("https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, m, p),
            ))
    if OPENROUTER_KEY:
        chain.append((
            f"openrouter:{OPENROUTER_MODEL}",
            lambda p: _chat("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, OPENROUTER_MODEL, p),
        ))
    return [c for c in chain if c[0] not in _dead]


def _clean(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _extract_json(text):
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _ask(prompt, as_json=True):
    chain = _chain(as_json)
    print("Zincir:", [n for n, _ in chain])
    if not chain:
        raise RuntimeError("Kullanılabilir model yok (key eksik ya da hepsinin kotası doldu)")
    errors = []
    for rnd in range(3):
        for item in list(chain):
            name, fn = item
            try:
                text = _clean(fn(prompt) or "")
                if as_json:
                    text = json.dumps(_extract_json(text), ensure_ascii=False)
                if text:
                    print(f"OK: {name}")
                    return text
            except Exception as e:
                msg = str(e)
                print(f"FAIL: {name}: {msg[:150]}")
                errors.append(f"{name}: {msg[:100]}")
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "404" in msg or "401" in msg:
                    _dead.add(name)
                    chain.remove(item)
        if not chain:
            break
        time.sleep(10 * (rnd + 1))
    raise RuntimeError("Tüm modeller başarısız: " + " | ".join(errors[-5:]))


# ---------- Senaryo ----------
def generate(history):
    note = pick_note()
    prompt = f"""You write 25-35 second YouTube Shorts voiceover scripts for a channel about: {NICHE}.
All output language: {LANG_NAME}.
Build the video around this real field note from the channel owner. It is the unique angle: keep its meaning, and do not invent personal anecdotes beyond it:
"{note}"
Trending context (use only if clearly relevant): {headlines()}
Do NOT repeat these earlier titles: {history[-30:]}
Rules: fully original wording, no quotes from copyrighted sources, no false claims. Scene 1 is a hook (max 12 words). 4 scenes total, each 8-20 words, simple spoken language. Max 80 words in total.
Return ONLY JSON, no markdown:
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
