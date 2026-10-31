import json
import re


def _fallback_instagram(title, description, tags):
    clean = re.sub(r"\s+#\w+", "", description or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    hashtags = " ".join("#" + str(tag).lstrip("#") for tag in tags[:5] if tag)
    body = f"{title}\n\n{clean[:700]}\n\nSave this for your next network troubleshooting session."
    return (body + ("\n\n" + hashtags if hashtags else ""))[:2100]


def build_platform_captions(script, youtube_description, ask_fn=None, linkedin_fn=None):
    """
    Produce platform-native captions from one reviewed video script.
    Technical claims must stay inside the approved script/description.
    """
    title = str(script.get("title", "")).strip()
    scenes = script.get("scenes") or []
    source_text = " ".join(str(s.get("text", "")) for s in scenes if isinstance(s, dict))
    tags = [str(t).strip().lstrip("#") for t in
            ([script.get("local_tag", "")] + (script.get("global_tags") or [])) if str(t).strip()]

    instagram = _fallback_instagram(title, youtube_description, tags)
    try:
        if ask_fn is None:
            import script_gen
            ask_fn = script_gen._ask
        prompt = f"""Create an Instagram Reels caption for this already reviewed network/cybersecurity video.
Title: {title}
Approved script: {source_text}
Approved description: {youtube_description}
Rules:
- Write in natural English for network engineers.
- Start with a strong, specific hook; then 1-2 short useful paragraphs.
- End with one practical question or save/share CTA.
- Use at most 5 relevant hashtags.
- Do not add facts, statistics, CVEs, dates, commands or claims absent from the approved material.
- No fake personal experience, no clickbait, no markdown.
Return ONLY JSON: {{"caption":"..."}}"""
        raw = ask_fn(prompt, as_json=True, tier="fast")
        data = json.loads(raw)
        candidate = str(data.get("caption", "")).strip()
        if 80 <= len(candidate) <= 2200:
            instagram = candidate
    except Exception as exc:
        print("Instagram caption fallback:", str(exc)[:160])

    try:
        if linkedin_fn is None:
            import script_gen
            linkedin_fn = script_gen.bilingual_caption
        linkedin = linkedin_fn(title, youtube_description)
    except Exception as exc:
        print("LinkedIn caption fallback:", str(exc)[:160])
        linkedin = f"{title}\n\n{youtube_description}".strip()

    return {
        "instagram_caption": instagram[:2200],
        "linkedin_caption": linkedin[:3000],
    }
