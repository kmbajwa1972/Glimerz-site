#!/usr/bin/env python3
import argparse, json, os, re, subprocess, textwrap, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W,H=1080,1920
BG=(247,244,239); TEXT=(32,32,32); MUTED=(105,100,94); ACCENT=(55,80,62)

def fetch(url,path):
    req=urllib.request.Request(url,headers={"User-Agent":"Glimerz-Video-Builder/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r: Path(path).write_bytes(r.read())

def parse_frontmatter(raw):
    m=re.match(r"^---\n([\s\S]*?)\n---",raw)
    if not m:return {}
    b=m.group(1); out={}
    for key in ["title","description","image"]:
        mm=re.search(rf"^{key}:\s*(.+?)(?=\n\w+:|\n\w[\w-]*:\s|$)",b,re.M|re.S)
        if mm: out[key]=re.sub(r"\s+"," ",mm.group(1).strip()).strip('"')
    return out

def extract_points(raw):
    body=raw.split("\n---\n",1)[-1] if "\n---\n" in raw else raw
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    points=[]
    for line in lines:
        if line.startswith("## "): points.append(line[3:].strip())
        elif re.match(r"^\*\*[^*]+\*\*\s*$",line): points.append(re.sub(r"[*]","",line).strip())
    if len(points)<4:
        for p in re.split(r"\n\s*\n",body):
            p=re.sub(r"[*_#]","",p).strip()
            if len(p)>70: points.append(re.split(r"(?<=[.!?])\s+",p)[0][:150])
            if len(points)>=5: break
    return points[:5]

def font(size,bold=False):
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",size)

def fit_cover(img):
    img=img.convert("RGB"); scale=max(W/img.width,H/img.height)
    img=img.resize((int(img.width*scale),int(img.height*scale)),Image.Resampling.LANCZOS)
    l=(img.width-W)//2; t=(img.height-H)//2
    return img.crop((l,t,l+W,t+H))

def make_slide(path,image,headline,sub=None,number=None):
    canvas=Image.new("RGB",(W,H),BG)
    if image:
        pic=fit_cover(image).resize((W,1200),Image.Resampling.LANCZOS)
        canvas.paste(pic,(0,0))
        shade=Image.new("RGBA",(W,1200),(0,0,0,35))
        canvas.paste(shade,(0,0),shade)
    d=ImageDraw.Draw(canvas); d.rectangle((0,1200,W,H),fill=BG)
    if number:d.text((70,1270),f"{number:02d}",font=font(42,True),fill=ACCENT)
    y=1350 if number else 1280
    for line in textwrap.wrap(headline,width=25)[:4]:
        d.text((70,y),line,font=font(70,True),fill=TEXT); y+=82
    if sub:
        y=min(y+25,1740)
        for line in textwrap.wrap(sub,width=48)[:4]:
            d.text((70,y),line,font=font(31),fill=MUTED); y+=42
    d.text((70,1840),"GLIMERZ  •  HOME & KITCHEN",font=font(25,True),fill=ACCENT)
    canvas.save(path,quality=95)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--slug",required=True); ap.add_argument("--repo",default="kmbajwa1972/Glimerz-site"); ap.add_argument("--out",default="build/video")
    args=ap.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    raw_url=f"https://raw.githubusercontent.com/{args.repo}/main/content/blog/{args.slug}.md"
    raw=urllib.request.urlopen(raw_url,timeout=30).read().decode("utf-8"); fm=parse_frontmatter(raw)
    title=fm.get("title",args.slug.replace("-"," ").title()); desc=fm.get("description","")
    image=None; image_url=fm.get("image")
    if image_url:
        if image_url.startswith("/"): image_url="https://glimerz.com"+image_url
        p=out/"hero.jpg"; fetch(image_url,p); image=Image.open(p)
    points=extract_points(raw); slides=[]
    f=out/"slide-01.png"; make_slide(f,image,title,"Practical ideas from the full Glimerz article."); slides.append(f)
    for i,p in enumerate(points[:4],start=2):
        f=out/f"slide-{i:02d}.png"; make_slide(f,image,p,desc if i==2 else "See the full Glimerz article for practical details and examples.",i-1); slides.append(f)
    f=out/f"slide-{len(slides)+1:02d}.png"; make_slide(f,image,"Read the full guide on Glimerz",title[:120],len(slides)); slides.append(f)
    inputs=[]; filters=[]
    for i,s in enumerate(slides):
        inputs += ["-loop","1","-t","4","-i",str(s)]
        filters.append(f"[{i}:v]scale={W}:{H},format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
    prev="[v0]"
    for i in range(1,len(slides)):
        outv=f"[x{i}]"; filters.append(f"{prev}[v{i}]xfade=transition=fade:duration=0.35:offset={i*4-0.35}{outv}"); prev=outv
    mp4=out/f"{args.slug}.mp4"
    subprocess.run(["ffmpeg","-y",*inputs,"-filter_complex",";".join(filters),"-map",prev,"-r","30","-c:v","libx264","-preset","veryfast","-crf","23","-movflags","+faststart",str(mp4)],check=True)
    manifest={"title":title,"description":desc,"slug":args.slug,"video":str(mp4),"duration_seconds":len(slides)*4-0.35*(len(slides)-1),"source_image":image_url,"slides":len(slides)}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)); print(json.dumps(manifest))

if __name__=="__main__":main()
