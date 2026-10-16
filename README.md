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

## Tan Phat premium editing pack

```sh
.venv/bin/python src/premium_pack.py --output outputs/CAPCUT_PREMIUM_EDIT_PACK
```

This separate pack implements the revised 40-sound brief, all 74 user-supplied
cue timestamps, four typography styles, 30 motion presets, actual animated cue
text and 11 transparent visual overlays. It includes complete-audition and
314-second timeline WAVs, CSV/JSON cue sheets, alpha MOVs, RGBA PNGs, two MP4
previews, source code, technical validation and a ZIP archive. It never overwrites
previous packs. To regenerate, select a new output name (and therefore a new ZIP
name). A Vietnamese-capable font can be selected with `--font /path/to/font.ttf`.

The timeline is provisional. The source MOV and SRT have not been supplied, so
the generated previews use a labeled graphic background. No reviewed dialogue
SRT or final source-video edit is claimed. Recheck product names, claims,
timing, source aspect ratio and face/product occlusion after upload. The JSON
presets and CSV do not automatically create a native CapCut project; use the
rendered assets and cue times. CapCut codec support must be checked in the user's
version; PNG and keyframe metadata remain available if qtrle MOV import fails.
