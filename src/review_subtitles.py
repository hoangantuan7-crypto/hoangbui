"""Conservative text-only SRT review; no speech or product verification claimed."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import textwrap
import unicodedata
import zipfile
from pathlib import Path

from scipy.io import wavfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def seconds(value):
    h,m,s=value.replace(',','.').split(':')
    return int(h)*3600+int(m)*60+float(s)


def review(source,output):
    if output.exists(): raise FileExistsError(output)
    archive=output.with_suffix('.zip')
    if archive.exists(): raise FileExistsError(archive)
    raw=source.read_bytes()
    text=unicodedata.normalize('NFC',raw.decode('utf-8-sig')).replace('\r\n','\n')
    pattern=r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\s*\n|\Z)'
    matches=list(re.finditer(pattern,text,re.S))
    if not matches: raise ValueError('No valid SRT cues')
    rows=[]; issues=[]; changes=[]; subtitles=[]; last=0
    fixes=[(r'\btấn phát\b','Tấn Phát'),(r'\bem hoàng\b','em Hoàng'),
           (r'\bthông Minh\b','thông minh'),(r'\bmáy rửa 8\b','máy rửa bát'),
           (r'\blau rẻ\b','lau giẻ'),(r'\bbấm một nút bấm\b','bấm một nút'),
           (r'\bsạch sạch sẽ\b','sạch sẽ'),(r'\b200m²\b','200 m²')]
    suspicious=[('inox','Tên thương hiệu/ngữ cảnh: có thể là INAX; chưa tự sửa.'),
                ('standa','Tên thương hiệu có thể là American Standard; chưa xác minh.'),
                ('boss','Có thể là Bosch; chưa tự sửa.'),('cáp','Có thể là KAFF; chưa tự sửa.'),
                ('grand x','Xác minh chính tả thương hiệu.'),('roblox','Xác minh tên hãng robot; không tự đổi thành Roborock.'),
                ('quevo','Xác minh chính xác tên model trên sản phẩm.'),('ecovac','Xác minh tên hãng và cách viết.'),
                ('25.000','Thông số lực hút và đơn vị cần kiểm chứng; không tự khẳng định.'),
                ('phát can','Đơn vị nhận dạng lỗi; cần nghe lại, không tự thay bằng Pa.'),
                ('độc nhất','Tuyên bố phân phối độc quyền cần bằng chứng; không dùng làm callout quảng cáo.'),
                ('hiện châu','Tên địa phương chưa xác minh.'),
                ('tốt hơn','So sánh hiệu năng: lời nhận xét của người nói, chưa được chứng minh.'),
                ('hơn cả','So sánh hiệu năng: không chuyển thành tuyên bố quảng cáo.'),
                ('không có được','So sánh với robot khác cần kiểm chứng.'),
                ('200m','Diện tích showroom cần xác minh nếu dùng làm thông điệp quảng cáo.')]
    for expected,m in enumerate(matches,1):
        ident=int(m[1]); start,end=seconds(m[2]),seconds(m[3]); original=' '.join(m[4].split())
        assert ident==expected and last<=start<end
        last=end; clean=original
        for pattern,replacement in fixes: clean=re.sub(pattern,replacement,clean,flags=re.I)
        clean=re.sub(r'\b(Cho|Ra|Tay|Chi|Leo|Xu|Theo|VA)\b',lambda v:v[0].lower(),clean)
        if clean!=original: changes.append(dict(ID=ident,Start=m[2],Original=original,Revised=clean,Scope='Text/context correction only; audio not verified'))
        duration=end-start; cps=len(clean)/duration
        notes=[note for token,note in suspicious if token in original.casefold()]
        if duration<.7: notes.append('Đoạn ngắn dưới 0,7 giây; cần nghe lại trước khi gộp hoặc đổi timing.')
        if cps>22: notes.append(f'Tốc độ đọc {cps:.1f} ký tự/giây; cân nhắc rút gọn sau khi nghe.')
        for note in notes: issues.append(dict(ID=ident,Start=m[2],End=m[3],Source_Text=original,Issue=note,Status='PENDING_AUDIO_OR_PRODUCT_CHECK'))
        wrapped='\n'.join(textwrap.wrap(clean,width=42,break_long_words=False,break_on_hyphens=False))
        if wrapped.count('\n')>1: issues.append(dict(ID=ident,Start=m[2],End=m[3],Source_Text=original,Issue='Hơn 2 dòng ở độ rộng tham chiếu 42 ký tự; cần chia khi có âm thanh.',Status='PENDING_AUDIO_OR_PRODUCT_CHECK'))
        subtitles.append(f'{ident}\n{m[2]} --> {m[3]}\n{wrapped}\n')
        rows.append(dict(id=ident,start=start,end=end,text=clean))
    output.mkdir(parents=True)
    (output/'SOURCE_ORIGINAL.srt').write_bytes(raw)
    (output/'HOANG_DRAMA_TEXT_REVIEW_DRAFT.srt').write_text('\n'.join(subtitles),encoding='utf-8')
    def csvwrite(name,data):
        with (output/name).open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    csvwrite('SUBTITLE_CHANGES.csv',changes)
    csvwrite('SUBTITLE_REVIEW_ISSUES.csv',issues)
    cues=json.loads((ROOT/'src/premium_cues.json').read_text())
    alignment=[]
    for i,c in enumerate(cues,1):
        active=[r for r in rows if r['start']<=c['start']<r['end']]
        nearest=min(rows,key=lambda r:abs(r['start']-c['start']))
        alignment.append(dict(ID=f'E{i:03}',Start=c['start'],Callout=c['text'],SRT_IDs=';'.join(str(r['id']) for r in active),SRT_Text=' | '.join(r['text'] for r in active),Nearest_SRT_ID=nearest['id'],Delta_From_Nearest_Start=round(c['start']-nearest['start'],3),Status='TIMESTAMP_MATCH_ONLY_NOT_SEMANTIC_OR_AUDIO_VERIFICATION',Notes='Existing callout uses user brief; compare with speech before final placement.'))
    csvwrite('TIMELINE_SRT_ALIGNMENT.csv',alignment)
    # Extend only with silence to the exact end in the uploaded SRT; keep old WAV intact.
    soundtrack=ROOT/'outputs/CAPCUT_PREMIUM_EDIT_PACK/SFX_TIMELINE.wav'
    if soundtrack.is_file():
        rate,a=wavfile.read(soundtrack); frames=round(last*rate)
        assert rate==48000 and a.dtype==np.int16 and frames>=len(a)
        padded=np.pad(a,(0,frames-len(a)))
        target=output/'SFX_TIMELINE_SRT_LENGTH.wav'; wavfile.write(target,rate,padded)
        rate,b=wavfile.read(target); assert np.array_equal(b[:len(a)],a) and not b[len(a):].any()
    report=dict(source_sha256=hashlib.sha256(raw).hexdigest(),subtitle_count=len(rows),end_seconds=last,
                timing_order_valid=True,timings_preserved=True,text_changes=len(changes),review_items=len(issues),
                callout_count=len(alignment),callouts_inside_subtitle=sum(bool(x['SRT_IDs']) for x in alignment),
                video_transfer='BLOCKED: attachment exceeds 32 MiB tool transfer limit',
                audio_verified=False,product_claims_verified=False,final_subtitles=False)
    (output/'REVIEW_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'README.md').write_text('''# Rà soát SRT — bản nháp chỉ đối chiếu văn bản

SRT nguồn có 111 đoạn, kết thúc 05:14.166. SOURCE_ORIGINAL.srt giữ nguyên từng byte. HOANG_DRAMA_TEXT_REVIEW_DRAFT.srt giữ nguyên timestamp, chuẩn hóa Unicode, sửa chữ hoa và lỗi rõ theo ngữ cảnh (máy rửa 8 → máy rửa bát; lau rẻ → lau giẻ). Chưa nghe âm thanh nên chưa phải phụ đề cuối.

Không tự sửa inox/INAX, boss/Bosch, cáp/KAFF, Roblox, quevo Pro 2, ecovac hoặc đơn vị lực hút. Xem SUBTITLE_REVIEW_ISSUES.csv để kiểm chứng tên hãng, model, địa phương, con số, tuyên bố độc quyền và so sánh hiệu năng. Những từ chưa xác minh còn nguyên trong SRT nháp; không dùng làm phụ đề xuất bản trước khi duyệt.

TIMELINE_SRT_ALIGNMENT.csv đối chiếu 74 cue với timestamp SRT, không chứng minh callout khớp ý hay khớp âm thanh. SFX_TIMELINE_SRT_LENGTH.wav nối im lặng vào bản 314 giây để có độ dài 314,166 giây theo SRT; không tuyên bố video có cùng độ dài.

MOV tải lên vượt giới hạn chuyển 32 MiB của công cụ; chưa đọc hình/âm thanh, chưa xác minh tỷ lệ hay vùng an toàn. Cần MP4 proxy dưới 32 MiB, giữ nguyên toàn bộ thời lượng, điểm bắt đầu và âm thanh. Không tăng tốc hoặc cắt đoạn. Ví dụ FFmpeg trên máy có video:

ffmpeg -i "hoàng hút bụi drama.mov" -vf "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2" -c:v libx264 -preset medium -b:v 450k -maxrate 500k -bufsize 1000k -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart "hoang_drama_proxy.mp4"

Với thời lượng khoảng 314 giây, bitrate này thường cho tệp khoảng 21 MB. Kiểm tra dung lượng thực tế trước khi tải lên. Giữ MOV gốc trên máy để xuất cuối ở chất lượng gốc.
''',encoding='utf-8')
    shutil.copy2(__file__,output/'review_subtitles.py')
    assert source.read_bytes()==raw
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.iterdir()): z.write(p,p.name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for p in output.iterdir(): assert z.read(p.name)==p.read_bytes()
    print(json.dumps(report,ensure_ascii=False,indent=2));print(archive)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();review(a.source,a.output)
