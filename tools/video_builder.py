#!/usr/bin/env python3
"""
Glimerz YouTube video builder (zero-cost edition).

Turns one blog post into ONE YouTube-ready video:
  * short -> vertical 1440x2560, max ~58 s  (YouTube treats it as a Short)
  * video -> horizontal 2560x1440, ~2-4 min, plus a 1280x720 thumbnail

Everything runs on a normal CPU (GitHub Actions), no paid services:
  * voice    : Kokoro (open-source TTS, runs locally)
  * visuals  : the post's own images with slow zoom/pan motion
  * captions : burned-in, synced per sentence, word-by-word highlight
  * music    : your own tracks in tools/music/ if present, else generated locally

Optional extras (only used if the secret exists):
  * ANTHROPIC_API_KEY -> Claude writes a better spoken script (fraction of a cent)
  * VOICE_ENGINE=elevenlabs + FAL_KEY -> old paid ElevenLabs voice

Format per post: front matter `youtube_format: short|video`, otherwise DEFAULT_FORMAT.
"""
import argparse, hashlib, json, os, re, subprocess, time, urllib.request, urllib.error
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# ------------------------------------------------------------------ settings
DEFAULT_FORMAT = "short"          # used when a post has no youtube_format
VOICE = "af_heart"                # Kokoro voice (try am_michael, af_bella, bf_emma)
VOICE_SPEED = 1.0
SHORT_MAX_SECONDS = 58
VIDEO_MAX_SECONDS = 270
FPS = 30
XFADE = 0.5                       # transition length between scenes
LEAD, TAIL, SENT_GAP = 0.35, 0.45, 0.22
UPSCALE = 2                       # frames rendered larger so zoom/pan is smooth
SITE = "https://glimerz.com"
CLAUDE_MODEL = "claude-haiku-4-5"
CACHE = Path(os.environ.get("GLIMERZ_VIDEO_CACHE", str(Path.home() / ".cache" / "glimerz-video")))
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FONT_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/"
FONTS = ["Poppins-Regular", "Poppins-SemiBold", "Poppins-Bold", "Poppins-ExtraBold"]
MUSIC_DIR = Path(__file__).resolve().parent / "music"
REPO_ROOT = Path(__file__).resolve().parent.parent

WHITE = (255, 255, 255)
ACCENT = (55, 80, 62)             # Glimerz green
ACCENT_LIGHT = (160, 205, 160)
HIGHLIGHT = (255, 214, 10)

FORMATS = {
    "short": {"w": 1440, "h": 2560, "max": SHORT_MAX_SECONDS},
    "video": {"w": 2560, "h": 1440, "max": VIDEO_MAX_SECONDS},
}

# ------------------------------------------------------------------ helpers
UA = {"User-Agent": "Mozilla/5.0 (Glimerz-Video-Builder/3.0)"}


def download(url, path, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    Path(path).write_bytes(data)


def ensure_assets():
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "fonts").mkdir(exist_ok=True)
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        p = CACHE / name
        if not p.exists() or p.stat().st_size < 1_000_000:
            print(f"Downloading {name} ...")
            download(KOKORO_BASE + name, p, timeout=600)
    for f in FONTS:
        p = CACHE / "fonts" / f"{f}.ttf"
        if not p.exists():
            try:
                download(FONT_BASE + f + ".ttf", p)
            except Exception as e:
                print(f"Font download failed ({f}): {e} - falling back to DejaVu")


_font_cache = {}


def font(weight, size):
    key = (weight, size)
    if key in _font_cache:
        return _font_cache[key]
    p = CACHE / "fonts" / f"Poppins-{weight}.ttf"
    try:
        f = ImageFont.truetype(str(p), size)
    except Exception:
        bold = weight in ("Bold", "ExtraBold", "SemiBold")
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), size)
    _font_cache[key] = f
    return f


def caption_font_name():
    return "Poppins ExtraBold" if (CACHE / "fonts" / "Poppins-ExtraBold.ttf").exists() else "DejaVu Sans"


def clean_text(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    s = re.sub(r"[*_#`>]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(text):
    text = clean_text(text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    return [p.strip() for p in parts if p.strip()]


def speech(text):
    """Make text easier for the TTS to read. Captions keep the original text."""
    t = text
    t = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 to \2", t)
    t = re.sub(r"\s*[—–]\s*", ", ", t)
    t = re.sub(r"(\d)\s*lbs?\b\.?", r"\1 pounds", t)
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)
    t = t.replace("&", " and ").replace("e.g.", "for example").replace("i.e.", "that is")
    t = t.replace(" vs. ", " versus ").replace("/", " or ")
    t = re.sub(r"\.com\b", " dot com", t)
    t = re.sub(r"[()\[\]\"“”]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


# ------------------------------------------------------------------ the post
def load_post(slug, repo):
    local = REPO_ROOT / "content" / "blog" / f"{slug}.md"
    if local.exists():
        raw = local.read_text(encoding="utf-8")
    else:
        url = f"https://raw.githubusercontent.com/{repo}/main/content/blog/{slug}.md"
        raw = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    fm = yaml.safe_load(m.group(1)) if m else {}
    body = raw[m.end():] if m else raw
    return fm or {}, body


def extract_sections(body):
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.M))
    out = []
    for i, m in enumerate(matches):
        heading = clean_text(m.group(1))
        chunk = body[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(body)]
        chunk = re.sub(r"^###.*$", "", chunk, flags=re.M)
        paras = [clean_text(p) for p in re.split(r"\n\s*\n", chunk)]
        paras = [p for p in paras if len(p.split()) > 5]
        if heading and paras and not re.search(r"disclosure|affiliate", heading, re.I):
            out.append((heading, paras))
    return out


def products_of(fm):
    items = []
    for key in ("products", "mid_products"):
        for p in fm.get(key) or []:
            if isinstance(p, dict) and p.get("product_name"):
                items.append({
                    "name": str(p["product_name"]).strip().rstrip("."),
                    "link": str(p.get("affiliate_link") or "").strip(),
                    "photo": str(p.get("photo") or "").strip(),
                })
    return items


def open_image(path):
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        # e.g. AVIF/WebP that this Pillow build cannot read: let ffmpeg convert it
        png = str(path) + ".png"
        ff("-i", str(path), "-frames:v", "1", png)
        return Image.open(png).convert("RGB")


def load_images(fm, repo, out):
    sources = []
    hero = str(fm.get("image") or "")
    if hero:
        if hero.startswith("/images/"):
            local = REPO_ROOT / "static" / "images" / Path(hero).name
            sources.append(("hero", str(local) if local.exists()
                            else f"https://raw.githubusercontent.com/{repo}/main/static/images/{Path(hero).name}"))
        elif hero.startswith("http"):
            sources.append(("hero", hero))
    for i, p in enumerate(products_of(fm), 1):
        if p["photo"]:
            src = p["photo"]
            if src.startswith("/images/"):
                src = str(REPO_ROOT / "static" / "images" / Path(src).name)
            sources.append((f"product-{i}", src))
    loaded = []
    for n, (label, src) in enumerate(sources, 1):
        try:
            if src.startswith("http"):
                p = out / f"src-{n}-{label}"
                download(src, p, timeout=60)
            else:
                p = Path(src)
            img = open_image(p)
            loaded.append((label, img))
            print(f"Image loaded: {label} {img.width}x{img.height}")
        except Exception as e:
            print(f"Image skipped: {label} ({e})")
    return loaded


# ------------------------------------------------------------------ script
def trim_words(sentence, max_words):
    words = sentence.split()
    if len(words) <= max_words:
        return sentence
    cut = " ".join(words[:max_words])
    for sep in (";", ":", " - ", ","):
        i = cut.rfind(sep)
        if i > len(cut) * 0.5:
            return cut[:i].rstrip() + "."
    return sentence  # keep the full sentence rather than cut it oddly


def lead_sentences(paras, max_sents, max_words):
    out, words = [], 0
    for s in split_sentences(" ".join(paras)):
        s = trim_words(s, max_words) if not out else s
        w = len(s.split())
        if out and words + w > max_words:
            break
        out.append(s)
        words += w
        if len(out) >= max_sents:
            break
    return " ".join(out)


def spoken_title(title):
    t = re.sub(r"\s*\([^)]*\)", "", title).strip().rstrip(".!?")
    if re.match(r"how to\b", t, re.I):
        return "Here's " + t[0].lower() + t[1:] + "."
    return t + "."


def extractive_script(fmt, title, desc, sections):
    scenes = [{"kind": "intro", "heading": title, "narration": spoken_title(title)}]
    if fmt == "short":
        chosen, per = sections[:5], (1, 26)
    else:
        if desc:
            scenes[0]["narration"] += " " + " ".join(split_sentences(desc)[:2])
        chosen, per = sections[:8], (3, 75)
    for heading, paras in chosen:
        scenes.append({"kind": "section", "heading": heading,
                       "narration": lead_sentences(paras, per[0], per[1])})
    if fmt == "short":
        outro = "Get the full guide, with the tools we recommend, on glimerz.com."
    else:
        outro = ("That's the short version. For the complete guide and the products we recommend, "
                 "visit glimerz.com. The link is in the description. Thanks for watching.")
    scenes.append({"kind": "outro", "heading": "Read the full guide", "narration": outro})
    return {"scenes": scenes, "youtube_title": None, "tags": None, "writer": "extractive"}


def claude_script(fmt, title, desc, body):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    if fmt == "short":
        shape = "5 to 7 scenes, 110 to 140 words of narration in total (under 55 seconds spoken)"
    else:
        shape = "7 to 10 scenes, 380 to 520 words of narration in total (about 3 minutes spoken)"
    prompt = f"""Turn this blog post into a YouTube voiceover script.

Format: {"vertical YouTube Short" if fmt == "short" else "horizontal YouTube video"}; {shape}.
Rules:
- Spoken, friendly, confident. No markdown, emojis, hashtags, stage directions or prices.
- Only use facts that are in the post. Do not invent products, numbers or claims.
- Scene 1 is a strong hook. The last scene invites viewers to read the full guide on glimerz.com.
- Each scene has an on-screen heading of at most 7 words.
Return ONLY JSON, no code fences:
{{"youtube_title": "max 90 characters, no clickbait, no emojis",
  "tags": ["8 to 12 short search tags"],
  "scenes": [{{"heading": "...", "narration": "..."}}]}}

POST TITLE: {title}
POST DESCRIPTION: {desc}
POST BODY:
{clean_text(body)[:14000]}"""
    payload = {"model": CLAUDE_MODEL, "max_tokens": 2500,
               "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode(),
                                 method="POST", headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                         "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
        js = json.loads(text[text.find("{"): text.rfind("}") + 1])
        raw_scenes = [s for s in js.get("scenes", []) if s.get("narration")]
        if len(raw_scenes) < 3:
            raise ValueError("too few scenes")
        scenes = []
        for i, s in enumerate(raw_scenes):
            kind = "intro" if i == 0 else "outro" if i == len(raw_scenes) - 1 else "section"
            heading = title if kind == "intro" else clean_text(str(s.get("heading", "")))[:80]
            if kind == "outro":
                heading = "Read the full guide"
            scenes.append({"kind": kind, "heading": heading, "narration": clean_text(s["narration"])})
        print("Script written by Claude")
        return {"scenes": scenes, "youtube_title": clean_text(str(js.get("youtube_title") or ""))[:100] or None,
                "tags": [clean_text(str(t))[:30] for t in js.get("tags", []) if str(t).strip()][:15] or None,
                "writer": CLAUDE_MODEL}
    except Exception as e:
        print(f"Claude script failed, using article text instead: {e}")
        return None


# ------------------------------------------------------------------ voice
class Voice:
    def __init__(self):
        self.engine = os.environ.get("VOICE_ENGINE", "kokoro").lower()
        self.sr = 24000
        if self.engine == "elevenlabs" and os.environ.get("FAL_KEY"):
            print("Voice: ElevenLabs via fal.ai (paid)")
        else:
            self.engine = "kokoro"
            from kokoro_onnx import Kokoro
            self.k = Kokoro(str(CACHE / "kokoro-v1.0.onnx"), str(CACHE / "voices-v1.0.bin"))
            print(f"Voice: Kokoro {VOICE} (free, local)")

    def say(self, text, workdir):
        if self.engine == "kokoro":
            samples, sr = self.k.create(speech(text), voice=VOICE, speed=VOICE_SPEED, lang="en-us")
            return np.asarray(samples, dtype=np.float32)
        return self._elevenlabs(speech(text), workdir)

    def _elevenlabs(self, text, workdir):
        key = os.environ["FAL_KEY"]
        req = urllib.request.Request("https://queue.fal.run/fal-ai/elevenlabs/tts/eleven-v3", method="POST",
                                     data=json.dumps({"text": text, "voice": "Aria", "output_format": "mp3_44100_128"}).encode(),
                                     headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            job = json.loads(r.read().decode())
        for _ in range(120):
            sreq = urllib.request.Request(job["status_url"], headers={"Authorization": f"Key {key}"})
            with urllib.request.urlopen(sreq, timeout=60) as r:
                st = json.loads(r.read().decode())
            if st.get("status") == "COMPLETED":
                break
            time.sleep(2)
        rreq = urllib.request.Request(job["response_url"], headers={"Authorization": f"Key {key}"})
        with urllib.request.urlopen(rreq, timeout=60) as r:
            url = json.loads(r.read().decode())["audio"]["url"]
        mp3 = Path(workdir) / f"el-{hashlib.md5(text.encode()).hexdigest()[:8]}.mp3"
        download(url, mp3)
        raw = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", str(mp3), "-f", "f32le",
                                       "-ac", "1", "-ar", str(self.sr), "-"])
        return np.frombuffer(raw, dtype=np.float32).copy()


def voice_scenes(scenes, voice, workdir):
    gap = np.zeros(int(SENT_GAP * voice.sr), np.float32)
    for sc in scenes:
        parts, timings, t = [], [], 0.0
        for s in split_sentences(sc["narration"]) or [sc["narration"]]:
            a = voice.say(s, workdir)
            dur = len(a) / voice.sr
            timings.append((t, t + dur, s))
            parts += [a, gap]
            t += dur + SENT_GAP
        sc["audio"] = np.concatenate(parts[:-1]) if parts else np.zeros(1, np.float32)
        sc["sentences"] = timings
        sc["audio_len"] = len(sc["audio"]) / voice.sr


def fit_scenes(scenes, max_seconds):
    def total(sc):
        return sum(s["audio_len"] + LEAD + TAIL for s in sc) - XFADE * (len(sc) - 1)
    while total(scenes) > max_seconds and len(scenes) > 3:
        idx = max(i for i, s in enumerate(scenes) if s["kind"] == "section")
        print(f"Dropping scene to fit {max_seconds}s: {scenes[idx]['heading']}")
        scenes.pop(idx)
    return scenes


# ------------------------------------------------------------------ visuals
def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def backdrop(img, w, h):
    small = cover(img, max(1, w // 6), max(1, h // 6)).filter(ImageFilter.GaussianBlur(6))
    bg = ImageEnhance.Brightness(small.resize((w, h), Image.BICUBIC)).enhance(0.40).convert("RGBA")
    grad = Image.new("L", (1, h))
    for y in range(h):
        edge = min(y, h - 1 - y) / (h * 0.28)
        grad.putpixel((0, y), int(130 * max(0.0, 1 - edge)))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade.putalpha(grad.resize((w, h)))
    return Image.alpha_composite(bg, shade)


def is_cutout(img):
    """True for product shots on a plain white background (never crop those)."""
    small = img.resize((64, 64))
    px = np.asarray(small, dtype=np.float32)
    border = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
    return float(border.mean()) > 232 and float(border.std()) < 18


def photo_card(img, box_w, box_h, pad=22, radius=28, crop=True):
    iw, ih = box_w - 2 * pad, box_h - 2 * pad
    if crop and not is_cutout(img):
        # Photos: trim up to 25% of the width so they fill more of the frame.
        target = max(iw / ih, (img.width / img.height) * 0.75)
        if target < img.width / img.height:
            img = cover(img, round(img.height * target), img.height)
    s = min(iw / img.width, ih / img.height)
    ph = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    cw, ch = ph.width + 2 * pad, ph.height + 2 * pad
    base = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    base.paste(ph, (pad, pad))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius, fill=255)
    base.putalpha(mask)
    return base


def paste_card(canvas, card, x, y, k=1.0):
    m = round(50 * k)
    sh = Image.new("RGBA", (card.width + 2 * m, card.height + 2 * m), (0, 0, 0, 0))
    dark = Image.new("RGBA", card.size, (0, 0, 0, 160))
    dark.putalpha(card.split()[3].point(lambda a: a * 160 // 255))
    sh.paste(dark, (m, m + round(14 * k)), dark)
    sh = sh.filter(ImageFilter.GaussianBlur(20 * k))
    canvas.alpha_composite(sh, (x - m, y - m))
    canvas.alpha_composite(card, (x, y))


def wrap_px(draw, text, fnt, max_w):
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_heading(draw, text, max_w, size, min_size, max_lines):
    while True:
        f = font("ExtraBold", size)
        lines = wrap_px(draw, text, f, max_w)
        if len(lines) <= max_lines or size <= min_size:
            return f, lines[:max_lines], size
        size -= 4


MEAS = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def chip(draw, x, y, label, k=1.0):
    f = font("Bold", round(34 * k))
    w = draw.textlength(label, font=f) + round(44 * k)
    draw.rounded_rectangle((x, y, x + w, y + round(60 * k)), round(18 * k), fill=ACCENT)
    draw.text((x + round(22 * k), y + round(8 * k)), label, font=f, fill=WHITE)


class Overlay:
    """Static text layer drawn at full output resolution with a soft shadow.
    It sits on top of the moving picture, so text stays razor sharp."""

    def __init__(self, w, h, k):
        self.w, self.h, self.k = w, h, k
        self.texts, self.chips = [], []

    def text(self, xy, s, fnt, fill):
        self.texts.append((xy, s, fnt, fill))

    def chip(self, x, y, label):
        self.chips.append((x, y, label))

    def render(self):
        k = self.k
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        sh = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        for (x, y), s, f, _ in self.texts:
            d.text((x, y + round(3 * k)), s, font=f, fill=(0, 0, 0, 190))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7 * k)))
        d = ImageDraw.Draw(img)
        for x, y, label in self.chips:
            chip(d, x, y, label, k)
        for (x, y), s, f, fill in self.texts:
            d.text((x, y), s, font=f, fill=fill)
        return img


def layout_short(sc, img, number, W, H):
    k = W / 1080

    def P(v):
        return round(v * k)
    bg = backdrop(img, W, H)
    ov = Overlay(W, H, k)
    x0, maxw, y = P(70), P(940), P(150)
    ov.text((x0, y), "G L I M E R Z", font("Bold", P(30)), ACCENT_LIGHT)
    y += P(70)
    if sc["kind"] == "section":
        ov.chip(x0, y, f"{number:02d}")
        y += P(90)
    size = P({"intro": 78, "section": 66, "outro": 80}[sc["kind"]])
    f, lines, sz = fit_heading(MEAS, sc["heading"], maxw, size, P(46), 4 if sc["kind"] == "intro" else 3)
    for ln in lines:
        ov.text((x0, y), ln, f, WHITE)
        y += int(sz * 1.18)
    if sc["kind"] == "outro":
        ov.text((x0, y + P(6)), "glimerz.com", font("ExtraBold", P(84)), HIGHLIGHT)
        y += P(106)
    top, bottom = y + P(45), P(1400)
    card = photo_card(img, P(960), max(P(420), bottom - top), pad=P(22), radius=P(28), crop=sc["kind"] == "section")
    paste_card(bg, card, (W - card.width) // 2, top + max(0, (bottom - top - card.height) // 2), k)
    return bg.convert("RGB"), ov.render()


def layout_video(sc, img, number, W, H):
    k = W / 1920

    def P(v):
        return round(v * k)
    bg = backdrop(img, W, H)
    ov = Overlay(W, H, k)
    card = photo_card(img, P(880), P(740), pad=P(22), radius=P(28), crop=sc["kind"] == "section")
    paste_card(bg, card, P(100) + (P(880) - card.width) // 2, P(110) + (P(740) - card.height) // 2, k)
    x0, maxw = P(1090), P(740)
    size = P({"intro": 70, "section": 62, "outro": 72}[sc["kind"]])
    f, lines, sz = fit_heading(MEAS, sc["heading"], maxw, size, P(44), 5 if sc["kind"] == "intro" else 4)
    block = P(70) + (P(90) if sc["kind"] == "section" else 0) + len(lines) * int(sz * 1.18) + (P(110) if sc["kind"] == "outro" else 0)
    y = max(P(110), P(110) + (P(740) - block) // 2)
    ov.text((x0, y), "G L I M E R Z", font("Bold", P(28)), ACCENT_LIGHT)
    y += P(70)
    if sc["kind"] == "section":
        ov.chip(x0, y, f"{number:02d}")
        y += P(90)
    for ln in lines:
        ov.text((x0, y), ln, f, WHITE)
        y += int(sz * 1.18)
    if sc["kind"] == "outro":
        ov.text((x0, y + P(10)), "glimerz.com", font("ExtraBold", P(80)), HIGHLIGHT)
    return bg.convert("RGB"), ov.render()


def thumbnail(title, img, path):
    W, H = 1280, 720
    cv = cover(img, W, H).convert("RGBA")
    grad = Image.new("L", (W, 1))
    for x in range(W):
        grad.putpixel((x, 0), int(235 * max(0.0, 1 - x / (W * 0.78))))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shade.putalpha(grad.resize((W, H)))
    cv = Image.alpha_composite(cv, shade)
    d = ImageDraw.Draw(cv)
    t = re.sub(r"\s*\([^)]*\)", "", title).strip()
    f, lines, sz = fit_heading(d, t, 760, 96, 56, 4)
    y = (H - len(lines) * int(sz * 1.12)) // 2 + 20
    chip(d, 60, y - 90, "GLIMERZ")
    for i, ln in enumerate(lines):
        d.text((64, y + 5), ln, font=f, fill=(0, 0, 0, 160))
        d.text((60, y), ln, font=f, fill=HIGHLIGHT if i == 0 else WHITE)
        y += int(sz * 1.12)
    cv.convert("RGB").save(path, quality=90)


MOTIONS = [
    ("1+0.06*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),            # push in
    ("1.06-0.06*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # pull out
    ("1.05", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),                  # pan right
    ("1.05", "(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),              # pan left
]


def render_segment(layers, frames, motion, w, h, path):
    bg, overlay = layers
    big = bg.resize((w * UPSCALE, h * UPSCALE), Image.LANCZOS)
    bg_png, ov_png = str(path) + ".bg.png", str(path) + ".ov.png"
    big.save(bg_png)
    overlay.save(ov_png)
    z, x, y = (m.format(n=max(1, frames - 1)) for m in motion)
    ff("-i", bg_png, "-i", ov_png, "-filter_complex",
       f"[0:v]zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}[b];"
       f"[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
       "-map", "[v]", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", str(path))


# ------------------------------------------------------------------ captions
def ass_time(t):
    cs = max(0, int(round(t * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def chunk_words(words, max_words, max_chars):
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(cur + [w])) > max_chars):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[,;:]$", w) and len(cur) >= 2:
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and len(cur) == 1 and len(chunks[-1]) < max_words + 1:
            chunks[-1] += cur
        else:
            chunks.append(cur)
    return chunks


def write_ass(path, cues, fmt):
    W, H = FORMATS[fmt]["w"], FORMATS[fmt]["h"]
    if fmt == "short":
        k = W / 1080
        size, outline, margin_v, mw, mc = 76, 6, 360, 4, 22
    else:
        k = W / 1920
        size, outline, margin_v, mw, mc = 62, 5, 55, 6, 40
    size, outline, margin_v, side = round(size * k), round(outline * k), round(margin_v * k), round(80 * k)
    name = caption_font_name()
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "ScaledBorderAndShadow: yes", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cap,{name},{size},&H000AD6FF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,"
        f"{outline},{round(2 * k)},2,{side},{side},{margin_v},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, sentence in cues:
        words = sentence.split()
        if not words:
            continue
        span_s, span_e = start + 0.04, max(start + 0.3, end - 0.08)
        weights = [len(w) + 1.5 for w in words]
        unit = (span_e - span_s) / sum(weights)
        t, wi = span_s, 0
        for ch in chunk_words(words, mw, mc):
            ws = weights[wi: wi + len(ch)]
            c_start, c_end = t, t + sum(ws) * unit
            ktags = "".join("{\\k%d}%s " % (max(1, round(wt * unit * 100)), w.replace("{", "(").replace("}", ")"))
                            for w, wt in zip(ch, ws)).strip()
            pop = "{\\fscx90\\fscy90\\t(0,90,\\fscx100\\fscy100)}"
            lines.append(f"Dialogue: 0,{ass_time(c_start)},{ass_time(c_end)},Cap,,0,0,0,,{pop}{ktags}")
            t = c_end
            wi += len(ch)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ music
def generated_music(seconds, seed, sr=48000):
    rng = np.random.default_rng(seed)
    shift = int(rng.choice([-3, -2, 0, 2, 3]))
    progression = [[48, 55, 60, 64], [43, 55, 59, 62], [45, 57, 60, 64], [41, 53, 57, 60]]
    bar = 4.0
    n = int((seconds + 2) * sr)
    mix = np.zeros(n, np.float32)

    def hz(m):
        return 440.0 * 2 ** ((m + shift - 69) / 12)
    seg = int((bar + 1.5) * sr)
    tt = np.arange(seg) / sr
    env = np.minimum(1, tt / 1.2) * np.clip((bar + 1.5 - tt) / 1.5, 0, 1)
    arp_len = int(1.2 * sr)
    ta = np.arange(arp_len) / sr
    arp_env = np.minimum(1, ta / 0.006) * np.exp(-ta / 0.45)
    k = 0
    while k * bar * sr < n:
        chord = progression[k % 4]
        start = int(k * bar * sr)
        pad = np.zeros(seg, np.float32)
        for m in chord:
            f = hz(m)
            pad += (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(2 * np.pi * 2 * f * tt)
                    + np.sin(2 * np.pi * f * 1.003 * tt) * 0.6)
        pad *= env * 0.05
        end = min(n, start + seg)
        mix[start:end] += pad[: end - start]
        for step in range(8):
            m = chord[[1, 2, 3, 2, 1, 2, 3, 2][step]] + 12
            s0 = start + int(step * bar / 8 * sr)
            if s0 >= n:
                break
            note = np.sin(2 * np.pi * hz(m) * ta) * arp_env * 0.06
            e0 = min(n, s0 + arp_len)
            mix[s0:e0] += note[: e0 - s0]
        k += 1
    left, right = mix.copy(), mix.copy()
    for delay, gain in ((0.23, 0.35), (0.41, 0.22), (0.67, 0.12)):
        dl, dr = int(delay * sr), int((delay + 0.05) * sr)
        left[dl:] += mix[:-dl] * gain
        right[dr:] += mix[:-dr] * gain
    st = np.stack([left, right], 1)
    st /= max(1e-6, np.abs(st).max()) / 0.5
    return st, sr


def music_track(slug, seconds, out):
    tracks = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))
    if tracks:
        pick = tracks[int(hashlib.md5(slug.encode()).hexdigest(), 16) % len(tracks)]
        print(f"Music: {pick.name}")
        return pick, True
    import soundfile as sf
    audio, sr = generated_music(seconds, int(hashlib.md5(slug.encode()).hexdigest()[:6], 16))
    p = out / "music.wav"
    sf.write(p, audio, sr)
    print("Music: generated ambient bed (add your own tracks to tools/music/ for better music)")
    return p, False


# ------------------------------------------------------------------ description
def build_description(fm, desc, slug, products, fmt):
    lines = []
    if desc:
        lines += [desc, ""]
    lines += [f"Read the full guide: {SITE}/blog/{slug}/"]
    cats = fm.get("categories") or []
    tags = ["#" + re.sub(r"[^A-Za-z0-9]", "", str(c)).lower() for c in cats]
    if fmt == "short":
        tags.append("#shorts")
    if tags:
        lines += ["", " ".join(tags)]
    return "\n".join(lines)[:4900]


def default_tags(fm, title):
    stop = set("a an the and or of to for in on with your you how what why without it its is are be later".split())
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", title) if w.lower() not in stop]
    tags = [str(c) for c in (fm.get("categories") or [])] + ["glimerz", "home tips"] + words[:8]
    seen, out = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:15]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--repo", default="kmbajwa1972/Glimerz-site")
    ap.add_argument("--out", default="build/video")
    ap.add_argument("--format", default="auto", choices=["auto", "short", "video"])
    ap.add_argument("--preflight", action="store_true", help="Check the post and images only, no rendering")
    args = ap.parse_args()
    args.slug = re.sub(r"^\s*slug\s*:\s*", "", args.slug, flags=re.I).strip().strip("\"'")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.slug):
        raise ValueError(f"Invalid slug: {args.slug!r}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    fm, body = load_post(args.slug, args.repo)
    title = clean_text(str(fm.get("title") or args.slug.replace("-", " ").title()))
    desc = clean_text(str(fm.get("description") or ""))
    fmt = args.format if args.format != "auto" else str(fm.get("youtube_format") or DEFAULT_FORMAT).lower()
    if fmt not in FORMATS:
        fmt = DEFAULT_FORMAT
    W, H, max_s = FORMATS[fmt]["w"], FORMATS[fmt]["h"], FORMATS[fmt]["max"]
    sections = extract_sections(body)
    images = load_images(fm, args.repo, out)
    if not images:
        raise RuntimeError("No images attached to this post could be loaded")
    if not sections:
        raise RuntimeError("No '## ' sections found in this post")
    products = products_of(fm)
    print(f"Post: {title}\nFormat: {fmt} ({W}x{H}, max {max_s}s)\nSections: {len(sections)}  Images: {len(images)}")

    if args.preflight:
        for h, _ in sections:
            print(f"  - {h}")
        print("PREFLIGHT: PASS (paid calls: 0)")
        return

    ensure_assets()
    script = claude_script(fmt, title, desc, body) or extractive_script(fmt, title, desc, sections)
    scenes = script["scenes"]

    voice = Voice()
    voice_scenes(scenes, voice, out)
    scenes = fit_scenes(scenes, max_s)

    # timeline
    hero = images[0][1]
    pool = [im for lbl, im in images if lbl != "hero"] or [hero]
    offset, cues, sec_no = 0.0, [], 0
    for sc in scenes:
        frames = int(round((sc["audio_len"] + LEAD + TAIL) * FPS))
        sc["frames"], sc["dur"], sc["start"] = frames, frames / FPS, offset
        for s, e, text in sc["sentences"]:
            cues.append((offset + LEAD + s, offset + LEAD + e, text))
        if sc["kind"] == "section":
            sec_no += 1
            sc["img"], sc["number"] = pool[(sec_no - 1) % len(pool)], sec_no
        else:
            sc["img"], sc["number"] = hero, 0
        offset += sc["dur"] - XFADE
    total = offset + XFADE

    import soundfile as sf
    narration = np.zeros(int(np.ceil(total * voice.sr)) + voice.sr, np.float32)
    for sc in scenes:
        a0 = int((sc["start"] + LEAD) * voice.sr)
        narration[a0: a0 + len(sc["audio"])] += sc["audio"][: len(narration) - a0]
    sf.write(out / "voice.wav", narration[: int(total * voice.sr)], voice.sr)
    write_ass(out / "captions.ass", cues, fmt)

    # scene clips
    segs = []
    for i, sc in enumerate(scenes):
        bg, ov = (layout_short if fmt == "short" else layout_video)(sc, sc["img"], sc["number"], W, H)
        preview = bg.convert("RGBA")
        preview.alpha_composite(ov)
        preview.convert("RGB").save(out / f"frame-{i:02d}.jpg", quality=85)
        seg = out / f"scene-{i:02d}.mp4"
        render_segment((bg, ov), sc["frames"], MOTIONS[i % len(MOTIONS)], W, H, seg)
        segs.append(seg)
        print(f"Scene {i + 1}/{len(scenes)} rendered ({sc['dur']:.1f}s): {sc['heading']}")

    music, is_file = music_track(args.slug, total, out)

    # final assembly
    inputs = []
    for s in segs:
        inputs += ["-i", str(s)]
    inputs += ["-i", str(out / "voice.wav")]
    inputs += (["-stream_loop", "-1"] if is_file else []) + ["-i", str(music)]
    vi, mi = len(segs), len(segs) + 1
    graph, prev, acc = [], "[0:v]", 0.0
    transitions = ["fade", "smoothleft", "fade", "smoothright"]
    for i in range(1, len(segs)):
        acc += scenes[i - 1]["dur"] - XFADE
        graph.append(f"{prev}[{i}:v]xfade=transition={transitions[i % 4]}:duration={XFADE}:offset={acc:.3f}[x{i}]")
        prev = f"[x{i}]"
    graph.append(f"{prev}ass={out / 'captions.ass'}:fontsdir={CACHE / 'fonts'},format=yuv420p[v]")
    fade_st = max(0.0, total - 2.5)
    graph.append(f"[{vi}:a]aresample=48000,asplit=2[va][vs]")
    graph.append(f"[{mi}:a]aresample=48000,volume=0.22,afade=t=in:d=1.5,afade=t=out:st={fade_st:.2f}:d=2.5[mus]")
    graph.append("[mus][vs]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400[duck]")
    graph.append("[va][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    final = out / f"{args.slug}.mp4"
    ff(*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
       "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
       "-r", str(FPS), "-g", str(FPS // 2), "-bf", "2",
       "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart", str(final))

    thumb = None
    if fmt == "video":
        thumb = out / f"{args.slug}-thumbnail.jpg"
        thumbnail(title, hero, thumb)

    yt_title = script.get("youtube_title") or re.sub(r"\s*\([^)]*\)", "", title).strip()
    manifest = {
        "title": yt_title[:100],
        "description": build_description(fm, desc, args.slug, products, fmt),
        "tags": script.get("tags") or default_tags(fm, title),
        "format": fmt, "width": W, "height": H,
        "duration_seconds": round(total, 2),
        "slug": args.slug, "blog_url": f"{SITE}/blog/{args.slug}/",
        "video": str(final), "thumbnail": str(thumb) if thumb else None,
        "voice": f"kokoro:{VOICE}" if voice.engine == "kokoro" else "elevenlabs:Aria",
        "script_writer": script["writer"],
        "scenes": [{"heading": s["heading"], "narration": s["narration"]} for s in scenes],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    for tmp in list(out.glob("scene-*")) + list(out.glob("src-*")):
        tmp.unlink(missing_ok=True)
    print(json.dumps({k: manifest[k] for k in ("title", "format", "duration_seconds", "voice", "script_writer")}))
    print(f"DONE: {final} ({final.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
