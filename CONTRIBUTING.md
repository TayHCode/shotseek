# Contributing

Use Python 3.11 or newer. For development without heavy model dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install numpy Pillow pillow-heif opencv-python-headless
pip install --no-deps -e .
mkdir -p .scratch/tmp
export TMPDIR="$PWD/.scratch/tmp"
python -m unittest discover -s tests -t . -q
```

Use standard unittest and run one test process at a time. Tests generate their
own media, never use real media or real paths, and must not access the network.
Only neutral cafe, hiking club, and product shoot examples belong in the repo.
Keep generated media, output, packages, and models in ignored scratch folders.

Run the configured syntax and import checks after the tests:

```sh
python -m pip install ruff
python -m ruff check .
```

For tests only, `SHOTSEEK_EMBEDDER=fake` selects deterministic colour vectors.
`SHOTSEEK_TRANSCRIBER=fake:/path/outside/library/segments.json` reads invented
segments. Neither fake represents real model quality. The default suite blocks
socket connections and does not import or download heavy model libraries.
`SHOTSEEK_DENYLIST` optionally names an external literal-term list; diagnostics
report counts and locations without exposing terms or matching text.

The three slow modules are opt-in. Install CPU PyTorch from its wheel index, then
the project dependencies. Cache the default image/text weights and the base speech
model under `.scratch/hf` before running; ffmpeg must include the flite speech source:

```sh
HF_HOME="$PWD/.scratch/hf" python -c "from shotseek.embed.openclip import OpenClipEmbedder; from shotseek.transcribe.whisper import WhisperTranscriber; OpenClipEmbedder({}, 'cpu'); WhisperTranscriber('base', 'cpu')"
```

Then run the tests with those cached weights:

```sh
HF_HOME="$PWD/.scratch/hf" SHOTSEEK_RUN_SLOW=1 python -m unittest tests.test_slow_real_models tests.test_slow_scale tests.test_slow_reference_embedding -v
```

Slow tests keep network access blocked and load the cached models offline. They use
only generated inputs and a synthetic 400,000-vector scale fixture. Measurements
include local base transcription, image/text search, and the frame pre-fit comparison.

Characterization tests pin existing behaviour; change one only together with
the behaviour and say why in the commit message. The default suite works with
or without TMPDIR. Multiple external term paths can be joined by the operating
system path separator; `SHOTSEEK_DENYLIST_HISTORY=1` includes historical blobs.
