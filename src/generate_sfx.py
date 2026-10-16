"""Generate original synthesized editing sounds, without external media."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

RATE = 48000


def timeline(seconds):
    return np.arange(round(seconds * RATE)) / RATE


def piano(t, frequency):
    return sum(np.sin(2 * np.pi * frequency * k * t) * np.exp(-t * (1.5 + k * .45)) / k**2
               for k in range(1, 7))


def synthesize():
    rng = np.random.default_rng(42)
    t = timeline(2.5)
    hit = signal.chirp(t, 110, 2.5, 32, method='logarithmic') * np.exp(-3*t)
    hit += .5 * rng.normal(size=t.size) * np.exp(-18*t)
    t = timeline(1.1)
    scratch = signal.sawtooth(2*np.pi*(350*t + 70*np.sin(2*np.pi*5*t)))
    scratch = signal.sosfilt(signal.butter(3, [400, 6500], fs=RATE, btype='bandpass', output='sos'), scratch)
    scratch *= np.sin(np.pi*t/1.1)**2 * (.3+.7*np.sin(2*np.pi*5*t)**2)
    t = timeline(4)
    sad = sum(piano(t, f) for f in [220, 261.6256, 329.6276]) / 3
    delayed = np.zeros_like(sad)
    delay = round(.28*RATE)
    delayed[delay:] = sad[:-delay]*.25
    sad += delayed
    t = timeline(1.8)
    happy = np.zeros_like(t)
    for offset, f in zip([0, .16, .32, .48], [523.251, 659.255, 783.991, 1046.502]):
        start = round(offset*RATE)
        nt = t[:len(t)-start]
        happy[start:] += .5*piano(nt, f)*np.minimum(nt/.008, 1)
    t = timeline(.45)
    beep = np.sin(2*np.pi*880*t)*np.exp(-5*t)
    return dict(dramatic_hit=hit, record_scratch=scratch, sad_piano=sad,
                happy_transition=happy, digital_beep=beep)


def export(output):
    output.mkdir(parents=True, exist_ok=True)
    sounds = synthesize()
    targets = [output / (name+'.wav') for name in sounds]
    if any(p.exists() for p in targets) or (output/'manifest.json').exists():
        raise FileExistsError('Output exists; choose a new --output directory to preserve files.')
    records = []
    for (name, samples), path in zip(sounds.items(), targets):
        # Short fades avoid clicks; keep 1 dB of peak headroom.
        fade = min(round(.008*RATE), len(samples)//2)
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)
        samples *= 10**(-1/20) / max(np.max(np.abs(samples)), 1e-12)
        wavfile.write(path, RATE, np.round(samples*32767).astype(np.int16))
        records.append(dict(name=name, file=path.name, sample_rate=RATE,
                            channels=1, bits=16, seconds=len(samples)/RATE))
    (output/'manifest.json').write_text(json.dumps(records, indent=2)+'\n')
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('outputs/sfx'))
    args = parser.parse_args()
    for path in export(args.output):
        print(path.resolve())
