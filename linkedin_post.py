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

publish_linkedin caption'i kaynak alip LinkedIn'e OZEL bir yazi uretir. Konuya gore iki stil:
  - TEKNIK konu (network, guvenlik, altyapi, IT): sahadan bakis, problem -> cozum -> ders
  - BILIM KURGU / uzay / gelecek teknolojisi: bilim kurgu fikri -> bugunun teknolojisi
Her iki stilde: merak uyandiran hook, sonda yorum cekmek icin acik uclu soru, 3-4 hashtag.
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

TECH_KEYWORDS = (
    "network", "switch", "vlan", "bpdu", "stp", "spanning", "firewall", "router", "routing",
    "cisco", "huawei", "aruba", "fortinet", "dhcp", "dns", "tacacs", "radius", "ansible",
    "security", "cyber", "cve", "cisa", "vulnerab", "exploit", "ransomware", "patch",
    "server", "linux", "cloud", "docker", "devops", "automation", "infrastructure",
    "ethernet", "wifi", "wi-fi", "vpn", "protocol", "port", "latency", "bandwidth",
