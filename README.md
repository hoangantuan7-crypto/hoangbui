# CapCut resource generator

Generate five original synthesized SFX without requiring MOV, SRT or downloaded audio. Piano and record scratch sounds are synthetic approximations.

## Setup

```sh
cd /workspace/hoangbui
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
ffmpeg -version
```

## Generate and validate

```sh
.venv/bin/python src/generate_sfx.py --output outputs/sfx
.venv/bin/python -m unittest discover -s tests -v
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bits_per_sample -of json outputs/sfx/dramatic_hit.wav
```

Output: mono PCM signed 16-bit WAV at 48 kHz plus `manifest.json`. Import the WAV files into CapCut's audio/media panel. Choose a different output directory for another run: existing assets are never overwritten. Generated media and the local virtual environment are ignored by Git.

Video editing will require the user to supply the source video and, if captions are needed, its SRT. No video is assumed to exist.

## Expanded pack and preview

After generating the original five files, run once:

```sh
.venv/bin/python src/build_pack.py
```

This preserves the original files and creates 35 additional synthesized SFX in
`outputs/sfx_extra/`, `outputs/SFX_PREVIEW.wav` (the original five in their listed
order with exactly two seconds of silence between them), an inventory CSV,
a validation JSON with SHA-256 hashes, and `outputs/CAPCUT_SFX_40.zip`.
The script refuses to replace existing pack outputs. Every WAV is checked with
SciPy, Python wave, FFprobe and FFmpeg decoding. ZIP members are checked against
the WAV hashes. `whoosh_pan` is stereo; the other files are mono.

To use on your computer, download the ZIP using the file download action if your
Codex interface provides one, extract it, and open `SFX_PREVIEW.wav` with VLC or
another audio player. Import the individual WAV files into CapCut using its
media import action, then drag them onto the audio timeline. The preview is for
auditioning the original five sounds; the individual WAVs are the editing assets.
Local workspace paths are not public download URLs. Generated assets are ignored
by Git, so downloading a source-only repository does not include them.
