# shorts-bot — sıfır maliyetli YouTube Shorts otomasyonu

Akış: GitHub Actions (cron) → Gemini senaryo → Edge-TTS ses → Pexels görüntü → MoviePy video
→ Telegram'da onay (veya tam otomatik) → YouTube upload → Pazar günü haftalık rapor.

## Kurulum
1. Repo'yu GitHub'a yükle (public önerilir: Actions dakikası sınırsız. Private ise process.yml cron'unu saatlik yap).
2. Bilgisayarında: `pip install google-auth-oauthlib` → `python get_refresh_token.py` → çıkan 3 değeri not al.
3. Repo → Settings → Secrets and variables → Actions → **Secrets**:
   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, PEXELS_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
4. Aynı yerde **Variables** (opsiyonel): AUTO_APPROVE (false/true), CONTENT_LANG (tr/en), CHANNEL_TAG (@kanaladin), AFFILIATE_TEXT
5. Actions sekmesi → `generate` → Run workflow ile ilk videoyu dene.
6. `field_notes.txt` dosyasına KENDİ sahadan notlarını ekle. Her video bir nottan üretilir, "sana ait" özgün içerik budur.

## Kritik tuzaklar
- **OAuth consent screen "Testing" modunda kalırsa refresh token 7 günde ölür.** "Publish app / In production" yap.
- **Doğrulanmamış API projesiyle yüklenen videolar PRIVATE'a kilitlenir.** YouTube API Services Audit formunu doldurman gerekir (ücretsiz, birkaç hafta sürebilir). Bu sürede videolar özel kalır; Telegram'dan indirip manuel yayınlayabilirsin.
- Telegram bot indirme limiti 20 MB: video 3000k bitrate ile ~35 sn'ye kadar güvenli.
- GitHub cron birkaç dakika gecikebilir. Komutlar (/durum vb.) 30 dk içinde cevaplanır.
- Günlük upload kotası ~6 video; 3 video güvenli.

## Ban'dan kaçınma
- Telifli klip/müzik yok: sadece Pexels (ücretsiz lisans) + Edge-TTS + kendi metinlerin.
- Her video farklı senaryo ve farklı not; tekrar eden/şablon spam gibi görünmesin diye ilk 2 hafta Telegram onayıyla yayınla.
- Müzik eklersen sadece YouTube Audio Library.

## Büyüme ve gelir planı
- 0-4. hafta: AUTO_APPROVE=false, her videoyu izle, kötüleri reddet.
- Haftalık rapordaki en iyi 5 videonun konusunu `field_notes.txt`'ye benzer notlarla çoğalt.
- 1.000 abone + 90 günde 10M Shorts izlenme (veya 4.000 saat) ile YPP başvurusu.
- O zamana kadar: AFFILIATE_TEXT ile kitap/kurs bağlantısı (Amazon Associates, Udemy affiliate).
- İstikrar sonrası AUTO_APPROVE=true.
