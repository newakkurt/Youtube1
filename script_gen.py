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
    "openai/gpt-oss-120b,openai/gpt-oss-20b",
).split(",") if m.strip()]
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "")  # boşsa OpenRouter atlanır; ücretsiz güncel bir model slug'ı yaz
GROQ_KEY = env("GROQ_API_KEY")
OPENROUTER_KEY = env("OPENROUTER_API_KEY")

# Router: "fast" işlerde bu işaretleri taşıyan küçük modeller öne alınır
FAST_MARKS = ("8b", "mini", "20b")
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
PERF_FILE = ROOT / "performance.json"  # [{"title": "...", "views": 123}, ...]
LINKEDIN_HISTORY = ROOT / "linkedin_history.json"

# Konuyla uyumlu stok görüntü anahtarları (video_maker.py'deki liste ile aynı olmalı)
STOCK_KEYWORDS = [
    "hands typing laptop keyboard", "network switch cables", "server rack", "laptop code screen",
    "ethernet cable closeup", "data center corridor", "engineer laptop",
]
LONG_KINDS = {"title", "bullets", "terminal", "topology"}

_dead = set()


# ---------- Haber başlıkları / not ----------
def headlines(n=8):
    q, loc = "network security OR cybersecurity OR networking when:2d", "hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{loc}")
    return [e.title for e in feed.entries[:n]]


_STOP = {"your", "with", "from", "that", "this", "network", "switch", "traffic", "silently", "hidden",
         "why", "how", "what", "when", "good", "kills", "causes", "fix", "repair", "unlock"}


def pick_note():
    """Notların çoğunu en çok izlenen konulara yaklaştırır; %20'si rastgele (keşif)."""
    lines = [l.strip() for l in (ROOT / "field_notes.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    if random.random() < 0.2:
        return random.choice(lines)
    try:
        rows = json.loads(PERF_FILE.read_text(encoding="utf-8"))
        top = sorted(rows, key=lambda r: r.get("views", 0), reverse=True)[:8]
        words = {w.lower() for r in top for w in re.findall(r"[A-Za-z]{4,}", r.get("title", ""))} - _STOP
        weights = [1 + 3 * sum(w in l.lower() for w in words) for l in lines]
        return random.choices(lines, weights=weights)[0]
    except Exception:
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
    """performance.json'dan medyanın 1.5 katını aşan, en çok izlenen n kayıt. Yoksa boş liste."""
    try:
        rows = json.loads(PERF_FILE.read_text(encoding="utf-8"))
        # Kanal İngilizceye geçti: eski Türkçe başlıkları örnek olarak verme
        rows = [r for r in rows if r.get("title") and not re.search(r"[çğıöşüÇĞİÖŞÜ]", r["title"])]
        if not rows:
            return []
        views = sorted(r.get("views", 0) for r in rows)
        med = views[len(views) // 2]
        top = [r for r in sorted(rows, key=lambda r: r.get("views", 0), reverse=True)
               if r.get("views", 0) >= max(30, med * 1.5)]
        return top[:n]
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
    if OPENROUTER_KEY and OPENROUTER_MODEL:
        chain.append((
            f"openrouter:{OPENROUTER_MODEL}",
            lambda p: _chat("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, OPENROUTER_MODEL, p),
        ))
    chain = [c for c in chain if c[0] not in _dead]
    # işaret kelime başında olmalı: "gpt-oss-120b" içindeki "20b" ve "gemini" içindeki "mini" hızlı model sayılmaz
    is_fast = lambda c: any(re.search(r"(?<![a-z0-9])" + re.escape(mk), c[0]) for mk in FAST_MARKS)
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
    prompt = f"""You are a strict YouTube editor and fact-checker for a network & cybersecurity channel.
Title: {data['title']}
Script: {script}
Verified facts available: {facts or 'none'}
Judge the draft and return ONLY JSON with these keys:
"hook": integer 1-10 (is the first line scroll-stopping and curiosity-driven?),
"fact_risk": integer 1-10 (10 = very likely invented or wrong numbers, dates, CVE ids, CLI commands or product claims),
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


def _win_block(win):
    if not win:
        return ""
    block = (
        "Our best-performing titles so far (same topic family and problem+fix pattern is GOOD; "
        f"but cover a NEW angle, do NOT copy them): {[r['title'] for r in win]}\n"
    )
    hooks = [r["hook"] for r in win if r.get("hook")]
    if hooks:
        block += f"Opening hooks of our best videos (learn the pattern, do NOT copy): {hooks}\n"
    return block


# ---------- Senaryo (Shorts) ----------
def _draft(note, facts, win, history, feedback):
    facts_block = (
        f"Verified facts (CISA Known Exploited Vulnerabilities). Any specific CVE, date or vendor you mention MUST come from here:\n{facts}\n"
        if facts else ""
    )
    prompt = f"""You write 25-35 second YouTube Shorts voiceover scripts for a channel about: Network & Cybersecurity, aimed at network engineers.
All output language: English.
Build the video around this real field note from the channel owner. It is the unique angle: keep its meaning, and do not invent personal anecdotes beyond it:
"{note}"
Trending context (use only if clearly relevant): {headlines()}
{facts_block}{_win_block(win)}Do NOT repeat these earlier titles or their angle: {history[-30:]}
Rules: fully original wording, no quotes from copyrighted sources, no false claims. Never invent statistics, CVE numbers, dates or product details; if unsure, speak in general terms. 4 scenes total, each 8-20 words, simple spoken language. Max 80 words in total.
Title formula: a real problem engineers hit + the fix, using a term they would search for (e.g. "err-disable", "DAI drops traffic", "dry-run"). Max 70 chars, honest, specific. Do NOT start with the same word as the last 5 titles.
Scene 1 is the hook (max 12 words): a concrete mistake or rule ("Stop doing X", "Always do Y"), never a vague question.
Scene 2-3: name the exact feature, setting or command. Scene 4: one-line rule to remember.
Each scene has an on-screen "caption" (max 9 words): a sharp imperative rule or fact that contains the key term (VLAN, DAI, err-disable...). It is read on screen, so it must make sense without audio.
Each scene "keyword" MUST be chosen ONLY from this list: {STOCK_KEYWORDS}
{feedback}
Return ONLY JSON, no markdown:
{{"title": "...",
 "scenes": [{{"text": "spoken line", "caption": "on-screen rule", "keyword": "one item from the list"}}],
 "local_tag": "one hashtag in English, no spaces",
 "global_tags": ["4 broad English hashtags, no spaces"],
 "description": "2 sentences"}}"""
    data = json.loads(_ask(prompt, tier="strong"))
    assert data["scenes"] and data["title"]
    for s in data["scenes"]:
        if s.get("keyword") not in STOCK_KEYWORDS:
            s["keyword"] = random.choice(STOCK_KEYWORDS)
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
        feedback = ("A previous draft had these problems, fix them: " + "; ".join(v["issues"])) if v["issues"] else ""
    if best is None:
        raise RuntimeError(f"Scenario generation failed: {last}")
    data = best[1]
    data["scenes"].append({
        "text": "Which of these have you hit in production? Tell me in the comments.",
        "caption": "Hit this in production? Comment below.",
        "keyword": "network switch cables",
    })
    return data


# ---------- Senaryo (uzun format, 16:9) ----------
def _draft_long(note, win, history, feedback):
    prompt = f"""You write a 5-7 minute YouTube long-form voiceover script for a Network & Cybersecurity channel aimed at network engineers. All output language: English.
Build it around this real field note from the channel owner. Keep its meaning; do not invent personal anecdotes beyond it:
"{note}"
{_win_block(win)}Do NOT repeat these earlier titles or their angle: {history[-30:]}
Structure, exactly 9 scenes in this order:
1 title (hook: the real problem engineers hit), 2 bullets (symptoms), 3 bullets (why it happens), 4 topology (where in the network it happens, highlight the problem node), 5 terminal (the correct configuration), 6 terminal (verification show commands + what to look for), 7 bullets (common mistakes), 8 bullets (3-point recap), 9 title (closing: ask viewers one concrete question to answer in the comments).
Each scene: "text" = spoken narration of 55-85 words, simple spoken language. Total 500-750 words.
Accuracy rules: use only real, standard CLI commands (Cisco IOS style unless the note says another vendor). Never invent statistics, CVE numbers, dates or product claims. If unsure about a command or output, keep it general. Terminal "lines" are 4-10 short lines (max 70 chars each), commands shown with a prompt like "Switch(config-if)# ...".
Title formula: a real problem + the fix, a term engineers search for, max 70 chars, honest.
Visual fields per scene: "heading" (max 60 chars), plus "bullets" (3-5 short items) for bullets, "lines" for terminal, "nodes" (3-5 names), "highlight" (index of the problem node) and "note" (one sentence) for topology.
{feedback}
Return ONLY JSON, no markdown:
{{"title": "...",
 "description": "3 sentences",
 "local_tag": "one hashtag, no spaces",
 "global_tags": ["4 broad hashtags, no spaces"],
 "scenes": [{{"kind": "title|bullets|terminal|topology", "text": "...", "heading": "..."}}]}}"""
    data = json.loads(_ask(prompt, tier="strong"))
    good = []
    for s in data["scenes"]:
        k = s.get("kind")
        if k not in LONG_KINDS or not s.get("text"):
            continue
        if (k == "bullets" and not s.get("bullets")) or (k == "terminal" and not s.get("lines")) \
                or (k == "topology" and not s.get("nodes")):
            continue
        good.append(s)
    assert data.get("title") and len(good) >= 7, "long script too short or malformed"
    data["scenes"] = good
    return data


def generate_long(history):
    note, win = pick_note(), winners()
    feedback, best, last = "", None, None
    for attempt in range(3):
        try:
            data = _draft_long(note, win, history, feedback)
        except Exception as e:
            last = e
            continue
        v = review(data, "")
        score = v["hook"] - v["fact_risk"]
        print(f"Long review #{attempt + 1}: hook={v['hook']} fact_risk={v['fact_risk']} issues={v['issues']}")
        if best is None or score > best[0]:
            best = (score, data)
        if v["hook"] >= 7 and v["fact_risk"] <= 3:
            break
        feedback = ("A previous draft had these problems, fix them: " + "; ".join(v["issues"])) if v["issues"] else ""
    if best is None:
        raise RuntimeError(f"Long script generation failed: {last}")
    return best[1]


# ---------- LinkedIn: genel IT / AI / iş dünyası, EN + TR ----------
# (konu adı, Google News arama sorgusu)
LINKEDIN_TOPICS = [
    ("AI at work", "artificial intelligence AI agents enterprise productivity"),
    ("IT careers", "IT jobs careers skills engineers hiring"),
    ("Cybersecurity", "cybersecurity breach ransomware enterprise"),
    ("Automation", "automation DevOps infrastructure as code network automation"),
    ("Cloud & infrastructure", "cloud data center infrastructure outage"),
    ("Industrial IT", "industrial OT IT manufacturing smart factory"),
    ("Tech & business", "technology business trends enterprise IT"),
]


def news(query, n=6):
    """Konu bazlı son 3 günün haber başlıkları (Google News RSS). Hata olursa boş liste."""
    try:
        q = f"{query} when:3d"
        feed = feedparser.parse(
            f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
        )
        return [e.title for e in feed.entries[:n]]
    except Exception:
        return []


def _li_history():
    try:
        return json.loads(LINKEDIN_HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def make_linkedin_bilingual():
    """Resimli LinkedIn postu için içerik: kart metni + post metni, İngilizce ve Türkçe.
    Dict döndürür: topic, card_en, card_tr, points_en, points_tr, post_en, post_tr, hashtags, alt_text."""
    prev = _li_history()[-20:]
    recent_topics = [p.split("|")[0] for p in prev[-3:]]
    pool = [t for t in LINKEDIN_TOPICS if t[0] not in recent_topics] or LINKEDIN_TOPICS
    topic, query = random.choice(pool)
    heads = news(query)
    prompt = f"""You write bilingual (English + Turkish) LinkedIn posts for a network/IT engineer who works at a large manufacturing company. The audience is IT professionals, engineers and managers in Turkey and abroad.
Topic today: {topic}
Recent headlines for context (real, from the last days): {heads or 'none available'}
Rules:
- Pick ONE relevant headline or trend and give a practical, grounded takeaway for IT professionals. If no headline fits, write an evergreen insight about the topic.
- Never state facts, numbers, quotes, dates or company claims beyond what the headline itself says. No invented personal stories. No hype, no clickbait.
- Professional first-person voice. Light perspective of an engineer in an industrial environment is fine, but no made-up anecdotes.
- Turkish must be natural and fluent (not word-for-word); keep common technical terms in English.
- Do NOT resemble these earlier posts: {prev}
Return ONLY JSON, no markdown:
{{"card_en": "image headline, max 80 chars",
 "card_tr": "Turkish version of the image headline, max 85 chars",
 "points_en": ["3 key points, each max 55 chars"],
 "points_tr": ["same 3 points in Turkish, each max 60 chars"],
 "post_en": "English post, 450-800 chars, short 1-2 line paragraphs separated by blank lines, no hashtags, ends with ONE concrete question",
 "post_tr": "Turkish post (same message), 450-800 chars, same structure, ends with the same question in Turkish",
 "hashtags": ["max 4 English hashtags, no spaces"],
 "alt_text": "one-sentence English image description"}}"""
    data = json.loads(_ask(prompt, tier="strong"))
    for k in ("card_en", "card_tr", "post_en", "post_tr"):
        assert data.get(k), f"missing {k}"
    data["points_en"] = [str(p)[:70] for p in data.get("points_en", [])][:3]
    data["points_tr"] = [str(p)[:75] for p in data.get("points_tr", [])][:3]
    data["hashtags"] = " ".join("#" + str(t).strip().lstrip("#").replace(" ", "") for t in data.get("hashtags", [])[:4])
    data["alt_text"] = data.get("alt_text") or data["card_en"]
    data["topic"] = topic
    LINKEDIN_HISTORY.write_text(
        json.dumps((_li_history() + [f"{topic}|{data['card_en'][:70]}"])[-60:], ensure_ascii=False), encoding="utf-8"
    )
    return data


def linkedin_text_from(data):
    """İngilizce + Türkçe tek post metni."""
    return (f"{data['post_en'].strip()}\n\n——— Türkçe ———\n\n{data['post_tr'].strip()}\n\n{data.get('hashtags', '')}").strip()


def bilingual_caption(title, description=""):
    """Video postu için EN + TR açıklama. Başarısız olursa İngilizce başlığa düşer."""
    prompt = f"""Write a short bilingual LinkedIn caption for a video. Video title: "{title}". Video description: "{description}".
Rules: do NOT add technical claims, numbers or commands that are not in the title/description. English 200-350 chars, then the same message in natural Turkish (keep technical terms in English). Each ends with the SAME short question to engineers (asked in that language). No emoji, max 3 hashtags in total at the very end.
Return ONLY JSON: {{"en": "...", "tr": "...", "hashtags": ["max 3 English hashtags"]}}"""
    try:
        d = json.loads(_ask(prompt, tier="fast"))
        tags = " ".join("#" + str(t).strip().lstrip("#").replace(" ", "") for t in d.get("hashtags", [])[:3])
        return f"{d['en'].strip()}\n\n——— Türkçe ———\n\n{d['tr'].strip()}\n\n{tags}".strip()
    except Exception as e:
        print("Bilingual caption failed:", str(e)[:150])
        return f"{title}\n\n{description}".strip()


def advice(stats_text):
    prompt = (
        "You are a YouTube Shorts growth coach. Based on this weekly report, give exactly 3 short, concrete, "
        f"actionable suggestions in English (what to repeat, what to change, posting tips):\n{stats_text}"
    )
    return _ask(prompt, as_json=False, tier="strong")
