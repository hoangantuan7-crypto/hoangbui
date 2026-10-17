"""Render the existing editing pack over a source clip without manual placement.

Uses the source display aspect ratio (including anamorphic SAR), original audio,
auto-ducked SFX and existing cue/motion definitions. Never overwrites output.
"""
import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from premium_pack import render_text, choose, visual, font

SOURCE=Path(__file__).resolve().parent
ROOT=SOURCE.parent


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))


def ratio(value):
    a,b=value.replace(':','/').split('/'); return float(a)/float(b)


def cue_end(cues,i,total):
    start=cues[i]['start']
    # Audio-only piano must not prematurely cut the punchline text at 23.7s.
    following=next((c['start'] for c in cues[i+1:] if not c['audio_only']),total)
    return min(start+2.4,following-.08 if following<total else total,total)


def overlay_for(cue,elapsed,duration,width,height):
    style,anim,_=choose(cue)
    tile=render_text(cue['text'],style,anim,elapsed/duration)
    tile=tile.crop((0,100,960,440))
    tw=round(width*.96); th=round(tw*tile.height/tile.width)
    tile=tile.resize((tw,th),Image.Resampling.LANCZOS)
    frame=Image.new('RGBA',(width,height))
    # Header band leaves the baked-in subtitles and lower robot demonstration visible.
    frame.alpha_composite(tile,((width-tw)//2,round(height*.025)))
    # Sparse decorative tech accents only; these are not sensor/robot tracking.
    if 'scan' in cue['direction'].lower() and duration>1:
        art=visual('hud_frame',elapsed/duration).resize((round(width*.30),round(width*.17)))
        frame.alpha_composite(art,(round(width*.65),round(height*.22)))
    if cue['start']>=310:
        art=visual('end_card_accent',elapsed/duration).resize((width,round(width*540/960)))
        frame.alpha_composite(art,(0,round(height*.02)))
    return frame


def render(source,out,pack,width=540):
    if out.exists(): raise FileExistsError(out)
    data=probe(source)
    stream=next(s for s in data['streams'] if s['codec_type']=='video')
    duration=float(stream.get('duration',data['format']['duration']))
    sar=ratio(stream.get('sample_aspect_ratio','1:1'))
    dar=stream['width']*sar/stream['height']
    height=round(width/dar/2)*2
    fps=ratio(stream['avg_frame_rate'])
    if not (23<=fps<=61): raise ValueError('Unexpected frame rate; review source')
    if height>4096 or width<270: raise ValueError('Unexpected output dimensions')
    if not any(s['codec_type']=='audio' for s in data['streams']): raise ValueError('Source audio required')
    cue_file=SOURCE/'premium_cues.json'
    if not cue_file.is_file(): cue_file=pack/'08_SOURCE_CODE/premium_cues.json'
    cues=json.loads(cue_file.read_text())
    sfx=pack/'SFX_TIMELINE.wav'
    assert sfx.is_file()
    out.mkdir(parents=True)
    # Record original data and decisions rather than guessing product names/specifications.
    (out/'SOURCE_METADATA.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    schedule=[]
    for i,c in enumerate(cues):
        schedule.append(dict(ID=f'E{i+1:03}',Start=c['start'],End=round(cue_end(cues,i,duration),3),Text=c['text'],Type='audio' if c['audio_only'] else 'text',Position='upper band; existing subtitles preserved',Status='brief/SRT-based; not word-level forced alignment'))
    with (out/'APPLIED_CUES.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(schedule[0]));w.writeheader();w.writerows(schedule)
    print(f'Source display {dar:.6f}; output {width}x{height} {fps:g}fps; {duration:.3f}s',flush=True)
    video=out/'HOANG_TAN_PHAT_AUTO_EDIT.mp4'
    dec=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-threads','2','-i',str(source),'-an','-vf',f'scale={width}:{height},setsar=1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=(out/'decode.log').open('wb'))
    # Normalize original dialogue, then use its envelope to duck the effect track.
    filters='[1:a]aresample=48000,loudnorm=I=-16:TP=-2:LRA=11,asplit=2[voice][control];[2:a]aresample=48000,apad,volume=0.6[fx];[fx][control]sidechaincompress=threshold=0.035:ratio=6:attack=5:release=180[ducked];[voice][ducked]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false,aresample=48000[mix]'
    cmd=['ffmpeg','-nostdin','-v','error','-n','-threads','2','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-i',str(source),'-i',str(sfx),'-filter_complex',filters,'-map','0:v','-map','[mix]','-c:v','libx264','-preset','veryfast','-crf','21','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-ar','48000','-t',str(duration),'-movflags','+faststart',str(video)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    index=0; count=0; last_key=None; cached=None
    try:
        while True:
            raw=dec.stdout.read(width*height*3)
            if not raw: break
            if len(raw)!=width*height*3: raise RuntimeError('Incomplete decoded video frame')
            t=count/fps
            while index+1<len(cues) and cues[index+1]['start']<=t: index+=1
            c=cues[index]; end=schedule[index]['End']
            im=Image.frombytes('RGB',(width,height),raw)
            if c['audio_only']:
                # Piano is audio-only; allow the previous punchline to remain on screen.
                chosen=index-1
            else: chosen=index
            cc=cues[chosen]; end=schedule[chosen]['End']; elapsed=t-cc['start']
            if 0<=elapsed<end-cc['start'] and not cc['audio_only']:
                tile=overlay_for(cc,elapsed,end-cc['start'],width,height)
                im=Image.alpha_composite(im.convert('RGBA'),tile).convert('RGB')
            enc.stdin.write(im.tobytes());count+=1
            if count%round(fps*30)==0: print(f'Render {count/fps:.0f}/{duration:.0f}s',flush=True)
        dec.stdout.close(); enc.stdin.close()
        if dec.wait()!=0: raise RuntimeError('Source decoding failed; see decode.log')
        if enc.wait()!=0: raise RuntimeError('Encoding failed; see encode.log')
    except BaseException:
        for p in [dec,enc]:
            if p.poll() is None: p.kill();p.wait()
        raise
    validate_result(source,out,width,height,fps,dar,duration,count)


def validate_result(source,out,width=None,height=None,fps=None,dar=None,duration=None,count=None):
    video=out/'HOANG_TAN_PHAT_AUTO_EDIT.mp4'
    original=probe(source)
    source_video=next(s for s in original['streams'] if s['codec_type']=='video')
    if duration is None: duration=float(source_video.get('duration',original['format']['duration']))
    if dar is None: dar=source_video['width']*ratio(source_video.get('sample_aspect_ratio','1:1'))/source_video['height']
    if fps is None: fps=ratio(source_video['avg_frame_rate'])
    if count is None: count=int(source_video['nb_frames'])
    result=probe(video)
    v=next(s for s in result['streams'] if s['codec_type']=='video')
    a=next(s for s in result['streams'] if s['codec_type']=='audio')
    if width is None: width=v['width']
    if height is None: height=round(width/dar/2)*2
    assert v['width']==width and v['height']==height and v.get('sample_aspect_ratio','1:1')=='1:1'
    assert abs(float(v['duration'])-duration)<.1
    assert int(v['nb_frames'])==count
    assert a['sample_rate']=='48000'
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
    report=dict(source_seconds=duration,output_seconds=float(v['duration']),frames=count,output_dimensions=[width,height],fps=fps,source_display_aspect=dar,original_audio_included=True,sfx_ducked=True,existing_subtitles_preserved=True,new_subtitles_burned=False,product_claims_verified=False,word_level_alignment_verified=False,technical_decode='PASS',note='Rendered from compressed proxy; do not describe as full-resolution master. Inspect final framing and mix before publishing.')
    (out/'RENDER_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    print(video,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pack',type=Path,default=ROOT/'outputs/CAPCUT_PREMIUM_EDIT_PACK')
    p.add_argument('--width',type=int,default=540)
    p.add_argument('--validate-existing',action='store_true',help='Validate an existing rendered MP4 without re-encoding')
    a=p.parse_args()
    if a.validate_existing: validate_result(a.source.resolve(),a.output.resolve())
    else: render(a.source.resolve(),a.output.resolve(),a.pack.resolve(),a.width)
