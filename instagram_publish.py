"""
Instagram Reels yayıncı — Meta Graph API (Instagram Business/Creator hesabı gerektirir).
Akış: videoyu IG biçimine çevir -> geçici host'a yükle -> Reels container -> işle -> yayınla.
+ Selenium tabanlı gelişmiş otomatik takip botu entegre edilmiştir.
Gerekli env: IG_USER_ID, IG_ACCESS_TOKEN, IG_USERNAME, IG_PASSWORD
"""
import os
import re
import subprocess
import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import config

# Reels paylaşımı için doğru endpoint Facebook Graph API'dir
API = "https://graph.instagram.com/v21.0"
UA = "Mozilla/5.0 (compatible; reels-bot/1.0)"


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

    # 0) IG biçimine çevir
    ig_path = make_ig_compatible(video_path)

    # 1) Videoyu doğrulanmış public linke koy
    video_url, host = upload_public(ig_path)

    # 2) Reels container oluştur
    r = requests.post(
        f"{API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "access_token": token,
        },
        timeout=60,
    )
    _check(r, "container", token)
    container_id = r.json()["id"]

    # 3) Instagram videoyu çekip işleyene kadar bekle
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

    # 4) Yayınla
    p = requests.post(
        f"{API}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    _check(p, "publish", token)
    return p.json()["id"]


def refresh_token() -> str:
    """Token yenileme fonksiyonu."""
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


# ---------- Selenium Otomatik Takip Modülü ----------

def human_delay(min_s=45, max_s=90):
    """İnsansı hareket ve algoritmaya takılmama için rastgele bekleme"""
    sleep_time = random.randint(min_s, max_s)
    time.sleep(sleep_time)


def parse_follower_count(text):
    """'5.4K', '1.2M', '5,400' vb. ifadeleri tamsayıya çevirir."""
    if not text:
        return 0
    text = text.upper().strip().replace(',', '')
    try:
        if 'K' in text:
            return int(float(text.replace('K', '')) * 1000)
        elif 'M' in text:
            return int(float(text.replace('M', '')) * 1000000)
        elif 'B' in text:
            return int(float(text.replace('B', '')) * 1000000000)
        else:
            return int(re.sub(r'[^\d]', '', text))
    except Exception:
        return 0


def check_and_follow_user(driver, username, min_followers=5000):
    """Kullanıcının profilini inceleyip 5000'den fazla takipçisi varsa takip eder."""
    driver.get(f"https://www.instagram.com/{username}/")
    time.sleep(random.randint(5, 8))
    
    try:
        follower_element = driver.find_element(By.XPATH, "//header//ul/li[2]//span")
        follower_text = follower_element.get_attribute("title") or follower_element.text
        follower_count = parse_follower_count(follower_text)
        
        if follower_count >= min_followers:
            follow_button = driver.find_element(
                By.XPATH, "//button[contains(text(), 'Takip Et') or contains(text(), 'Follow')]"
            )
            follow_button.click()
            print(f"[+] Takip edildi: @{username} (Takipçi Sayısı: {follower_count})")
            return True
        else:
            print(f"[-] Pas geçildi: @{username} (Takipçi < {min_followers}: {follower_count})")
            return False
            
    except Exception as e:
        print(f"[!] Pas geçildi/Zaten takip ediliyor: @{username}")
        return False


def get_candidates_from_target(driver, target_username):
    """Hedef hesabın profilinden takipçi/önerilen kullanıcı adlarını çeker."""
    candidates = []
    try:
        driver.get(f"https://www.instagram.com/{target_username}/")
        time.sleep(6)
        
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if href and "instagram.com/" in href:
                parts = [p for p in href.split("/") if p]
                if len(parts) >= 4:
                    user = parts[3]
                    if user not in candidates and user not in ["explore", "reels", "direct", "accounts", target_username]:
                        candidates.append(user)
    except Exception as e:
        print(f"⚠️ {target_username} taranırken hata: {e}")
    return candidates


def run_follow_bot():
    """GitHub Actions (Headless) ortamı için Gelişmiş Gizli Takip Botu"""
    max_daily_follows = getattr(config, "MAX_DAILY_FOLLOWS", 99)
    min_followers = getattr(config, "MIN_FOLLOWER_COUNT", 5000)
    target_accounts = getattr(config, "TARGET_ACCOUNTS", ["github", "python.hub", "nature"])
    
    username = os.environ.get("IG_USERNAME") or getattr(config, "IG_USERNAME", None)
    password = os.environ.get("IG_PASSWORD") or getattr(config, "IG_PASSWORD", None)

    if not username or not password:
        print("⚠️ IG_USERNAME veya IG_PASSWORD bulunamadı, bot iptal edildi.")
        return

    print("🤖 Instagram takip botu gizli modda başlatılıyor...")
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    
    wait = WebDriverWait(driver, 20)
    followed_count = 0

    try:
        driver.get("https://www.instagram.com/accounts/login/?hl=en")
        time.sleep(7)
        
        try:
            cookie_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Allow') or contains(text(), 'Accept') or contains(text(), 'Kabul')]")
            cookie_btn.click()
            print("🍪 Çerez bildirimi kapatıldı.")
            time.sleep(3)
        except Exception:
            pass

        username_input = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
        
        username_input.clear()
        for char in username:
            username_input.send_keys(char)
            time.sleep(random.uniform(0.1, 0.3))
            
        time.sleep(1)
        
        password_input.clear()
        for char in password:
            password_input.send_keys(char)
            time.sleep(random.uniform(0.1, 0.3))
            
        time.sleep(2)
        
        login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
        login_button.click()
        
        print("⏳ Giriş yapılıyor, bekleniyor...")
        time.sleep(12)
        
        current_url = driver.current_url
        if "login" in current_url:
            print("❌ Giriş başarısız oldu! Instagram güvenlik duvarı veya şifre kontrolü takıldı.")
            return
            
        print("✅ Instagram'a başarıyla giriş yapıldı.")
        
        for target in target_accounts:
            if followed_count >= max_daily_follows:
                break
                
            print(f"🔍 Hedef inceleniyor: @{target}")
            candidates = get_candidates_from_target(driver, target)
            
            for candidate in candidates:
                if followed_count >= max_daily_follows:
                    break
                    
                is_followed = check_and_follow_user(driver, candidate, min_followers=min_followers)
                if is_followed:
                    followed_count += 1
                    human_delay(45, 90)
                else:
                    time.sleep(random.randint(5, 10))

        print(f"✨ Instagram takip turu tamamlandı. Bu turda {followed_count} hesap takip edildi.")
        
    except Exception as e:
        print(f"⚠️ Instagram takip botu hatası: {str(e)[:300]}")
    finally:
        driver.quit()
