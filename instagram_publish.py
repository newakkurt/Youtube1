"""
Instagram Reels yayıncı — Meta Graph API (Instagram Business/Creator hesabı gerektirir).
- IT, Network, Siber Güvenlik, Yapay Zeka ve Uzay/Havacılık Odaklı Otomasyon.
Akış: videoyu IG biçimine çevir -> geçici host'a yükle -> Reels container -> işle -> yayınla.
+ Requests tabanlı doğrudan Instagram Otomatik Takip Modülü (Tarayıcısız / %100 Bulut Uyumlu)
Gerekli env: IG_USER_ID, IG_ACCESS_TOKEN, IG_USERNAME, IG_PASSWORD
"""
import os
import re
import subprocess
import time
import random
import requests
import json
import config

# Reels paylaşımı için doğru endpoint Facebook Graph API'dir
API = "https://graph.instagram.com/v21.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Teknoloji, Network, Siber Güvenlik, Yapay Zeka ve Uzay/Havacılık odaklı sabit hashtag setleri
TECH_HASHTAGS = "\n\n#InformationTechnology #Networking #CyberSecurity #ArtificialIntelligence #SpaceAndAviation #TechInnovation #NetworkEngineering #DevOps #TechReels"


def _get_env():
    user_id = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not user_id or not token:
        raise ValueError("IG_USER_ID veya IG_ACCESS_TOKEN ortam değişkeni eksik!")
    return user_id, token


def _check(resp, step, token):
    """Hata olursa Instagram'ın asıl cevabını (token'sız) mesaja koy."""
    if resp.ok:
        return resp
    body = resp.text.replace(token, "***")[:350]
    raise RuntimeError(f"[{step}] HTTP {resp.status_code}: {body}")


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def make_ig_compatible(src: str) -> str:
    """H.264 + yuv420p + 30fps + AAC 48k stereo + faststart. Ses yoksa sessiz ses ekler."""
    if not os.path.exists(src):
        raise FileNotFoundError(f"Video dosyası bulunamadı: {src}")

    ff = _ffmpeg()
    dst = os.path.splitext(src)[0] + "_ig.mp4"

    probe = subprocess.run([ff, "-hide_banner", "-i", src], capture_output=True, text=True)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*Audio:", probe.stderr))

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += [
        "-map", "0:v:0",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError(f"[ffmpeg] {r.stderr[-300:]}")
    return dst


# ---------- Geçici host'lar (doğrudan mp4 linki verenler) ----------

def _host_litterbox(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "24h"},
            files={"fileToUpload": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


def _host_uguu(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    try:
        return r.json()["files"][0]["url"]
    except Exception:
        return r.text.strip()


def _host_0x0(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://0x0.st",
            files={"file": (os.path.basename(path), f, "video/mp4")},
            data={"expires": "24"},
            headers={"User-Agent": "curl/8.5.0"}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


def _host_catbox(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


HOSTS = (_host_litterbox, _host_uguu, _host_0x0, _host_catbox)


def _is_direct_mp4(url: str) -> str:
    """Linkten ilk baytları çek: MP4 imzası ('ftyp') varsa doğrudan video demektir."""
    try:
        r = requests.get(url, stream=True, timeout=30, allow_redirects=True,
                         headers={"User-Agent": UA, "Range": "bytes=0-63"})
        head = next(r.iter_content(64), b"")
        ctype = r.headers.get("Content-Type", "?")
        status = r.status_code
        r.close()
        if status not in (200, 206):
            return f"HTTP {status}"
        if b"ftyp" not in head[:16]:
            return f"video değil ({ctype})"
        return ""
    except Exception as e:
        return f"erişilemedi: {str(e)[:60]}"


def upload_public(path: str):
    """İlk doğrulanmış doğrudan-MP4 linkini döndür: (url, host_adı)."""
    notes = []
    for fn in HOSTS:
        name = fn.__name__.replace("_host_", "")
        try:
            url = fn(path)
        except Exception as e:
            notes.append(f"{name}: yükleme hatası {str(e)[:60]}")
            continue
        if not url.startswith("http"):
            notes.append(f"{name}: beklenmedik cevap {url[:50]}")
            continue
        why = _is_direct_mp4(url)
        if not why:
            return url, name
        notes.append(f"{name}: {why}")
    raise RuntimeError("Hiçbir host uygun değil -> " + " | ".join(notes))


def publish_reel(video_path: str, caption: str, timeout_s: int = 420) -> str:
    ig_user_id, token = _get_env()

    ig_path = make_ig_compatible(video_path)
    video_url, host = upload_public(ig_path)

    # Açıklamaya otomatik olarak teknoloji, siber güvenlik, AI ve uzay/havacılık etiketlerini ekleyelim
    full_caption = caption.strip() + TECH_HASHTAGS

    r = requests.post(
        f"{API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": full_caption[:2200],
            "access_token": token,
        },
        timeout=60,
    )
    _check(r, "container", token)
    container_id = r.json()["id"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        sr = requests.get(
            f"{API}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        _check(sr, "status", token)
        s = sr.json()
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"[processing] {s} | host={host}")
        time.sleep(6)
    else:
        raise TimeoutError("IG video işleme zaman aşımı")

    p = requests.post(
        f"{API}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    _check(p, "publish", token)
    return p.json()["id"]


def refresh_token() -> str:
    _, token = _get_env()
    r = requests.get(
        f"{API}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": os.environ.get("FB_APP_ID"),
            "client_secret": os.environ.get("FB_APP_SECRET"),
            "fb_exchange_token": token
        },
        timeout=30,
    )
    _check(r, "refresh", token)
    return r.json()["access_token"]


# ---------- Requests Tabanlı Bulut Uyumlu Otomatik Takip Modülü ----------

def run_follow_bot():
    """GitHub Actions (Cloud) için Tarayıcısız API Tabanlı Takip Botu
    - Hedef hesaplar tamamen Bilgi Teknolojileri ve Network odaklı olacak şekilde optimize edilmiştir.
    """
    if os.environ.get("ENABLE_IG_AUTO_FOLLOW", "").strip().lower() != "true":
        print("🛡️ Instagram otomatik takip kapalı. Reels yayınlama bundan etkilenmez.")
        return
    max_daily_follows = getattr(config, "MAX_DAILY_FOLLOWS", 99)
    min_followers = getattr(config, "MIN_FOLLOWER_COUNT", 5000)
    # Hedefler IT, Network, Siber Güvenlik, AI ve Uzay odaklı sayfalara güncellendi
    target_accounts = getattr(config, "TARGET_ACCOUNTS", ["python.hub", "cybersecurity.hub", "nasa", "spacex", "networking_pro"])
    
    username = os.environ.get("IG_USERNAME") or getattr(config, "IG_USERNAME", None)
    password = os.environ.get("IG_PASSWORD") or getattr(config, "IG_PASSWORD", None)

    if not username or not password:
        print("⚠️ IG_USERNAME veya IG_PASSWORD bulunamadı, bot iptal edildi.")
        return

    print("🤖 Instagram API takip botu bulut ortamında başlatılıyor...")
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "X-IG-App-ID": "936619743392459",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    })

    try:
        # 1) Instagram ana sayfasından çerezleri al
        init_res = session.get("https://www.instagram.com/", timeout=20)
        csrftoken = session.cookies.get_dict().get("csrftoken", "")
        
        session.headers.update({
            "X-CSRFToken": csrftoken,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/accounts/login/"
        })

        # 2) Web tabanlı giriş simülasyonu
        login_url = "https://www.instagram.com/api/v1/web/accounts/login/ajax/"
        login_data = {
            "username": username,
            "enc_password": f"#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{password}",
            "queryParams": "{}",
            "optIntoOneTap": "false"
        }
        
        time.sleep(random.uniform(2, 4))
        login_res = session.post(login_url, data=login_data, timeout=20)
        
        try:
            res_json = login_res.json()
        except Exception:
            print(f"⚠️ Instagram yanıtı JSON formatında değil: {login_res.text[:150]}")
            return

        if not res_json.get("authenticated"):
            print(f"❌ Giriş başarısız: {res_json.get('message', 'Bilinmeyen hata / Kontrol noktası')}")
            return

        print("✅ Instagram'a API üzerinden başarıyla giriş yapıldı.")
        followed_count = 0

        # 3) Hedef hesapların kullanıcı ID'lerini çözüp takipçilerini tara
        for target in target_accounts:
            if followed_count >= max_daily_follows:
                break
                
            print(f"🔍 Hedef taranıyor: @{target}")
            profile_res = session.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={target}", timeout=15)
            
            if not profile_res.ok:
                print(f"⚠️ @{target} profiline erişilemedi.")
                continue
                
            try:
                user_data = profile_res.json()["data"]["user"]
                target_id = user_data["id"]
            except Exception:
                continue

            # Hedefin takipçilerini çek
            followers_res = session.get(f"https://www.instagram.com/api/v1/friendships/{target_id}/followers/?count=12", timeout=15)
            if not followers_res.ok:
                continue
                
            followers_list = followers_res.json().get("users", [])
            
            for user in followers_list:
                if followed_count >= max_daily_follows:
                    break
                    
                target_user_id = user["pk"]
                target_username = user["username"]
                
                # Kullanıcı detayını kontrol et (Takipçi sayısı 5000+ mı?)
                detail_res = session.get(f"https://www.instagram.com/api/v1/users/{target_user_id}/info/", timeout=15)
                if detail_res.ok:
                    details = detail_res.json().get("user", {})
                    follower_count = details.get("follower_count", 0)
                    is_following = details.get("friendship_status", {}).get("following", False)
                    
                    if follower_count >= min_followers and not is_following:
                        # Takip Et İstegi At
                        follow_res = session.post(f"https://www.instagram.com/api/v1/friendships/create/{target_user_id}/", timeout=15)
                        if follow_res.ok:
                            followed_count += 1
                            print(f"[+] Takip edildi: @{target_username} (Takipçi: {follower_count}) | Toplam: {followed_count}")
                            time.sleep(random.randint(45, 90))
                        else:
                            print(f"[-] Takip edilemedi: @{target_username}")
                    else:
                        print(f"[-] Pas geçildi: @{target_username} (Takipçi: {follower_count})")
                
                time.sleep(random.randint(5, 10))

        print(f"✨ Instagram takip turu tamamlandı. Bu turda {followed_count} hesap takip edildi.")

    except Exception as e:
        print(f"⚠️ API takip botu hatası: {str(e)[:300]}")
