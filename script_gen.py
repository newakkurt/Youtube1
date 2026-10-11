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
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.8-flash")
GROQ_MODELS = [m.strip() for m in env(
    "GROQ_MODELS",
    "llama-3.3-70b-versatile,openai/gpt-oss-120b,llama-3.1-8b-instant",
).split(",") if m.strip()]
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GROQ_KEY = env("GROQ_API_KEY")
OPENROUTER_KEY = env("OPENROUTER_API_KEY")

# Router: "fast" işlerde bu işaretleri taşıyan küçük modeller öne alınır
FAST_MARKS = ("8b", "mini", "20b")
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
PERF_FILE = ROOT / "performance.json"  # [{"title": "...", "views": 123}, ...]

_dead = set()


# ---------- Haber başlıkları / not ----------
def headlines(n=8):
    q, loc = "network security OR cybersecurity OR networking when:2d", "hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{loc}")
    return [e.title for e in feed.entries[:n]]


def pick_note():
    lines = [l.strip() for l in (ROOT / "field_notes.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    return random.choice(lines)


# ---------- (2) Gerçek kaynaktan veri: CISA KEV ----------
def grounding(pick=3, pool=15):
    """CISA'nın bilinen istismar edilen açıklar listesinden son kayıtlar. Hata olursa boş döner."""
    try:
        r = requests.get(KEV_URL, timeout=20)
        r.raise_for_status()
        vulns = sorted(r.json()["vulnerabilities"], key=lambda v: v["dateAdded"], reverse=True)[:pool]
        vulns = random.sample(vulns, min(pick, len(vulns)))
        return "\n".join(
            f"- {v['cveID']} ({v['vendorProject']} {v['product']}), added {v['dateAdded']}: "
            f"{v['shortDescription'][:200]}"
            for v in vulns
        )
    except Exception as e:
        print("Grounding failed:", str(e)[:150])
        return ""


# ---------- (1) Geri besleme: en çok izlenen başlıklar ----------
def winners(n=5):
    try:
        rows = json.loads(PERF_FILE.read_text(encoding="utf-8"))
        rows = sorted(rows, key=lambda r: r.get("views", 0), reverse=True)[:n]
        return [r["title"] for r in rows if r.get("title")]
    except Exception:
        return []


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


# ---------- (4) Router ----------
def _chain(as_json, tier="strong"):
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
    chain = [c for c in chain if c[0] not in _dead]
    is_fast = lambda c: any(mk in c[0] for mk in FAST_MARKS)
    # sorted kararlıdır: aynı gruptakiler kendi sırasını korur
    if tier == "fast":
        return sorted(chain, key=lambda c: 0 if is_fast(c) else 1)
    return sorted(chain, key=lambda c: 1 if is_fast(c) else 0)


def _clean(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _extract_json(text):
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _ask(prompt, as_json=True, tier="strong"):
    chain = _chain(as_json, tier)
    print(f"Chain ({tier}):", [n for n, _ in chain])
    if not chain:
        raise RuntimeError("No available model (missing key or quota exhausted)")
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
    raise RuntimeError("All models failed: " + " | ".join(errors[-5:]))


# ---------- (3) Kontrol ajanı ----------
def review(data, facts):
    """İkinci model taslağı puanlar. Başarısız olursa akışı bloklamaz."""
    script = " ".join(s["text"] for s in data["scenes"])
    prompt = f"""You are a strict YouTube Shorts editor and fact-checker for a network & cybersecurity channel.
Title: {data['title']}
Script: {script}
Verified facts available: {facts or 'none'}
Judge the draft and return ONLY JSON with these keys:
"hook": integer 1-10 (is the first line scroll-stopping and curiosity-driven?),
"fact_risk": integer 1-10 (10 = very likely invented or wrong numbers, dates, CVE ids or product claims),
"issues": list of at most 3 short, concrete fixes."""
    try:
        v = json.loads(_ask(prompt, tier="fast"))
        return {
            "hook": int(v.get("hook", 7)),
            "fact_risk": int(v.get("fact_risk", 3)),
            "issues": [str(i) for i in v.get("issues", [])][:3],
        }
    except Exception as e:
        print("Review skipped:", str(e)[:150])
        return {"hook": 7, "fact_risk": 3, "issues": []}


# ---------- Senaryo ----------
def _draft(note, facts, win, history, feedback):
    win_block = (
        f"Our best-performing titles so far (match their style and curiosity pattern, do NOT copy them): {win}\n"
        if win else ""
    )
    facts_block = (
        f"Verified facts (CISA Known Exploited Vulnerabilities). Any specific CVE, date or vendor you mention MUST come from here:\n{facts}\n"
        if facts else ""
    )
    prompt = f"""You write 25-35 second YouTube Shorts voiceover scripts for a channel about: Network & Cybersecurity.
All output language: English.
Build the video around this real field note from the channel owner. It is the unique angle: keep its meaning, and do not invent personal anecdotes beyond it:
"{note}"
Trending context (use only if clearly relevant): {headlines()}
{facts_block}{win_block}Do NOT repeat these earlier titles: {history[-30:]}
Rules: fully original wording, no quotes from copyrighted sources, no false claims. Never invent statistics, CVE numbers, dates or product details; if unsure, speak in general terms. Scene 1 is a hook (max 12 words). 4 scenes total, each 8-20 words, simple spoken language. Max 80 words in total.
{feedback}
Return ONLY JSON, no markdown:
{{"title": "curiosity-driven, max 70 chars, honest",
 "scenes": [{{"text": "spoken line", "keyword": "2-3 English words for stock footage, concrete visual like 'server room'"}}],
 "local_tag": "one hashtag in English, no spaces",
 "global_tags": ["4 broad English hashtags, no spaces"],
 "description": "2 sentences"}}"""
    data = json.loads(_ask(prompt, tier="strong"))
    assert data["scenes"] and data["title"]
    return data


def generate(history):
    note = pick_note()
    facts = grounding()
    win = winners()
    feedback = ""
    best = None  # (skor, taslak)
    last = None
    for attempt in range(3):
        try:
            data = _draft(note, facts, win, history, feedback)
        except Exception as e:
            last = e
            continue
        v = review(data, facts)
        score = v["hook"] - v["fact_risk"]
        print(f"Review #{attempt + 1}: hook={v['hook']} fact_risk={v['fact_risk']} issues={v['issues']}")
        if best is None or score > best[0]:
            best = (score, data)
        if v["hook"] >= 7 and v["fact_risk"] <= 3:
            break
        feedback = "A previous draft had these problems, fix them: " + "; ".join(v["issues"]) if v["issues"] else ""
    if best is None:
        raise RuntimeError(f"Scenario generation failed: {last}")
    data = best[1]
    data["scenes"].append({"text": "Subscribe for more network security tips!", "keyword": "computer network cables"})
    return data


def advice(stats_text):
    prompt = (
        "You are a YouTube Shorts growth coach. Based on this weekly report, give exactly 3 short, concrete, "
        f"actionable suggestions in English (what to repeat, what to change, posting tips):\n{stats_text}"
    )
    return _ask(prompt, as_json=False, tier="strong")
