import json
import os
import sys
import uuid
import requests

import tg
import youtube
from config import *


def load():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else {"offset": 0, "history": [], "items": {}}


def save(state):
    QUEUE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def compose(script):
    tags = [script.get("local_tag", "")] + script.get("global_tags", [])
    tags = ["#" + t.lstrip("#") for t in tags if t]
    desc = script.get("description", "")
    if AFFILIATE_TEXT:
        desc += "\n\n" + AFFILIATE_TEXT
    desc += "\n\n#Shorts " + " ".join(tags)
    return desc, [t.lstrip("#") for t in tags] + ["Shorts"]


def post_instagram(item, path):
    try:
        import instagram_publish
        caption = (item["title"] + "\n\n" + item["description"]).replace("#Shorts", "").strip()
        ig_id = instagram_publish.publish_reel(str(path), caption)
        item["ig_id"] = ig_id
        tg.send(f"📸 Instagram'a yüklendi: {item['title']}")
    except Exception as e:
        tg.send(f"⚠️ Instagram hatası: {str(e)[:400]}")


def post_linkedin(item, path):
    """LinkedIn'e video paylaşır. post_instagram'dan SONRA çağrılmalı (_ig.mp4 dosyasını kullanır)."""
    try:
        from linkedin_post import publish_linkedin
        caption = (item["title"] + "\n\n" + item["description"]).replace("#Shorts", "").strip()
        status = publish_linkedin(str(path), caption)
        tg.send(f"{status}\n{item['title']}")
    except Exception as e:
        tg.send(f"⚠️ LinkedIn hatası: {str(e)[:400]}")


def post_linkedin_status(state):
    """LinkedIn token durumunu kontrol eder ve Telegram'a bildirir."""
    try:
        token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
        if not token:
            tg.send("⚠️ LinkedIn Access Token bulunamadı (Secret eksik).")
            return

        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            tg.send(
                f"🔗 LinkedIn Bağlantısı Başarılı!\n"
                f"İsim: {data.get('name', '?')}\n"
                f"Kullanıcı ID: {data.get('sub', '?')}\n"
                f"Token Durumu: Aktif ✅"
            )
        else:
            tg.send(f"⚠️ LinkedIn Token Hatası ({res.status_code}): {res.text[:300]}")

        try:
            from linkedin_post import token_warning
            warn = token_warning()
            if warn:
                tg.send(f"⚠️ {warn}")
        except Exception:
            pass
    except Exception as e:
        tg.send(f"⚠️ LinkedIn Status Hatası: {str(e)[:400]}")


def generate_one(state):
    import script_gen
    import video_maker

    script = script_gen.generate(state["history"])
    uid = uuid.uuid4().hex[:8]
    OUT.mkdir(exist_ok=True)
    path = video_maker.build(script, OUT / f"{uid}.mp4")
    desc, tags = compose(script)
    title = script["title"]
    state["history"] = (state["history"] + [title])[-100:]
    item = {"title": title, "description": desc, "tags": tags, "status": "pending"}

    if AUTO_APPROVE:
        vid = youtube.upload(path, title, desc, tags)
        item.update(status="published", video_id=vid)
        post_instagram(item, path)
        post_linkedin(item, path)
        tg.send(f"✅ Yayınlandı: {title}\nhttps://youtube.com/shorts/{vid}")
    else:
        file_id, mid = tg.send_video(path, f"{title}\n\n{desc}", uid)
        item.update(file_id=file_id, message_id=mid)
    state["items"][uid] = item


def ig_test(state):
    import script_gen
    import video_maker
    script = script_gen.generate(state["history"])
    OUT.mkdir(exist_ok=True)
    path = video_maker.build(script, OUT / "igtest.mp4")
    desc, tags = compose(script)
    post_instagram({"title": script["title"], "description": desc}, path)


def handle_callback(state, cq):
    action, uid = cq["data"].split(":")
    item = state["items"].get(uid)
    if not item or item["status"] != "pending":
        return tg.answer_cb(cq["id"], "Zaten işlendi")
    if action == "no":
        item["status"] = "rejected"
        tg.answer_cb(cq["id"], "Reddedildi")
        return tg.edit_caption(item["message_id"], f"❌ Reddedildi: {item['title']}")
    tg.answer_cb(cq["id"], "Yükleniyor...")
    path = tg.download(item["file_id"], OUT / f"{uid}.mp4")
    vid = youtube.upload(path, item["title"], item["description"], item["tags"])
    item.update(status="published", video_id=vid)
    post_instagram(item, path)
    post_linkedin(item, path)
    tg.edit_caption(item["message_id"], f"✅ Yayınlandı: {item['title']}\nhttps://youtube.com/shorts/{vid}")


def dispatch_generate():
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    marker = "/.github/workflows/"
    wf = ref.split(marker)[-1].split("@")[0] if marker in ref else "generate.yml"
    r = requests.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"mode": "generate"}}, timeout=30)
    return r.status_code == 204


def handle_message(state, msg):
    cmd = (msg.get("text") or "").split()[0].lower() if msg.get("text") else ""
    if cmd in ("/yardim", "/yardım", "/start"):
        tg.send("Komutlar:\n/durum - kuyruk özeti\n/trend - güncel konu başlıkları\n/analiz - haftalık rapor\n"
                "/video - hemen yeni video üret\n/iptal - bekleyenleri iptal et\n"
                "/oneriler - hedef video ve yorum önerileri\n"
                "Not: komutlar ~30 dk içinde cevaplanır.")
    elif cmd == "/durum":
        counts = {}
        for it in state["items"].values():
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        last = [it["title"] for it in list(state["items"].values())[-5:]]
        tg.send(f"Durum: {counts}\nSon 5:\n" + "\n".join(f"- {t}" for t in last))
    elif cmd == "/trend":
        import script_gen
        tg.send("🔥 Güncel başlıklar:\n" + "\n".join(f"- {h}" for h in script_gen.headlines(10)))
    elif cmd == "/analiz":
        tg.send(youtube.stats(7))
    elif cmd == "/video":
        tg.send("🎬 Üretim başladı, birkaç dakikaya gelir." if dispatch_generate() else "⚠️ Üretim tetiklenemedi (Actions izni?).")
    elif cmd == "/oneriler":
        try:
            from lead_finder import run_lead_finder
            run_lead_finder()
        except Exception as e:
            tg.send(f"⚠️ Lead Finder hatası: {e}")
    elif cmd == "/iptal":
        n = 0
        for it in state["items"].values():
            if it["status"] == "pending":
                it["status"] = "cancelled"
                n += 1
        tg.send(f"{n} bekleyen iptal edildi.")


def process(state):
    OUT.mkdir(exist_ok=True)
    for u in tg.updates(state["offset"]):
        state["offset"] = u["update_id"] + 1
        if "callback_query" in u:
            cq = u["callback_query"]
            if str(cq["message"]["chat"]["id"]) == TELEGRAM_CHAT_ID:
                handle_callback(state, cq)
        elif "message" in u and str(u["message"]["chat"]["id"]) == TELEGRAM_CHAT_ID:
            handle_message(state, u["message"])


def report():
    import script_gen
    text = youtube.stats(7)
    try:
        text += "\n\n💡 Öneriler:\n" + script_gen.advice(text)
    except Exception:
        pass
    tg.send(text)


def run_lead():
    from lead_finder import run_lead_finder
    run_lead_finder()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "generate"
    state = load()

    modes = {
        "generate": lambda: generate_one(state),
        "process": lambda: process(state),
        "report": report,
        "igtest": lambda: ig_test(state),
        "lead": run_lead,
        "li_status": lambda: post_linkedin_status(state),
    }

    try:
        if mode in modes:
            modes[mode]()
        else:
            tg.send(f"⚠️ Bilinmeyen mod: {mode}")
    except Exception as e:
        tg.send(f"⚠️ Hata ({mode}): {str(e)[:500]}")
        raise
    finally:
        save(state)
