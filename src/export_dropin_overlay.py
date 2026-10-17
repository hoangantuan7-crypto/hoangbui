"""One transparent timeline clip: original-media-free text/graphics plus SFX."""
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from render_source_edit import overlay_for, cue_end, probe

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/DROP_IN_OVERLAY_V1'
FPS=24; W=540; H=960; FRAMES=7552


def main():
    if OUT.exists(): raise FileExistsError(OUT)
    OUT.mkdir(parents=True)
    cues=json.loads((ROOT/'src/premium_cues.json').read_text())
    duration=FRAMES/FPS
    path=OUT/'KEO_LEN_TREN_VIDEO_TAI_00_00.mov'
    sfx=ROOT/'outputs/CAPCUT_PREMIUM_EDIT_PACK/SFX_TIMELINE.wav'
    cmd=['ffmpeg','-nostdin','-v','error','-n','-f','rawvideo','-pix_fmt','rgba','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-i',str(sfx),'-map','0:v','-map','1:a','-vf','setsar=1','-c:v','prores_ks','-profile:v','4','-qscale:v','24','-pix_fmt','yuva444p10le','-alpha_bits','8','-threads','2','-af',f'volume=0.45,apad,atrim=duration={duration}','-c:a','pcm_s16le','-ar','48000','-t',str(duration),str(path)]
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(OUT/'encode.log').open('wb'))
    index=0; blank=Image.new('RGBA',(W,H)).tobytes()
    try:
        for k in range(FRAMES):
            t=k/FPS
            while index+1<len(cues) and cues[index+1]['start']<=t: index+=1
            chosen=index-1 if cues[index]['audio_only'] else index
            c=cues[chosen]; end=cue_end(cues,chosen,duration)
            if c['start']<=t<end and not c['audio_only']:
                raw=overlay_for(c,t-c['start'],end-c['start'],W,H).tobytes()
            else: raw=blank
            p.stdin.write(raw)
            if k and k%(FPS*45)==0: print(f'Render {k/FPS:.0f}/{duration:.0f}s',flush=True)
        p.stdin.close()
        if p.wait()!=0: raise RuntimeError((OUT/'encode.log').read_text())
    except BaseException:
        if p.poll() is None: p.kill();p.wait()
        raise
    finish(path)


def finish(path):
    duration=FRAMES/FPS
    data=probe(path);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio')
    assert v['codec_name']=='prores' and v['profile']=='4444'
    assert v['pix_fmt'].startswith('yuva') and int(v['nb_frames'])==FRAMES
    assert a['sample_rate']=='48000'
    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True)
    for time,empty in [(1,True),(23.95,False),(136.6,False)]:
        raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-pix_fmt','rgba','-f','rawvideo','pipe:1'])
        im=np.frombuffer(raw,np.uint8).reshape(H,W,4)
        if empty: assert not im[:,:,3].any()
        else: assert im[:,:,3].min()==0 and im[:,:,3].max()>0
    report=dict(codec=v['codec_name'],profile=v['profile'],pixel_format=v['pix_fmt'],alpha_test='PASS: empty regions and visible text',decode='PASS',duration=duration,frames=FRAMES,fps=FPS,dimensions=[W,H],audio='48 kHz PCM16 SFX only; no source speech',source_footage_included=False,native_capcut_tested=False)
    (OUT/'CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'HUONG_DAN.txt').write_text('''CHỈ CẦN KÉO MỘT CLIP\n\n1. Giải nén ZIP.\n2. Trong dự án CapCut đang có video gốc, Import KEO_LEN_TREN_VIDEO_TAI_00_00.mov.\n3. Kéo MOV lên track PHÍA TRÊN video gốc, căn mép trái tại 00:00. Không thay video gốc.\n4. Nếu clip không phủ vừa khung, chọn Fit/Vừa khung hoặc chỉnh Scale cho phủ đúng khung 9:16.\n5. Giữ âm thanh video gốc; MOV mới chỉ có SFX. Không thêm lại SFX_TIMELINE hoặc các CUE từ pack cũ để tránh trùng. Nếu đã thêm trước đó, tắt các track hiệu ứng cũ khi thử clip này.\n6. Xem đoạn 00:20–00:30 để kiểm tra đồng bộ. Cần giữ timeline video gốc nguyên thời gian như proxy, chưa cắt/ripple hoặc đổi tốc độ. Nếu đã cắt video, clip tổng sẽ không tự biết các điểm cắt.\n\nĐịnh dạng ProRes 4444 có alpha thật, 540×960, 24 fps, dài 5:14.667. Không chứa hình hoặc giọng nói của video nguồn. Chữ, HUD và SFX đã gộp theo timeline. Không có project native nhiều lớp; chỉ chỉnh vị trí/âm lượng/độ dài của clip tổng.\n\nChưa kiểm thử trực tiếp trên phiên bản CapCut của anh. Nếu nền xuất hiện đen và che video, không dùng Chroma Key vì sẽ làm mất viền chữ. Gửi ảnh timeline/preview và phiên bản CapCut để kiểm tra hỗ trợ alpha. Đặt clip lên track trên video trước khi kết luận nền đen: xem riêng clip trên nền preview đen không chứng minh alpha bị mất.\n''',encoding='utf-8')
    (OUT/'export_dropin_overlay.py').write_bytes(Path(__file__).read_bytes())
    archive=ROOT/'outputs/TAN_PHAT_KEO_THA_MOT_CLIP.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(path,'KEO_LEN_TREN_VIDEO_TAI_00_00.mov')
        for f in sorted(OUT.iterdir()):
            if f.is_file() and f.stat().st_size and f.suffix not in ['.log','.mov']: z.write(f,f.name)
    with zipfile.ZipFile(archive) as z: assert z.testzip() is None
    print(json.dumps(report),flush=True)
    print('MOV bytes:',path.stat().st_size,'ZIP bytes:',archive.stat().st_size,flush=True)


if __name__=='__main__':
    if '--finalize-compact' in sys.argv: finish(OUT/'KEO_THA_GON.mov')
    elif '--finalize' in sys.argv: finish(OUT/'KEO_LEN_TREN_VIDEO_TAI_00_00.mov')
    else: main()
