#!/usr/bin/env python3
import argparse, json, os, re, subprocess, textwrap, time, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W,H=1080,1920
FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_TTS_MODEL = "fal-ai/elevenlabs/tts/eleven-v3"
FAL_MUSIC_MODEL = "fal-ai/stable-audio-25/text-to-audio"

def fal_request(model, payload, timeout=900):
    key = os.environ.get("FAL_KEY", "").strip()
    if not key:
        raise RuntimeError("FAL_KEY GitHub secret is required for the fal.ai YouTube builder")
    req = urllib.request.Request(f"{FAL_QUEUE_BASE}/{model}", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        submitted = json.loads(r.read().decode())
    started = time.time()
    while time.time() - started < timeout:
        sreq = urllib.request.Request(submitted["status_url"], headers={"Authorization": f"Key {key}"})
        with urllib.request.urlopen(sreq, timeout=60) as r:
            status = json.loads(r.read().decode())
        if status.get("status") == "COMPLETED":
            rreq = urllib.request.Request(submitted["response_url"], headers={"Authorization": f"Key {key}"})
            with urllib.request.urlopen(rreq, timeout=60) as r:
                return json.loads(r.read().decode())
        if status.get("status") not in ("IN_QUEUE", "IN_PROGRESS"):
            raise RuntimeError(f"fal.ai job failed: {status}")
        time.sleep(3)
    raise RuntimeError(f"fal.ai job timed out: {model}")

def download_url(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Glimerz-Video-Builder/2.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        Path(path).write_bytes(r.read())
BG=(247,244,239); TEXT=(32,32,32); MUTED=(105,100,94); ACCENT=(55,80,62)

def fetch(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"Glimerz-Video-Builder/1.1"})
    with urllib.request.urlopen(req,timeout=30) as r:
        Path(path).write_bytes(r.read())

def parse_frontmatter(raw):
    m=re.match(r"^---\\n(.*?)\\n---\\n",raw,re.S)
    if not m:
        return {}, raw
    block=m.group(1)
    body=raw[m.end():]
    out={}
    lines=block.splitlines()
    current=None
    for line in lines:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:", line):
            key,val=line.split(":",1)
            key=key.strip(); val=val.strip()
            current=key
            if val:
                out[key]=val.strip('"').strip("'")
            else:
                out[key]=""
        elif current and line.startswith((" ","\\t")):
            # Preserve simple multiline YAML values such as description.
            continuation=re.sub(r"\\s+"," ",line.strip())
            if continuation:
                out[current]=(out.get(current,"")+" "+continuation).strip()
    out["product_photos"]=re.findall(r"photo:\\s*(https?://[^\\s]+)",block)
    return out, body

def clean_text(s):
    s=re.sub(r"\[([^\]]+)\]\([^\)]+\)",r"\1",s)
    s=re.sub(r"[*_#]","",s)
    return re.sub(r"\s+"," ",s).strip()

def extract_sections(body):
    matches=list(re.finditer(r"^##\s+(.+?)\s*$",body,re.M))
    sections=[]
    for i,m in enumerate(matches):
        heading=clean_text(m.group(1))
        start=m.end()
        end=matches[i+1].start() if i+1<len(matches) else len(body)
        chunk=body[start:end]
        paras=[clean_text(p) for p in re.split(r"\n\s*\n",chunk) if clean_text(p)]
        summary=re.split(r"(?<=[.!?])\s+",paras[0])[0] if paras else ""
        if heading and heading.lower()!="disclosure":
            sections.append((heading,summary[:210]))
    return sections

def font(size,bold=False):
    return ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",size)

def make_background(image,hero):
    canvas=Image.new("RGB",(W,H),BG)
    if image and hero:
        img=image.convert("RGB")
        scale=max(W/img.width,1200/img.height)
        img=img.resize((int(img.width*scale),int(img.height*scale)),Image.Resampling.LANCZOS)
        left=max(0,(img.width-W)//2); top=max(0,(img.height-1200)//2)
        img=img.crop((left,top,left+W,1200))
        canvas.paste(img,(0,0))
        shade=Image.new("RGBA",(W,1200),(0,0,0,55))
        canvas.paste(shade,(0,0),shade)
    return canvas

def make_slide(path,image,headline,sub="",number=None,hero=False):
    canvas=make_background(image,hero)
    d=ImageDraw.Draw(canvas)
    if hero:
        d.rectangle((0,1120,W,H),fill=BG)
        y=1215
    else:
        if image:
            img=image.convert("RGB")
            # Preserve the complete source photo instead of aggressively
            # cropping its sides. Fit it inside the visual panel and use the
            # Glimerz background around it when aspect ratios differ.
            panel_w, panel_h = W, 860
            scale=min(panel_w/img.width, panel_h/img.height)
            fitted=img.resize((int(img.width*scale),int(img.height*scale)),Image.Resampling.LANCZOS)
            x=(panel_w-fitted.width)//2; y_img=(panel_h-fitted.height)//2
            canvas.paste(fitted,(x,y_img))
            d=ImageDraw.Draw(canvas)
            d.rectangle((0,860,W,H),fill=BG)
            y=1010
        else:
            d.rounded_rectangle((65,120,180,235),radius=24,fill=ACCENT)
            y=470
        if number is not None:
            d.rounded_rectangle((65,120,180,235),radius=24,fill=ACCENT)
            d.text((91,142),f"{number:02d}",font=font(42,True),fill=(255,255,255))
        d.text((70,y-80 if image else 330),"GLIMERZ",font=font(28,True),fill=ACCENT)
    for line in textwrap.wrap(headline,width=25)[:5]:
        d.text((70,y),line,font=font(66 if hero else 58,True),fill=TEXT)
        y+=72
    if sub:
        y=min(y+24,1710)
        for line in textwrap.wrap(sub,width=48)[:4]:
            d.text((70,y),line,font=font(28),fill=MUTED)
            y+=38
    d.text((70,1838),"GLIMERZ  •  HOME & KITCHEN",font=font(25,True),fill=ACCENT)
    canvas.save(path,quality=95)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slug",required=True)
    ap.add_argument("--repo",default="kmbajwa1972/Glimerz-site")
    ap.add_argument("--out",default="build/video")
    args=ap.parse_args()
    args.slug=re.sub(r"^\\s*slug\\s*:\\s*", "", args.slug, flags=re.I).strip().strip("\\\"").strip("\\'")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.slug):
        raise ValueError(f"Invalid slug: {args.slug!r}")
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)

    raw_url=f"https://raw.githubusercontent.com/{args.repo}/main/content/blog/{args.slug}.md"
    raw=urllib.request.urlopen(raw_url,timeout=30).read().decode("utf-8")
    fm,body=parse_frontmatter(raw)
    title=fm.get("title",args.slug.replace("-"," ").title())
    desc=fm.get("description","")

    # Use Glimerz-hosted static images for reliable video rendering.
    # We intentionally do not depend on Amazon/external product image URLs.
    is_kitchen = bool(re.search(r"kitchen|cook|knife|utensil|appliance|gadget", (title + " " + args.slug).lower()))
    if is_kitchen:
        # Use clean kitchen photography for video slides. Several older kitchen
        # assets contain baked-in editorial text, which gets cropped in 9:16.
        # Keep those out of the video source pool.
        static_names = [
            "kitchen-15.jpg", "kitchen-16.jpg", "kitchen-17.jpg"
        ]
    else:
        # Prefer the article's own Glimerz hero image when it is a local static asset.
        local_hero = fm.get("image", "")
        hero_name = Path(local_hero).name if local_hero.startswith("/images/") else "home-24.png"
        home_pool = [hero_name, "home-21.png", "home-22.png", "home-23.png", "home-24.png", "home-15.jpg", "home-16.jpg"]
        static_names = list(dict.fromkeys(home_pool))

    static_images=[]
    for n,name in enumerate(static_names, start=1):
        try:
            p=out/f"static-{n}-{name}"
            fetch(f"https://raw.githubusercontent.com/{args.repo}/main/static/images/{name}", p)
            static_images.append(Image.open(p).convert("RGB"))
            print(f"Static image loaded: {name}")
        except Exception as e:
            print(f"Static image skipped: {name} ({e})")

    if not static_images:
        raise RuntimeError("No Glimerz static images could be loaded")

    # First image is used for the title slide; all content slides use the
    # remaining static images in sequence. This guarantees visible imagery.
    image = static_images[0]
    visual_images = static_images
    image_url = f"https://raw.githubusercontent.com/{args.repo}/main/static/images/{static_names[0]}"

    sections=extract_sections(body)
    if not sections:
        raise RuntimeError("No article sections were found")
    sections=sections[:6]

    slides=[]
    f=out/"slide-01.png"
    make_slide(f,image,title,"A practical Glimerz guide to choosing the right mixing bowls and utensils.",hero=True)
    slides.append(f)

    for idx,(heading,summary) in enumerate(sections,start=2):
        f=out/f"slide-{idx:02d}.png"
        visual=visual_images[(idx-2) % len(visual_images)] if visual_images else None
        make_slide(f,visual,heading,summary,number=idx-1,hero=False)
        slides.append(f)

    f=out/f"slide-{len(slides)+1:02d}.png"
    make_slide(f,None,"Read the full guide on Glimerz",
               "See the complete mixing bowls and utensils guide on Glimerz.",
               number=len(slides),hero=False)
    slides.append(f)

    inputs=[]; filters=[]
    for i,s in enumerate(slides):
        inputs += ["-loop","1","-t","5","-i",str(s)]
        filters.append(f"[{i}:v]scale={W}:{H},format=yuv420p,setpts=PTS-STARTPTS[v{i}]")

    prev="[v0]"; elapsed=5.0
    for i in range(1,len(slides)):
        outv=f"[x{i}]"; offset=elapsed-0.35
        filters.append(f"{prev}[v{i}]xfade=transition=fade:duration=0.35:offset={offset:.2f}{outv}")
        prev=outv; elapsed+=4.65

    slides_mp4=out/f"{args.slug}-slides.mp4"
    subprocess.run([
        "ffmpeg","-y",*inputs,"-filter_complex",";".join(filters),
        "-map",prev,"-r","30","-c:v","libx264","-preset","veryfast","-crf","23",
        "-pix_fmt","yuv420p","-movflags","+faststart",str(slides_mp4)
    ],check=True)

    # Keep video generation deterministic: use the rendered Glimerz slides as the visual track.
    # This avoids the unpredictable queue time of generative video models while retaining
    # natural ElevenLabs narration and original background music.
    voice_parts = [f"Today on Glimerz: {title}."]
    for heading, summary in sections[:4]:
        voice_parts.append(f"{heading}. {summary}")
    voice_script = clean_text(" ".join(voice_parts))[:750]
    tts = fal_request(FAL_TTS_MODEL, {"text": voice_script, "voice": "Aria", "stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "speed": 0.98, "language_code": "en", "apply_text_normalization": "auto", "output_format": "mp3_44100_128"})
    voice_file = out/"voiceover.mp3"
    download_url(tts["audio"]["url"], voice_file)

    music = fal_request(FAL_MUSIC_MODEL, {
        "prompt": "Warm modern lifestyle instrumental for a home and kitchen YouTube video, soft acoustic guitar, light piano, subtle brushed percussion, relaxed upscale mood, no vocals, no spoken words, clean background music.",
        "seconds_total": 45,
        "num_inference_steps": 8,
        "guidance_scale": 1,
    })
    music_value = music.get("audio")
    music_url = music_value.get("url") if isinstance(music_value, dict) else music_value
    if not music_url:
        raise RuntimeError(f"fal.ai Stable Audio returned no audio URL: {music}")
    music_file = out/"music.wav"
    download_url(music_url, music_file)

    mp4=out/f"{args.slug}.mp4"
    subprocess.run([
        "ffmpeg","-y",
        "-i",str(slides_mp4),
        "-i",str(voice_file),
        "-stream_loop","-1","-i",str(music_file),
        "-filter_complex",
        "[2:a]volume=0.24[music];[1:a]volume=1.65[voice];"
        "[voice][music]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
        "-map","0:v","-map","[a]",
        "-c:v","libx264","-preset","veryfast","-crf","22","-r","30",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest",
        "-movflags","+faststart",str(mp4)
    ],check=True)

    manifest={
        "title":title,"description":desc,"slug":args.slug,"video":str(mp4),
        "duration_seconds":round(len(slides)*5-0.35*(len(slides)-1),2),
        "source_image":image_url,"slides":len(slides),"audio":{"voiceover":"fal.ai ElevenLabs Eleven v3","music":"fal.ai Stable Audio 2.5"},"voice_model":FAL_TTS_MODEL,"music_model":FAL_MUSIC_MODEL,
        "sections":[h for h,_ in sections],"voiceover_script":voice_script
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest))

if __name__=="__main__":
    main()
