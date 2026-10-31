import json
import os
import sys
import uuid
import traceback
import requests
from moviepy import VideoFileClip

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
        item["instagram"] = {"status": "published", "media_id": ig_id}
        tg.send(f"📸 Instagram'a yüklendi: {item['title']}")
    except Exception as e:
        item["instagram"] = {"status": "failed", "error": str(e)[:300]}
        tg.send(f"⚠️ Instagram hatası: {str(e)[:400]}")


def post_linkedin(item, path):
    """LinkedIn'e video paylaşır. post_instagram'dan SONRA çağrılmalı (_ig.mp4 dosyasını kullanır)."""
    try:
        from linkedin_post import publish_linkedin
        caption = (item["title"] + "\n\n" + item["description"]).replace("#Shorts", "").strip()
        status = publish_linkedin(str(path), caption)
        item["linkedin"] = {"status": "published", "result": str(status)[:180]}
        tg.send(f"{status}\n{item['title']}")
    except Exception as e:
        item["linkedin"] = {"status": "failed", "error": str(e)[:300]}
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


def upload_youtube(path, title, desc, tags):
    """YouTube'a yükler. Hataları hem Actions loguna hem Telegram'a yazar."""
    try:
        video_id = youtube.upload(path, title, desc, tags)
        print(f"YOUTUBE_UPLOAD_OK: video_id={video_id}", flush=True)
        return video_id
    except Exception as e:
        msg = str(e)
        # YouTube hatası daha önce sadece Telegram'a yazıldığı için Actions yeşil
        # görünüyordu. Ayrıntıyı loga da yaz ki gerçek API sebebi bulunabilsin.
        print(f"YOUTUBE_UPLOAD_FAILED: {type(e).__name__}: {msg}", flush=True)
        if getattr(e, "content", None):
            try:
                print("YOUTUBE_API_ERROR_BODY:", e.content.decode("utf-8", errors="replace")[:2000], flush=True)
            except Exception:
                pass
        traceback.print_exc()
        if "invalid_grant" in msg or "RefreshError" in type(e).__name__:
            tg.send("🔑 YouTube token'ı geçersiz (invalid_grant).\n"
                    "1) get_refresh_token.py ile yeni token al\n"
                    "2) GitHub Secrets → YT_REFRESH_TOKEN'ı güncelle\n"
                    "3) Google Cloud → OAuth consent screen → 'In production' yap "
                    "(Testing'de token 7 günde ölür)")
        else:
            tg.send(f"⚠️ YouTube yükleme hatası: {msg[:400]}")
        return None


def generate_one(state):
    import script_gen
    import video_maker

    script = script_gen.generate(state["history"])
    uid = uuid.uuid4().hex[:8]
    OUT.mkdir(exist_ok=True)
    path = video_maker.build(script, OUT / f"{uid}.mp4")
    rendered_video = VideoFileClip(str(path))
    duration_seconds = round(float(rendered_video.duration), 2)
    rendered_video.close()
    desc, tags = compose(script)
    title = script["title"]
    state["history"] = (state["history"] + [title])[-100:]
    item = {"title": title, "description": desc, "tags": tags, "status": "pending",
            "hook": script["scenes"][0]["text"], "duration_seconds": duration_seconds,
            "youtube": {"status": "pending"}, "instagram": {"status": "pending"},
            "linkedin": {"status": "pending"}}
    if not 25 <= duration_seconds <= 45:
        tg.send(f"⚠️ Video süresi hedef aralığın dışında: {duration_seconds} sn (hedef 25–45 sn). Yayın akışı durdurulmadı.")

    if AUTO_APPROVE:
        vid = upload_youtube(path, title, desc, tags)
        post_instagram(item, path)   # YouTube başarısız olsa bile Instagram/LinkedIn devam eder
        post_linkedin(item, path)
        if vid:
            item.update(status="published", video_id=vid)
            item["youtube"] = {"status": "published", "video_id": vid}
            tg.send(f"✅ Yayınlandı: {title}\nhttps://youtube.com/shorts/{vid}")
        else:
            # Video kaybolmasın: Telegram'a koy, token düzelince ✅ ile sadece YouTube'a yüklenir
            file_id, mid = tg.send_video(path, f"⚠️ YouTube'a yüklenemedi\n{title}\n\n{desc}", uid)
            item.update(status="yt_failed", file_id=file_id, message_id=mid)
            item["youtube"] = {"status": "failed"}
    else:
        file_id, mid = tg.send_video(path, f"{title}\n\n{desc}", uid)
        item.update(file_id=file_id, message_id=mid)
    state["items"][uid] = item



def generate_long_one(state):
    """Manually generate and publish a 16:9 long-form YouTube video."""
    if not AUTO_APPROVE:
        tg.send("ℹ️ Uzun video modu şu an otomatik yayın gerektiriyor. AUTO_APPROVE=true olmadan yayınlanmadı.")
        return
    import script_gen
    import video_maker
    script = script_gen.generate_long(state["history"])
    uid = "long_" + uuid.uuid4().hex[:8]
    OUT.mkdir(exist_ok=True)
    path, chapters = video_maker.build_long(script, OUT / f"{uid}.mp4")
    long_tags = [script.get("local_tag", "")] + script.get("global_tags", [])
    tags = [str(t).lstrip("#") for t in long_tags if t][:15]
    desc = (script.get("description", "") + "\n\nChapters:\n" + chapters + "\n\n" + " ".join("#" + t for t in tags))[:4900]
    title = script["title"]
    rendered = VideoFileClip(str(path))
    duration_seconds = round(float(rendered.duration), 2)
    rendered.close()
    item = {
        "title": title, "description": desc, "tags": tags, "status": "pending",
        "format": "long", "duration_seconds": duration_seconds,
        "youtube": {"status": "pending"},
        "instagram": {"status": "skipped", "reason": "16:9 long-form video"},
        "linkedin": {"status": "skipped", "reason": "long-form distribution not enabled"}
    }
    if not 300 <= duration_seconds <= 420:
        tg.send(f"⚠️ Uzun video süresi hedef 5–7 dk dışında: {duration_seconds} sn. Yayın kararı devam ediyor.")
    vid = upload_youtube(path, title, desc, tags)
    if vid:
        item.update(status="published", video_id=vid)
        item["youtube"] = {"status": "published", "video_id": vid}
        tg.send(f"✅ Uzun video yayınlandı: {title}\nhttps://youtube.com/watch?v={vid}")
    else:
        item["status"] = "yt_failed"
        item["youtube"] = {"status": "failed"}
        tg.send(f"⚠️ Uzun video YouTube'a yüklenemedi: {title}")
    state["history"] = (state["history"] + [title])[-100:]
    state["items"][uid] = item

def ig_test(state):
    import script_gen
    import video_maker
    script = script_gen.generate(state["history"])
    OUT.mkdir(exist_ok=True)
    path = video_maker.build(script, OUT / "igtest.mp4")
    desc, tags = compose(script)
    post_instagram({"title": script["title"], "description": desc}, path)


def li_test(state):
    import script_gen
    import video_maker
    script = script_gen.generate(state["history"])
    OUT.mkdir(exist_ok=True)
    path = video_maker.build(script, OUT / "litest.mp4")
    desc, tags = compose(script)
    post_linkedin({"title": script["title"], "description": desc}, path)


def handle_callback(state, cq):
    action, uid = cq["data"].split(":")
    item = state["items"].get(uid)
    if not item or item["status"] not in ("pending", "yt_failed"):
        return tg.answer_cb(cq["id"], "Zaten işlendi")
    if action == "no":
        item["status"] = "rejected"
        tg.answer_cb(cq["id"], "Reddedildi")
        return tg.edit_caption(item["message_id"], f"❌ Reddedildi: {item['title']}")
    tg.answer_cb(cq["id"], "Yükleniyor...")
    path = tg.download(item["file_id"], OUT / f"{uid}.mp4")
    vid = upload_youtube(path, item["title"], item["description"], item["tags"])
    if not vid:
        return  # durum aynı kalır, token düzelince tekrar onaylanabilir
    already_posted = item["status"] == "yt_failed"  # Instagram/LinkedIn zaten gitti, tekrar etme
    item.update(status="published", video_id=vid)
    item["youtube"] = {"status": "published", "video_id": vid}
    if not already_posted:
        post_instagram(item, path)
        post_linkedin(item, path)
    tg.edit_caption(item["message_id"], f"✅ Yayınlandı: {item['title']}\nhttps://youtube.com/shorts/{vid}")


def dispatch_generate(mode="generate"):
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    marker = "/.github/workflows/"
    wf = ref.split(marker)[-1].split("@")[0] if marker in ref else "generate.yml"
    r = requests.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"mode": mode}}, timeout=30)
    return r.status_code == 204


def handle_message(state, msg):
    cmd = (msg.get("text") or "").split()[0].lower() if msg.get("text") else ""
    if cmd in ("/yardim", "/yardım", "/start"):
        tg.send("Komutlar:\n/durum - kuyruk özeti\n/trend - güncel konu başlıkları\n/analiz - haftalık rapor\n"
                "/video - yeni Shorts üret\n/uzunvideo - 5-7 dakikalık video üret\n/iptal - bekleyenleri iptal et\n"
                "/oneriler - hedef video ve yorum önerileri\n"
                "Not: komutlar ~30 dk içinde cevaplanır.")
    elif cmd == "/durum":
        counts = {}
        platforms = {"youtube": {}, "instagram": {}, "linkedin": {}}
        for it in state["items"].values():
            counts[it["status"]] = counts.get(it["status"], 0) + 1
            for platform in platforms:
                status = (it.get(platform) or {}).get("status", "unknown")
                platforms[platform][status] = platforms[platform].get(status, 0) + 1
        last = [it["title"] for it in list(state["items"].values())[-5:]]
        platform_text = "\n".join(
            f"{name}: {status_counts}" for name, status_counts in platforms.items()
        )
        tg.send(f"Genel durum: {counts}\nPlatformlar:\n{platform_text}\nSon 5:\n" + "\n".join(f"- {t}" for t in last))
    elif cmd == "/trend":
        import script_gen
        tg.send("🔥 Güncel başlıklar:\n" + "\n".join(f"- {h}" for h in script_gen.headlines(10)))
    elif cmd == "/analiz":
        tg.send(youtube.stats(7))
    elif cmd == "/video":
        tg.send("🎬 Shorts üretimi başladı." if dispatch_generate("generate") else "⚠️ Üretim tetiklenemedi (Actions izni?).")
    elif cmd == "/uzunvideo":
        tg.send("🎬 Uzun video üretimi başladı." if dispatch_generate("long") else "⚠️ Uzun video tetiklenemedi (Actions izni?).")
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


def report(state):
    import script_gen
    text = youtube.stats(7)
    try:
        hooks = {it["video_id"]: it["hook"] for it in state["items"].values() if it.get("video_id") and it.get("hook")}
        print("performance.json:", youtube.save_performance(hooks), "kayıt")
    except Exception as e:
        print("save_performance hatası:", str(e)[:200])
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
        "long": lambda: generate_long_one(state),
        "process": lambda: process(state),
        "report": lambda: report(state),
        "igtest": lambda: ig_test(state),
        "lead": run_lead,
        "li_status": lambda: post_linkedin_status(state),
        "ytcheck": lambda: tg.send(youtube.check_token()[1]),
        "litest": lambda: li_test(state),
        "yt_subs": lambda: __import__("youtube_subscriptions").run(),
        "ig_follow": lambda: print("🛡️ Instagram otomatik takip kapalı: resmî Instagram API bu işlemi desteklemiyor."),
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

