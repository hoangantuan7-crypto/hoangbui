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
