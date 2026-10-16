"""Build an additive SFX pack, preview, inventory and downloadable ZIP."""
import csv
import hashlib
import io
import json
import subprocess
import wave
import zipfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile
from generate_sfx import RATE, piano, timeline

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    'whoosh_short', 'whoosh_long', 'whoosh_reverse', 'whoosh_pan',
    'impact_sub', 'impact_metal', 'impact_cinematic', 'impact_soft',
    'riser_tension', 'riser_bright', 'downlifter', 'reverse_cymbal',
    'ui_click', 'ui_pop', 'ui_confirm', 'ui_error', 'notification',
    'message_sent', 'message_received', 'countdown', 'success_chime',
    'failure_buzz', 'glitch_short', 'glitch_stutter', 'digital_scan',
    'laser_zap', 'robot_blip', 'camera_shutter', 'typewriter',
    'swoosh_sparkle', 'magic_chime', 'comedy_boing', 'cartoon_drop',
    'heartbeat', 'clock_tick',
]


def extra_sounds():
    rng = np.random.default_rng(2026)
    for i, name in enumerate(NAMES):
        duration = 2.8 if name.startswith('riser') else (2.0 if name in ['whoosh_long', 'downlifter', 'reverse_cymbal', 'heartbeat', 'countdown'] else 1.2)
        t = timeline(duration)
        noise = signal.sosfilt(signal.butter(3, [250, 11000], fs=RATE, btype='bandpass', output='sos'), rng.normal(size=len(t)))
        if i < 4:
            x = noise * np.sin(np.pi*t/duration)**(2+i)
            if i == 2:
                x *= (t/duration)**2
            if i == 3:
                # Stereo movement from left to right.
                pan = t/duration*np.pi/2
                x = np.column_stack((x*np.cos(pan), x*np.sin(pan)))
        elif i < 8:
            x = signal.chirp(t, 65+110*(i-4), duration, 25+20*(i-4), method='logarithmic')*np.exp(-(3+i-4)*t)
            if i == 5:
                x += sum(np.sin(2*np.pi*f*t)*np.exp(-4*t)/4 for f in [731, 1193, 1877])
            x += noise*.3*np.exp(-22*t)
        elif i < 12:
            up = i in [8, 9, 11]
            env = (t/duration)**2 if up else (1-t/duration)**2
            x = noise*env*.6
            if i != 11:
                x += signal.chirp(t, 150 if up else 5000, duration, 6000 if up else 80, method='logarithmic')*env*.3
        elif i in [12, 13, 27, 28, 34]:
            x = np.zeros_like(t)
            starts = [0, .09] if i == 27 else ([0, .13, .29, .5] if i == 28 else [0])
            for start in starts:
                u = t-round(start*RATE)/RATE
                active = u >= 0
                v = np.maximum(u, 0)
                x += active*(noise*np.exp(-v*(65 if i != 27 else 30)) + .6*np.sin(2*np.pi*(1100 if i == 34 else 450)*v)*np.exp(-80*v))
        elif i in [14, 15, 16, 17, 18, 19, 20, 21, 26, 30]:
            notes = {14:[660,880],15:[330,220],16:[880,1174.66],17:[600,1000],18:[1000,700],19:[660,660,1320],20:[523.25,659.25,783.99,1046.5],21:[155,146.83],26:[1200,800,1600],30:[1046.5,1318.51,1567.98,2093]}[i]
            x = np.zeros_like(t)
            for j, f in enumerate(notes):
                start = round(j*(.5 if i == 19 else .13)*RATE)
                u = t[:len(t)-start]
                tone = piano(u, f) if i in [16,20,30] else np.sin(2*np.pi*f*u)*np.exp(-10*u)
                x[start:] += tone*np.minimum(u/.005,1)
        elif i in [22,23,24,25]:
            if i == 24:
                x = np.sin(2*np.pi*(350*t+1300*t*t))*(.5+.5*np.sin(2*np.pi*12*t))*np.exp(-t)
            elif i == 25:
                x = signal.chirp(t, 4500, duration, 80, method='logarithmic')*np.exp(-6*t)
            else:
                gate = (np.sin(2*np.pi*(23 if i == 22 else 9)*t) > .3)
                steps = rng.uniform(200,4500,24)[np.minimum((t/duration*24).astype(int),23)]
                x = (signal.square(2*np.pi*np.cumsum(steps)/RATE)*.5+noise*.25)*gate*np.exp(-3*t)
        elif i == 29:
            x = noise*np.sin(np.pi*t/duration)**3*.4
            x += piano(t,1567.98)*np.minimum(t/.05,1)*.4
        elif i == 31:
            freq = 180+160*np.exp(-4*t)*np.cos(2*np.pi*8*t)
            x = np.sin(2*np.pi*np.cumsum(freq)/RATE)*np.exp(-4*t)
        elif i == 32:
            x = signal.chirp(t, 1800, duration, 90, method='logarithmic')*np.exp(-2*t)
        elif i == 33:
            x = np.zeros_like(t)
            for offset in [0, .18, .85, 1.03]:
                u = np.maximum(t-offset,0)
                x += (t >= offset)*np.sin(2*np.pi*65*u)*np.exp(-25*u)
        yield name, x


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    output = ROOT/'outputs'
    originals = [output/'sfx'/f'{name}.wav' for name in ['dramatic_hit','record_scratch','sad_piano','happy_transition','digital_beep']]
    before = {p: digest(p) for p in originals}
    extra = output/'sfx_extra'
    preview = output/'SFX_PREVIEW.wav'
    inventory = output/'SFX_INVENTORY.csv'
    archive = output/'CAPCUT_SFX_40.zip'
    checks = output/'SFX_VALIDATION.json'
    targets = [extra/(n+'.wav') for n in NAMES]+[preview, inventory, archive, checks]
    if any(p.exists() for p in targets):
        raise FileExistsError('Pack output exists; preserve it before building a new pack.')
    extra.mkdir(parents=True, exist_ok=True)
    for name, x in extra_sounds():
        fade = round(.008*RATE)
        envelope = np.ones(len(x))
        envelope[:fade] = np.linspace(0,1,fade)
        envelope[-fade:] = np.linspace(1,0,fade)
        x *= envelope if x.ndim == 1 else envelope[:, None]
        x *= 10**(-1/20)/max(np.max(np.abs(x)),1e-12)
        wavfile.write(extra/(name+'.wav'), RATE, np.round(x*32767).astype(np.int16))
    pieces = []
    for i,p in enumerate(originals):
        rate,x = wavfile.read(p)
        assert rate == RATE and x.dtype == np.int16 and x.ndim == 1
        if i:
            pieces.append(np.zeros(2*RATE,dtype=np.int16))
        pieces.append(x)
    wavfile.write(preview,RATE,np.concatenate(pieces))
    all_sfx = originals+[extra/(n+'.wav') for n in NAMES]
    rows = []
    for p in all_sfx+[preview]:
        rate,x = wavfile.read(p)
        with wave.open(str(p)) as w:
            assert w.getsampwidth() == 2 and w.getcomptype() == 'NONE'
        assert rate == RATE and x.dtype == np.int16 and np.isfinite(x).all()
        peak = int(np.max(np.abs(x.astype(np.int32))))
        assert 0 < peak < 32767
        assert np.sqrt(np.mean(x.astype(float)**2)) > 100
        subprocess.run(['ffmpeg','-v','error','-i',str(p),'-f','null','-'],check=True)
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_name,sample_rate,channels,bits_per_sample','-of','json',str(p)]))['streams'][0]
        assert probe['codec_name'] == 'pcm_s16le' and probe['sample_rate'] == '48000' and probe['bits_per_sample'] == 16
        rows.append(dict(file=str(p.relative_to(output)), seconds=len(x)/rate, sample_rate=rate, channels=1 if x.ndim == 1 else x.shape[1], bits=16, peak=peak, sha256=digest(p), decode='PASS'))
    # Verify exact samples and the four 2-second silent gaps in the preview.
    _,combined = wavfile.read(preview)
    cursor = 0
    for i,p in enumerate(originals):
        if i:
            assert not combined[cursor:cursor+2*RATE].any()
            cursor += 2*RATE
        _,x = wavfile.read(p)
        assert np.array_equal(combined[cursor:cursor+len(x)],x)
        cursor += len(x)
    assert cursor == len(combined)
    assert before == {p:digest(p) for p in originals}
    with inventory.open('x',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    checks.write_text(json.dumps(dict(sfx_count=40, wav_count=41, originals_unchanged=True, preview_gaps_seconds=2, files=rows),indent=2)+'\n')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in all_sfx+[preview,inventory,checks]:
            z.write(p,p.relative_to(output))
        z.writestr('README.txt','40 synthesized SFX for CapCut; PCM 16-bit / 48000 Hz. whoosh_pan is stereo; other SFX are mono. SFX_PREVIEW.wav contains the original five sounds with 2-second silent gaps. See SFX_INVENTORY.csv for durations and SHA-256 hashes. Extract the ZIP and import WAVs through CapCut media import. Sounds are synthetic approximations, not field recordings.\n')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for p in all_sfx+[preview]:
            assert hashlib.sha256(z.read(str(p.relative_to(output)))).hexdigest() == digest(p)
    print(f'Validated {len(rows)} WAV files, 40 SFX, originals preserved; ZIP integrity OK')
    print(archive)


if __name__ == '__main__':
    build()
