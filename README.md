# shorts-bot
Günde 3 video (09:00 / 14:00 / 20:00 TR): Gemini 3.8 -> Groq (3 model) -> OpenRouter yedekli senaryo, Edge-TTS ses, Pexels görüntü, MoviePy video.
AUTO_APPROVE varsayılan true: onay istemeden YouTube'a yükler, Telegram'a link atar. Pazar 18:00 haftalık rapor.
Yükleme hatasında video Telegram'a onay butonlarıyla gönderilir (kaybolmaz).

Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, PEXELS_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Variables (opsiyonel): AUTO_APPROVE, CONTENT_LANG, CHANNEL_TAG, AFFILIATE_TEXT, GROQ_MODELS, OPENROUTER_MODEL
