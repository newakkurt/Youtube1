"""LinkedIn video paylasimi (kisisel profil) + LinkedIn'e ozel metin uretimi.

Gerekli ortam degiskenleri:
  LINKEDIN_ACCESS_TOKEN   (zorunlu)
  LINKEDIN_TOKEN_DATE     (opsiyonel, token'in alindigi tarih, YYYY-MM-DD; sure uyarisi icin)
  LINKEDIN_API_VERSION    (opsiyonel, varsayilan 202609; surum hatasi alirsan guncelle)

Metin uretimi icin (hepsi opsiyonel; hicbiri yoksa sablon metin kullanilir):
  GROQ_API_KEY            Groq anahtari
  GEMINI_API_KEY          Gemini anahtari
  LINKEDIN_GROQ_MODELS    virgullu model listesi (varsayilan: llama-3.3-70b-versatile,llama-3.1-8b-instant)
  LINKEDIN_GEMINI_MODELS  virgullu model listesi (varsayilan: gemini-2.0-flash,gemini-1.5-flash)
  LINKEDIN_AUTHOR_CONTEXT yazarin kisisel acisi (varsayilan: a network engineer working in a factory environment)
  LINKEDIN_REWRITE        0 yaparsan metin yeniden yazilmaz, caption aynen gider

Ana bot dosyasindan kullanim (degismedi, 2 satir):
  from linkedin_post import publish_linkedin
  li_status = publish_linkedin(video_path, caption)   # Telegram mesajina ekle

publish_linkedin artik caption'i kaynak alip LinkedIn icin ayri bir yazi uretir:
merak uyandiran hook, bilim kurgu -> bugunun teknolojisi, kisisel aci ve
yorum cekmek icin sonda acik uclu bir soru.
"""
import os
import re
import time
from datetime import date, datetime
from urllib.parse import quote

import requests

API = "https://api.linkedin.com"
TOKEN_LIFETIME_DAYS = 60
WARN_AT_DAYS_LEFT = 10

FALLBACK_QUESTION = "Which sci-fi idea do you think becomes reality next? Tell me in the comments."
FALLBACK_HASHTAGS = "#technology #scifi #futuretech #innovation"

SYSTEM_PROMPT = (
    "You write LinkedIn posts for the personal profile of {author}. "
    "Topic area: general technology and science fiction. Write in English.\n"
    "Rules:\n"
