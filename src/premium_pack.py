"""Generate an additive, source-independent Tan Phat editing pack.

No source video is inferred. All timeline positions require source review.
Run: .venv/bin/python src/premium_pack.py --output outputs/CAPCUT_PREMIUM_EDIT_PACK
"""
import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import textwrap
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from generate_sfx import RATE, piano, timeline, synthesize
from build_pack import extra_sounds

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parent
FONT = SOURCE/'NotoSans-Bold.ttf' if (SOURCE/'NotoSans-Bold.ttf').is_file() else Path('/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf')
W, H, FPS = 960, 540, 24
TOTAL = 314
SFX = [
('record_scratch','record_scratch'),('sad_piano_sting','sad_piano'),
('dramatic_boom','dramatic_hit'),('awkward_silence_accent','ui_pop'),
('cartoon_pop','ui_pop'),('comedic_boing','comedy_boing'),
('spring_bounce','comedy_boing'),('funny_whistle','laser_zap'),
('surprise_blip','robot_blip'),('reverse_whoosh','whoosh_reverse'),
('tiny_fail_sound','failure_buzz'),('light_rimshot','clock_tick'),
('digital_beep','digital_beep'),('robot_startup','digital_scan'),
('futuristic_scan','digital_scan'),('interface_click','ui_click'),
('smart_device_activation','ui_confirm'),('sensor_detection','message_received'),
('robotic_servo','glitch_short'),('tech_notification','notification'),
('data_processing_pulse','glitch_stutter'),('electronic_reveal','swoosh_sparkle'),
('charging_station_chime','success_chime'),('ai_interface_pulse','robot_blip'),
('short_whoosh','whoosh_short'),('long_whoosh','whoosh_long'),
('fast_swipe','whoosh_pan'),('text_pop','ui_pop'),('text_impact','impact_soft'),
('zoom_transition','whoosh_long'),('swipe_transition','whoosh_short'),
('reverse_transition','whoosh_reverse'),('soft_riser','riser_bright'),
('sub_drop','impact_sub'),('cinematic_hit','impact_cinematic'),
('glass_sparkle','magic_chime'),('premium_logo_reveal','success_chime'),
('elegant_chime','notification'),('soft_tonal_impact','impact_soft'),
('uplifting_transition','happy_transition')]
ANIMS = ['Bounce In','Elastic Pop','Scale Punch','Shake X','Shake Y','Typewriter',
'Word-by-Word Reveal','Character-by-Character Reveal','Slide Left','Slide Right',
'Slide Up','Slide Down','Zoom In','Zoom Out','Rotation Pop','Glitch Reveal',
'Digital Scan','Blur-to-Sharp','Kinetic Split','Cinematic Fade','Overshoot Scale',
'Spring Drop','Flash Reveal','Mask Wipe','Highlight Sweep','Tracking Expansion',
'Neon Pulse','Floating Text','Staggered Letters','Logo End Reveal']
COLORS = {'Comedy':(255,220,64), 'Technology':(90,237,255),
          'Premium':(240,205,130), 'Lifestyle':(210,246,224)}
VISUALS = ['robot_arrow','sensor_ring','scan_line','question_marks','speech_bubble',
           'hud_frame','button_halo','robot_cleaning_path','check_mark',
           'product_sparkles','end_card_accent']


def write_json(p, obj):
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def write_csv(p, rows):
    with p.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def pcm(p,x,peak_db=-3):
    x=np.asarray(x,dtype=float).copy()
    if x.ndim==2: x=x.mean(axis=1)
    n=min(round(.012*RATE),len(x)//2)
    x[:n]*=np.linspace(0,1,n); x[-n:]*=np.linspace(1,0,n)
    x*=10**(peak_db/20)/max(abs(x).max(),1e-12)
    wavfile.write(p,RATE,np.round(x*32767).astype(np.int16))


def make_sfx(out):
    folder=out/'01_SFX_WAV'
    bank={**dict(extra_sounds()),**synthesize()}
    records=[]; sounds={}; preview=[]; cursor=0.
    for i,(name,base) in enumerate(SFX):
        x=bank[base].copy()
        if x.ndim==2: x=x.mean(axis=1)
        # Each variant receives new synthesized layers, envelopes or pitch design.
        t=np.arange(len(x))/RATE
        rng=np.random.default_rng(100+i)
        layer=np.sin(2*np.pi*(220+37*i)*t)*np.exp(-(4+i%7)*t)
        if name=='awkward_silence_accent':
            t=timeline(1.6); x=.25*np.sin(2*np.pi*165*t)*np.exp(-16*t)
            x+=.04*np.sin(2*np.pi*330*t)*np.exp(-24*t)
        elif name in ['funny_whistle','spring_bounce']:
            freq=(850+300*np.sin(2*np.pi*3*t)*np.exp(-2*t)) if name=='funny_whistle' else (150+220*np.cos(2*np.pi*7*t)*np.exp(-3*t))
            x=.65*np.sin(2*np.pi*np.cumsum(freq)/RATE)*np.exp(-2.6*t)+.18*layer
        elif name=='light_rimshot':
            x=rng.normal(size=len(t))*np.exp(-65*t)*.35
            x+=sum(.22*np.sin(2*np.pi*f*t)*np.exp(-40*t) for f in [420,1280,2240])
        elif name=='robotic_servo':
            freq=90+80*np.sin(np.pi*t/t[-1])
            x=.3*np.sin(2*np.pi*np.cumsum(freq)/RATE)+.12*np.sin(2*np.pi*980*t)
            x*=np.sin(np.pi*t/t[-1])**2*(.65+.35*np.sin(2*np.pi*35*t))
        elif name in ['data_processing_pulse','ai_interface_pulse','sensor_detection','robot_startup']:
            x*=.45
            for j,freq in enumerate([440+20*i,660+20*i,880+20*i]):
                start=round(j*.16*RATE); u=t[:len(t)-start]
                x[start:]+=.25*np.sin(2*np.pi*freq*u)*np.exp(-12*u)*np.minimum(u/.005,1)
        else:
            x=.82*x+.12*layer
            # Add delayed harmonic air to premium sounds, transient detail to motion.
            if i>=35:
                delay=round(.13*RATE)
                x[delay:]+=.18*x[:-delay].copy()
                x+=.06*np.sin(2*np.pi*3520*t)*np.exp(-4*t)*np.minimum(t/.01,1)
            elif i>=24:
                air=signal.sosfilt(signal.butter(2,[1500,9500],btype='bandpass',fs=RATE,output='sos'),rng.normal(size=len(t)))
                x+=.09*air*np.sin(np.pi*t/t[-1])**2
        path=folder/f'{i+1:02}_{name}.wav'; pcm(path,x)
        _,a=wavfile.read(path); sounds[name]=a.astype(float)/32768
        if i:
            preview.append(np.zeros(2*RATE,dtype=np.int16)); cursor+=2
        records.append(dict(ID=i+1,Name=name,File=str(path.relative_to(out)),Duration=len(a)/RATE,
                            Preview_Start=round(cursor,6),Layers='base synthesis + custom tonal/transient/air layers',Peak_dBFS=round(20*np.log10(abs(a.astype(float)).max()/32768),3)))
        preview.append(a); cursor+=len(a)/RATE
    wavfile.write(out/'SFX_PREVIEW.wav',RATE,np.concatenate(preview))
    write_csv(folder/'sfx_inventory.csv',records)
    return sounds


def font(n): return ImageFont.truetype(str(FONT),n)


def text_tile(text,style,size=(W,H),highlight=False):
    text=unicodedata.normalize('NFC',text)
    im=Image.new('RGBA',size); d=ImageDraw.Draw(im)
    n=52
    while True:
        f=font(n); lines=[]; line=''
        for word in text.split():
            test=(line+' '+word).strip()
            if d.textlength(test,font=f)>size[0]*.83 and line:
                lines.append(line); line=word
            else: line=test
        lines.append(line)
        if len(lines)<=3 or n<=26: break
        n-=2
    spacing=12; boxes=[d.textbbox((0,0),s,font=f,stroke_width=2) for s in lines]
    heights=[b[3]-b[1] for b in boxes]; y=(size[1]-sum(heights)-spacing*(len(lines)-1))/2
    color=COLORS[style]
    for line,b,h in zip(lines,boxes,heights):
        x=(size[0]-d.textlength(line,font=f))/2
        d.text((x+3,y-b[1]+5),line,font=f,fill=(0,0,0,150),stroke_width=4,stroke_fill=(0,0,0,100))
        d.text((x,y-b[1]),line,font=f,fill=(*color,255),stroke_width=3 if style=='Comedy' else 1,stroke_fill=(10,17,25,255))
        y+=h+spacing
    return im


def state(index,q):
    """Motion curves shared by rendered output and exported sampled keyframes."""
    a=min(q/.3,1); exit=min((1-q)/.18,1); op=max(0,min(a,exit)); sc=1.; x=y=rot=0.
    if index==0: y=-160*abs(math.cos(a*2.5*math.pi))*(1-a)
    elif index==1: sc=1-math.exp(-6*a)*math.cos(10*a)
    elif index==2: sc=1+.25*math.sin(math.pi*a)*math.exp(-a)
    elif index==3: x=18*math.sin(48*q)*(1-q)
    elif index==4: y=13*math.sin(48*q)*(1-q)
    elif index in [8,9]: x=(-1 if index==8 else 1)*300*(1-a)**3
    elif index in [10,11]: y=(1 if index==10 else -1)*160*(1-a)**3
    elif index==12: sc=.5+.5*a
    elif index==13: sc=1.7-.7*a
    elif index==14: sc=.6+.4*a; rot=25*(1-a)
    elif index==15: x=(12 if int(q*40)%2 else -12)*(1-a)
    elif index==19: op=max(0,min(q/.4,(1-q)/.25,1))
    elif index==20: sc=1+(2.70158*(a-1)**3+1.70158*(a-1)**2)
    elif index==21: y=-150*math.exp(-5*a)*math.cos(13*a)
    elif index==22: op=max(0,min(exit,1 if a>.6 else (.3 if int(q*40)%2 else 1)))
    elif index==26: op*=.75+.25*math.sin(2*math.pi*q*3)**2
    elif index==27: y=9*math.sin(2*math.pi*q)
    elif index==29: sc=.9+.1*a; op*=a
    return dict(scale=round(max(.02,sc),6),opacity=round(op,6),position=[round(W/2+x,3),round(H/2+y,3)],rotation=round(rot,3))


def render_text(text,style,index,q):
    reveal=min(q/.5,1)
    if index==5:
        # A terminal-style cursor distinguishes Typewriter from the smooth glyph reveal.
        text=text[:int(len(text)*reveal)]+('▏' if reveal<1 and int(q*16)%2==0 else '')
    elif index==6: text=' '.join(text.split()[:max(1,math.ceil(len(text.split())*reveal))])
    elif index==7: text=text[:int(len(text)*reveal)]
    tile=text_tile(text,style)
    if index in [16,23]:
        mask=Image.new('L',(W,H)); ImageDraw.Draw(mask).rectangle((0,0,int(W*reveal),H),fill=255)
        tile.putalpha(Image.fromarray(np.minimum(np.array(tile.getchannel('A')),np.array(mask))))
        if index==16 and reveal<1:
            ImageDraw.Draw(tile).line((W*reveal,130,W*reveal,410),fill=(80,240,255,200),width=3)
    if index==17: tile=tile.filter(ImageFilter.GaussianBlur(12*(1-min(q/.4,1))))
    if index==18:
        a=min(q/.3,1); shifted=Image.new('RGBA',(W,H))
        shifted.alpha_composite(tile.crop((0,0,W,H//2)),(int(-100*(1-a)),0))
        shifted.alpha_composite(tile.crop((0,H//2,W,H)),(int(100*(1-a)),H//2)); tile=shifted
    if index==24:
        sweep=Image.new('RGBA',(W,H)); sd=ImageDraw.Draw(sweep)
        x=int(-120+(W+240)*q); sd.polygon([(x-60,160),(x,160),(x+70,380),(x+10,380)],fill=(255,255,255,180))
        mask=tile.getchannel('A'); sweep.putalpha(Image.fromarray((np.array(sweep.getchannel('A')).astype(float)*np.array(mask)/255).astype('uint8')))
        tile=Image.alpha_composite(tile,sweep)
    if index==25:
        # Animate spacing of individual glyphs while keeping the baseline fixed.
        tile=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(tile); f=font(34)
        chars=text; spacing=8*(1-min(q/.5,1)); width=sum(d.textlength(c,font=f) for c in chars)+spacing*(len(chars)-1)
        if width>W*.9: f=font(24); width=sum(d.textlength(c,font=f) for c in chars)+spacing*(len(chars)-1)
        x=(W-width)/2
        for c in chars:
            d.text((x,H/2),c,font=f,anchor='lm',fill=(*COLORS[style],255)); x+=d.textlength(c,font=f)+spacing
    if index==28:
        tile=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(tile); f=font(34)
        widths=[d.textlength(c,font=f) for c in text]; x=(W-sum(widths))/2
        for j,(c,width) in enumerate(zip(text,widths)):
            local=max(0,min(1,q/.5-j/max(len(text),1)))
            d.text((x,H/2+30*(1-local)),c,font=f,anchor='lm',fill=(*COLORS[style],round(255*local))); x+=width
    if index==26:
        glow=tile.filter(ImageFilter.GaussianBlur(7)); tile=Image.alpha_composite(glow,tile)
    s=state(index,q)
    sw,sh=max(1,round(W*s['scale'])),max(1,round(H*s['scale']))
    tile=tile.resize((sw,sh),Image.Resampling.BICUBIC)
    if s['rotation']: tile=tile.rotate(s['rotation'],resample=Image.Resampling.BICUBIC,expand=True)
    tile.putalpha(tile.getchannel('A').point(lambda v:round(v*s['opacity'])))
    canvas=Image.new('RGBA',(W,H)); canvas.alpha_composite(tile,(round(s['position'][0]-tile.width/2),round(s['position'][1]-tile.height/2)))
    return canvas


def encode(path,frames,fps=FPS,alpha=True,audio=None):
    cmd=['ffmpeg','-nostdin','-v','error','-n','-threads','2','-f','rawvideo','-pix_fmt','rgba','-s',f'{W}x{H}','-r',str(fps),'-i','pipe:0']
    if audio: cmd+=['-i',str(audio)]
    if alpha: cmd+=['-an','-c:v','qtrle','-pix_fmt','argb']
    else:
        cmd+=['-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-threads','2']
        if audio: cmd+=['-c:a','aac','-b:a','160k','-shortest']
        cmd+=['-movflags','+faststart']
    cmd+=[str(path)]
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for frame in frames: p.stdin.write(frame.convert('RGBA').tobytes())
        p.stdin.close(); error=p.stderr.read(); rc=p.wait()
        if rc: raise RuntimeError(error.decode())
    except BaseException:
        if p.poll() is None: p.kill(); p.wait()
        raise


def visual(name,q):
    im=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(im); c=(80,235,255,230)
    pulse=round(12*math.sin(2*math.pi*q))
    if name=='robot_arrow':
        x=400+round(20*math.sin(2*math.pi*q)); d.line((x,170,x+150,310),fill=c,width=8); d.line((x+100,310,x+150,310,x+150,260),fill=c,width=8)
    elif name in ['sensor_ring','button_halo']:
        r=65+pulse if name=='sensor_ring' else 45+round(q*60)
        d.ellipse((W/2-r,H/2-r,W/2+r,H/2+r),outline=c,width=4)
        d.arc((W/2-r-12,H/2-r-12,W/2+r+12,H/2+r+12),q*360,q*360+110,fill=c,width=4)
    elif name=='scan_line':
        y=100+340*q; d.line((120,y,840,y),fill=c,width=4)
        for j in range(1,15): d.line((120,y-j*2,840,y-j*2),fill=(80,235,255,max(0,100-j*6)),width=2)
    elif name=='question_marks':
        for j in range(3): d.text((350+j*100,230+15*math.sin(q*6+j)), '?',font=font(90),fill=c)
    elif name=='speech_bubble':
        d.rounded_rectangle((200,170,760,330),radius=30,fill=(15,30,50,150),outline=c,width=3); d.polygon([(620,330),(650,370),(680,330)],fill=c)
    elif name=='hud_frame':
        for x,y,dx,dy in [(150,110,1,1),(810,110,-1,1),(150,430,1,-1),(810,430,-1,-1)]:
            d.line((x+65*dx,y,x,y,x,y+50*dy),fill=c,width=4)
        d.line((200,450,200+560*q,450),fill=c,width=3)
    elif name=='robot_cleaning_path':
        pts=[(220+j*30,270+75*math.sin(j*.55)) for j in range(18)]
        d.line(pts[:max(2,int(len(pts)*q))],fill=c,width=5)
    elif name=='check_mark':
        d.line([(350,270),(440,350),(620,170)][:2 if q<.3 else 3],fill=(150,255,180,255),width=16)
    elif name=='product_sparkles':
        for j in range(14):
            x=160+(j*151)%640; y=120+(j*83)%300; r=3+5*abs(math.sin(q*6+j))
            d.line((x-r,y,x+r,y),fill=c,width=2); d.line((x,y-r,x,y+r),fill=c,width=2)
    elif name=='end_card_accent':
        width=round(300*min(q/.3,1)); d.line((480-width,365,480+width,365),fill=(240,205,130,255),width=4)
        d.rectangle((120,85,840,455),outline=(240,205,130,100),width=2)
    return im


def choose(cue):
    s=cue['start']; text=cue['text']; direction=cue['direction'].lower()
    if 20<=s<32: style='Comedy'
    elif 70<=s<178 or 227<=s<274: style='Technology'
    elif s>=274 and s<302: style='Lifestyle'
    else: style='Premium'
    rules=[('scale punch',2),('elastic',1),('shake',3),('typewriter',5),('spring',21),('word',6),('slide up',10),('slide',8),('scan',16),('mask',23),('highlight',24),('floating',27),('staggered',28),('bounce',0),('overshoot',20),('glow',26),('logo',29),('fade',19),('reveal',17),('pop',1)]
    anim=next((n for word,n in rules if word in direction),19)
    if cue['audio_only']: sound='sad_piano_sting'
    elif 'scratch' in direction: sound='record_scratch'
    elif 'dramatic' in direction: sound='dramatic_boom'
    elif 'scan' in direction: sound='futuristic_scan'
    elif 'sensor' in direction or 'CẢM BIẾN' in text: sound='sensor_detection'
    elif 'click' in direction: sound='interface_click'
    elif 'whoosh' in direction: sound='short_whoosh'
    elif style=='Comedy': sound='cartoon_pop' if anim in [0,1] else 'text_impact'
    elif style=='Technology': sound='electronic_reveal' if 'reveal' in direction else 'digital_beep'
    elif s>=310: sound='premium_logo_reveal'
    elif style=='Lifestyle': sound='soft_tonal_impact'
    else: sound='elegant_chime'
    return style,anim,sound


def tc(sec):
    ms=round(sec*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'


def visual_gallery(out):
    def frames():
        for name in VISUALS:
            for k in range(24):
                im=Image.new('RGBA',(W,H),(11,20,32,255))
                im=Image.alpha_composite(im,visual(name,k/23))
                d=ImageDraw.Draw(im)
                d.text((35,35),'VISUAL OVERLAY • MINH HỌA',font=font(28),fill=(240,205,130,255))
                d.text((35,475),name,font=font(24),fill=(220,240,250,255))
                yield im
    encode(out/'07_PREVIEW/VISUAL_OVERLAY_GALLERY.mp4',frames(),fps=12,alpha=False)


def build(out):
    if out.exists(): raise FileExistsError(f'Preserve existing output: {out}')
    zip_path=out.parent/('TAN_PHAT_PREMIUM_CAPCUT_PACK.zip' if out.name=='CAPCUT_PREMIUM_EDIT_PACK' else out.name+'.zip')
    if zip_path.exists(): raise FileExistsError(str(zip_path))
    original_hash={str(p):sha(p) for p in (ROOT/'outputs').rglob('*.wav')}
    for folder in ['01_SFX_WAV','02_TEXT_PNG','03_TEXT_ANIMATION','04_VISUAL_OVERLAYS','05_SUBTITLES','06_TIMELINE','07_PREVIEW','08_SOURCE_CODE']:
        (out/folder).mkdir(parents=True,exist_ok=True)
    sounds=make_sfx(out)
    print('Phase 1: 40 layered SFX and full audition WAV created',flush=True)
    cues=json.loads((SOURCE/'premium_cues.json').read_text())
    configs=[]
    for j,name in enumerate(ANIMS):
        configs.append(dict(id=j+1,name=name,duration=2.,fps=FPS,canvas=[W,H],position_units='pixels; centre anchor',easing='sampled curves in keyframes; renderer-specific reveal parameters',
            scale=1,opacity=1,position=[W/2,H/2],keyframes=[dict(time=round(q*2,6),**state(j,q)) for q in np.linspace(0,1,49)],
            reveal=dict(type=name,progress_window=[0,1],renderer='render_text',index=j),
            asset=f'03_TEXT_ANIMATION/{j+1:02}.mov'))
    write_json(out/'animation_config.json',configs)
    write_json(out/'02_TEXT_PNG/typography_styles.json',dict(colors=COLORS,font='Noto Sans Bold',reference_canvas=[W,H],status='provisional layout; source aspect ratio and face/product occlusion unknown'))
    for style in COLORS: text_tile('TẤN PHÁT • TRẢI NGHIỆM THÔNG MINH',style).save(out/f'02_TEXT_PNG/STYLE_{style}.png')
    for i,name in enumerate(ANIMS):
        style=list(COLORS)[i%4]
        encode(out/f'03_TEXT_ANIMATION/{i+1:02}.mov',(render_text('TẤN PHÁT • CÔNG NGHỆ THÔNG MINH',style,i,k/(2*FPS-1)) for k in range(2*FPS)))
        print(f'Animation {i+1}/30: {name}',flush=True)
    # Render actual cue text with the chosen animation, not just demonstration titles.
    events=[]; cue_sheet=[]; mix=np.zeros(TOTAL*RATE,dtype=np.float32)
    for i,c in enumerate(cues):
        style,a,sound=choose(c); start=c['start']
        end=min(start+2.4,cues[i+1]['start']-.08 if i+1<len(cues) else TOTAL,TOTAL)
        end=max(start+.12,end)
        textfile=''; movie=''
        if not c['audio_only']:
            textfile=f'02_TEXT_PNG/{i+1:03}.png'; movie=f'03_TEXT_ANIMATION/CUE_{i+1:03}.mov'
            text_tile(c['text'],style).save(out/textfile)
            duration=end-start; frames=max(3,round(duration*FPS))
            encode(out/movie,(render_text(c['text'],style,a,k/(frames-1)) for k in range(frames)))
        sf=next(f'01_SFX_WAV/{j+1:02}_{n}.wav' for j,(n,_) in enumerate(SFX) if n==sound)
        notes='DRAFT: user-provided timestamps; source MOV/SRT not available; verify wording, timing, ratio and placement. '
        if '200' in c['text']: notes+='Area claim requires verification. '
        if any(x in c['text'] for x in ['LỰC HÚT','CẢM BIẾN','TIẾT KIỆM']): notes+='Product claim requires source verification. '
        events.append(dict(ID=f'E{i+1:03}',Start=tc(start),End=tc(end),Duration=round(end-start,3),Type='audio' if c['audio_only'] else 'text',Text='' if c['audio_only'] else c['text'],Asset_File=movie or sf,Animation='' if c['audio_only'] else ANIMS[a],SFX_File=sf,Layer='A2' if c['audio_only'] else 'V2',Notes=notes))
        gain_db=-12 if style in ['Premium','Lifestyle'] else -10
        if c['audio_only']: gain_db=-9
        # Keep a short cue under speech; fade truncated tails instead of hard-cutting.
        x=sounds[sound][:round(min(1.6,TOTAL-start)*RATE)].copy()
        tail=min(round(.04*RATE),len(x)); x[-tail:]*=np.linspace(1,0,tail)
        offset=round(start*RATE); mix[offset:offset+len(x)]+=x*10**(gain_db/20)
        cue_sheet.append(dict(ID=f'E{i+1:03}',Start=tc(start),File=sf,Gain_dB=gain_db,Duration=len(x)/RATE,Notes='Provisional; no source dialogue available for loudness/ducking decisions.'))
    assert abs(mix).max()<.99
    wavfile.write(out/'SFX_TIMELINE.wav',RATE,np.round(mix*32767).astype(np.int16))
    write_csv(out/'06_TIMELINE/timeline.csv',events); write_json(out/'06_TIMELINE/timeline.json',events)
    write_csv(out/'sfx_cue_sheet.csv',cue_sheet)
    for name in VISUALS:
        visual(name,.5).save(out/f'04_VISUAL_OVERLAYS/{name}.png')
        encode(out/f'04_VISUAL_OVERLAYS/{name}.mov',(visual(name,k/(FPS*2-1)) for k in range(FPS*2)))
    write_json(out/'04_VISUAL_OVERLAYS/placement.json',dict(status='UNPLACED: source frame unavailable',canvas=[W,H],assets=VISUALS,instructions='Reposition, crop and scale each transparent overlay on the actual target. No robot tracking or safe-area claim has been made.'))
    (out/'05_SUBTITLES/README.md').write_text('Chưa có SRT nguồn. Không tạo phụ đề lời thoại giả từ các câu callout. Cần MOV và SRT để rà soát dấu tiếng Việt, tên hãng, model, công nghệ và đồng bộ. INAX, Bosch, KAFF và mọi thông số chưa được xác minh.\n',encoding='utf-8')
    print(f'Phases 2–3: {len(events)} draft cues, 30 presets, actual cue movies and 11 visual overlays created',flush=True)
    # Full-duration layout/sound preview on a clearly marked synthetic background.
    bg=Image.new('RGBA',(W,H),(11,20,32,255)); d=ImageDraw.Draw(bg)
    for x in range(0,W,60): d.line((x,0,x,H),fill=(20,38,52,255))
    for y in range(0,H,60): d.line((0,y,W,y),fill=(20,38,52,255))
    d.text((35,30),'TẤN PHÁT • PREVIEW MINH HỌA',font=font(28),fill=(240,205,130,255))
    d.text((35,72),'CHƯA CÓ MOV/SRT • TIMELINE CHƯA XÁC MINH',font=font(20),fill=(240,210,160,255))
    d.text((35,485),'Bố cục 16:9 tạm • Cần kiểm tra lại trên video nguồn',font=font(22),fill=(190,210,225,255))
    def frames():
        idx=0
        for k in range(TOTAL*12):
            t=k/12
            while idx+1<len(cues) and cues[idx+1]['start']<=t: idx+=1
            im=bg.copy(); c=cues[idx]; event=events[idx]
            elapsed=t-c['start']; duration=event['Duration']
            if 0<=elapsed<duration and not c['audio_only']:
                style,a,_=choose(c)
                im=Image.alpha_composite(im,render_text(c['text'],style,a,elapsed/duration))
            dr=ImageDraw.Draw(im); dr.text((W-190,35),tc(t),font=font(22),fill=(255,255,255,255))
            if k%600==0: print(f'Full preview: {t:.0f}/{TOTAL}s',flush=True)
            yield im
    encode(out/'07_PREVIEW/TIMELINE_DRAFT_PREVIEW.mp4',frames(),fps=12,alpha=False,audio=out/'SFX_TIMELINE.wav')
    # Thirty-preset gallery for quickly auditioning all animation styles.
    def gallery():
        for i,name in enumerate(ANIMS):
            for k in range(24):
                im=bg.copy(); im=Image.alpha_composite(im,render_text('TẤN PHÁT • TRẢI NGHIỆM',list(COLORS)[i%4],i,k/23))
                ImageDraw.Draw(im).text((35,430),f'{i+1:02} / 30   {name}',font=font(25),fill=(255,255,255,255))
                yield im
    encode(out/'07_PREVIEW/ANIMATION_GALLERY.mp4',gallery(),fps=12,alpha=False)
    visual_gallery(out)
    # Contact sheet for visual review of real Vietnamese callouts.
    sheet=Image.new('RGB',(1280,math.ceil(len(events)/4)*180),(18,29,43))
    for i,e in enumerate(events):
        if e['Type']=='audio': continue
        tile=Image.open(out/f'02_TEXT_PNG/{i+1:03}.png').convert('RGBA').resize((320,180))
        sheet.paste(tile,((i%4)*320,(i//4)*180),tile)
    sheet.save(out/'07_PREVIEW/TEXT_CONTACT_SHEET.jpg',quality=90)
    for p in SOURCE.glob('*.py'): shutil.copy2(p,out/'08_SOURCE_CODE'/p.name)
    shutil.copy2(SOURCE/'premium_cues.json',out/'08_SOURCE_CODE/premium_cues.json')
    requirements=ROOT/'requirements.txt' if (ROOT/'requirements.txt').is_file() else SOURCE/'requirements.txt'
    shutil.copy2(requirements,out/'08_SOURCE_CODE/requirements.txt')
    shutil.copy2(FONT,out/'08_SOURCE_CODE/NotoSans-Bold.ttf')
    license_path=Path('/usr/share/doc/fonts-noto-core/copyright')
    if license_path.exists(): shutil.copy2(license_path,out/'08_SOURCE_CODE/FONT_LICENSE.txt')
    readme='''# TẤN PHÁT PREMIUM CAPCUT PACK — BẢN NHÁP TÀI NGUYÊN

40 SFX tổng hợp nhiều lớp; 48 kHz PCM 16-bit; 2 giây im lặng giữa 40 SFX trong SFX_PREVIEW.wav. SFX_TIMELINE.wav dài 314 giây, có thể đặt tại 00:00 trên một track âm thanh riêng. Gain cue đã giảm nhưng chưa thể cân với giọng nói vì thiếu MOV.

74 cue theo mốc người dùng cung cấp (73 text + 1 audio), chưa xác minh bằng MOV/SRT. Không có phụ đề lời thoại đã rà soát. Không có logo chính thức: chữ TẤN PHÁT chỉ là wordmark minh họa. Không xác minh tên model, thông số, thương hiệu hoặc tuyên bố quảng cáo.

30 preset là cấu hình JSON + MOV mẫu, không phải preset CapCut native. Mỗi câu callout có PNG RGBA và MOV alpha riêng. MOV dùng QuickTime Animation qtrle/argb, 960×540, 24 fps, alpha thực. Khả năng import qtrle phụ thuộc phiên bản CapCut; dùng PNG kèm keyframe JSON nếu không hỗ trợ. Không chuyển MP4 preview thành overlay vì MP4 không có alpha.

## Nhập CapCut
1. Giải nén ZIP vào máy tính. Import WAV, PNG và MOV cần dùng.
2. Đặt video nguồn trên track chính; SFX_TIMELINE.wav tại 00:00. Không import SFX_PREVIEW.wav như soundtrack.
3. Tham khảo 06_TIMELINE/timeline.csv để đặt từng MOV/PNG lên track overlay. CSV/JSON là cue sheet tham khảo, không tự tạo project CapCut.
4. Kiểm tra tỉ lệ nguồn, dời chữ tránh mặt/sản phẩm và đồng bộ lại từng cue. Canvas 16:9 chỉ là bố cục tạm, không khẳng định video nguồn 16:9.
5. Preview MP4 dùng nền đồ họa minh họa, không chứa video nguồn. Đây chưa phải bản dựng cuối.

## Tái tạo bằng mã nguồn
Từ repository: .venv/bin/python src/premium_pack.py --output outputs/TEN_THU_MUC_MOI
Từ 08_SOURCE_CODE: cài requirements.txt, đặt NotoSans-Bold.ttf vào đường dẫn --font hoặc dùng font mặc định hệ thống; chạy python premium_pack.py --output ../TEN_THU_MUC_MOI. FFmpeg và FFprobe phải có trong PATH.
Chương trình từ chối ghi đè thư mục output và ZIP đã có. Bộ WAV và ZIP trước đó được giữ nguyên.

Cần cung cấp hoàng hút bụi drama.mov và hoàng hút bụi drama(1).srt để hoàn thiện phụ đề, xác minh tuyên bố sản phẩm và dựng preview trên hình thật.
'''
    (out/'README.md').write_text(readme,encoding='utf-8')
    finish(out,original_hash)


def finish(out,original_hash):
    """Validate completed renders and package without re-rendering or overwriting."""
    zip_path=out.parent/('TAN_PHAT_PREMIUM_CAPCUT_PACK.zip' if out.name=='CAPCUT_PREMIUM_EDIT_PACK' else out.name+'.zip')
    assert original_hash=={p:sha(Path(p)) for p in original_hash}
    if any((out/n).exists() for n in ['VALIDATION_REPORT.json','FILE_MANIFEST.json']) or zip_path.exists():
        raise FileExistsError('Delivery files already exist; refusing to overwrite.')
    print('Validating generated media...',flush=True)
    report=validate(out)
    report['prior_wav_files_preserved']=len(original_hash)
    write_json(out/'VALIDATION_REPORT.json',report)
    files=[p for p in sorted(out.rglob('*')) if p.is_file()]
    write_json(out/'FILE_MANIFEST.json',[dict(file=str(p.relative_to(out)),bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    with zipfile.ZipFile(zip_path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file(): z.write(p,Path(out.name)/p.relative_to(out))
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        for p in out.rglob('*'):
            if p.is_file(): assert hashlib.sha256(z.read(str(Path(out.name)/p.relative_to(out)))).hexdigest()==sha(p)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    print(f'ZIP verified: {zip_path} ({zip_path.stat().st_size} bytes)',flush=True)


def validate(out):
    report=dict(wav=[],png_count=0,alpha_movies=0,mp4=[],status='technical checks passed; source-dependent review pending')
    for p in sorted(out.rglob('*')):
        if not p.is_file(): continue
        assert p.stat().st_size>0,p
        if p.suffix=='.wav':
            rate,x=wavfile.read(p); assert rate==RATE and x.dtype==np.int16 and len(x)>0
            assert 0<abs(x.astype(np.int32)).max()<32767
            assert x[0]==0 and x[-1]==0
            subprocess.run(['ffmpeg','-v','error','-i',str(p),'-f','null','-'],check=True)
            report['wav'].append(dict(file=str(p.relative_to(out)),seconds=len(x)/RATE,sample_rate=rate,peak=int(abs(x.astype(np.int32)).max()),decode='PASS'))
        elif p.suffix=='.png':
            with Image.open(p) as im:
                im.load(); assert im.mode=='RGBA'; lo,hi=im.getchannel('A').getextrema(); assert lo==0 and hi>0
            report['png_count']+=1
        elif p.suffix in ['.mov','.mp4']:
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
            video=next(s for s in data['streams'] if s['codec_type']=='video')
            assert float(data['format']['duration'])>0
            subprocess.run(['ffmpeg','-v','error','-i',str(p),'-f','null','-'],check=True)
            if p.suffix=='.mov':
                assert video['pix_fmt']=='argb'
                sample_time=min(.5,float(data['format']['duration'])/2)
                raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(sample_time),'-i',str(p),'-frames:v','1','-f','rawvideo','-pix_fmt','rgba','pipe:1'])
                alpha=np.frombuffer(raw,dtype='uint8')[3::4]
                assert alpha.size and alpha.min()==0 and alpha.max()>0, str(p)
                report['alpha_movies']+=1
            else: report['mp4'].append(dict(file=str(p.relative_to(out)),seconds=float(data['format']['duration']),decode='PASS'))
    events=json.loads((out/'06_TIMELINE/timeline.json').read_text()); last=-1
    for e in events:
        def seconds(t):
            h,m,s=t.split(':'); return int(h)*3600+int(m)*60+float(s)
        start,end=seconds(e['Start']),seconds(e['End'])
        assert last<=start<end<=TOTAL; assert abs(end-start-e['Duration'])<.002; last=start
        assert (out/e['Asset_File']).is_file() and (out/e['SFX_File']).is_file()
        assert unicodedata.is_normalized('NFC',e['Text'])
    # Confirm all 39 audition gaps are exactly two seconds of zero samples.
    rows=list(csv.DictReader((out/'01_SFX_WAV/sfx_inventory.csv').open(encoding='utf-8-sig')))
    _,preview=wavfile.read(out/'SFX_PREVIEW.wav'); cursor=0
    for i,row in enumerate(rows):
        if i: assert not preview[cursor:cursor+2*RATE].any(); cursor+=2*RATE
        _,a=wavfile.read(out/row['File']); assert np.array_equal(preview[cursor:cursor+len(a)],a); cursor+=len(a)
    assert cursor==len(preview)
    report.update(cues=len(events),text_cues=sum(e['Type']=='text' for e in events),presets=30,visual_overlays=11,preview_gaps_verified=39,source_video_available=False,source_srt_available=False,reviewed_subtitles=False)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--font',type=Path,default=FONT)
    parser.add_argument('--finalize-existing',action='store_true',help='Validate completed renders and create missing delivery files without re-rendering')
    args=parser.parse_args(); FONT=args.font
    if not FONT.is_file(): raise FileNotFoundError('Provide a Vietnamese-capable font using --font')
    if args.finalize_existing:
        prior=ROOT/'outputs/SFX_VALIDATION.json'
        rows=json.loads(prior.read_text())['files'] if prior.is_file() else []
        originals={str(ROOT/'outputs'/row['file']):row['sha256'] for row in rows}
        finish(args.output.resolve(),originals)
    else:
        build(args.output.resolve())
