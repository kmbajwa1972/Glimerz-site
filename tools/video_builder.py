#!/usr/bin/env python3
import argparse, json, re, subprocess, textwrap, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W,H=1080,1920
BG=(247,244,239); TEXT=(32,32,32); MUTED=(105,100,94); ACCENT=(55,80,62)

def fetch(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"Glimerz-Video-Builder/1.1"})
    with urllib.request.urlopen(req,timeout=30) as r:
        Path(path).write_bytes(r.read())

def parse_frontmatter(raw):
    m=re.match(r"^---\n([\\s\\S]*?)\n---\n",raw)
    if not m:
        return {}, raw
    block=m.group(1)
    body=raw[m.end():]
    out={}
    for key in ("title","description","image"):
        mm=re.search(rf"^{key}:\s*(.+?)(?=\n[A-Za-z_][A-Za-z0-9_-]*:|\n[A-Za-z_][A-Za-z0-9_-]*:\s|$)",block,re.M|re.S)
        if mm:
            out[key]=re.sub(r"\s+"," ",mm.group(1).strip()).strip('"')
    photos=re.findall(r"^\s+photo:\s*(https?://[^\s]+)",block,re.M)
    out["product_photos"]=photos[:6]
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
            scale=max(W/img.width,860/img.height)
            img=img.resize((int(img.width*scale),int(img.height*scale)),Image.Resampling.LANCZOS)
            left=max(0,(img.width-W)//2); top=max(0,(img.height-860)//2)
            img=img.crop((left,top,left+W,top+860))
            canvas.paste(img,(0,0))
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
        static_names = [
            "kitchen-21.png", "kitchen-22.png", "kitchen-24.png",
            "kitchen-15.jpg", "kitchen-16.jpg", "kitchen-17.jpg"
        ]
    else:
        static_names = [
            "home-21.png", "home-22.png", "home-23.png", "home-24.png",
            "home-15.jpg", "home-16.jpg"
        ]

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
    make_slide(f,image,title,"A practical Glimerz guide to choosing the right rug size.",hero=True)
    slides.append(f)

    for idx,(heading,summary) in enumerate(sections,start=2):
        f=out/f"slide-{idx:02d}.png"
        visual=visual_images[(idx-2) % len(visual_images)] if visual_images else None
        make_slide(f,visual,heading,summary,number=idx-1,hero=False)
        slides.append(f)

    f=out/f"slide-{len(slides)+1:02d}.png"
    make_slide(f,None,"Read the full guide on Glimerz",
               "Measure your room, consider your furniture, and choose the rug size that fits your space.",
               number=len(slides),hero=False)
    slides.append(f)

    inputs=[]; filters=[]
    for i,s in enumerate(slides):
        inputs += ["-loop","1","-t","4","-i",str(s)]
        filters.append(f"[{i}:v]scale={W}:{H},format=yuv420p,setpts=PTS-STARTPTS[v{i}]")

    prev="[v0]"; elapsed=4.0
    for i in range(1,len(slides)):
        outv=f"[x{i}]"; offset=elapsed-0.35
        filters.append(f"{prev}[v{i}]xfade=transition=fade:duration=0.35:offset={offset:.2f}{outv}")
        prev=outv; elapsed+=3.65

    mp4=out/f"{args.slug}.mp4"
    subprocess.run([
        "ffmpeg","-y",*inputs,"-filter_complex",";".join(filters),
        "-map",prev,"-r","30","-c:v","libx264","-preset","veryfast","-crf","23",
        "-pix_fmt","yuv420p","-movflags","+faststart",str(mp4)
    ],check=True)

    manifest={
        "title":title,"description":desc,"slug":args.slug,"video":str(mp4),
        "duration_seconds":round(len(slides)*4-0.35*(len(slides)-1),2),
        "source_image":image_url,"slides":len(slides),
        "sections":[h for h,_ in sections]
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest))

if __name__=="__main__":
    main()
