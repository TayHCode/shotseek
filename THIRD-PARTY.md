# Third-party components

shotseek itself is MIT licensed (see [LICENSE](LICENSE)). It installs and uses
the components below. Licenses were read from the installed package metadata
(versions in the right-hand column of the first table were the ones tested) or
from the model card on the upstream model page. This is a summary, not legal
advice; each component's own license file is authoritative.

## Direct dependencies

| Package | License (from package metadata) | Version checked |
| --- | --- | --- |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 2.5.2 |
| Pillow | MIT-CMU | 12.3.0 |
| pillow-heif | BSD-3-Clause (bundles other libraries, see below) | 1.8.0 |
| opencv-python-headless | Apache 2.0 (bundles FFmpeg, see below) | 5.0.0 |
| torch | BSD-style and Apache-2.0 terms (metadata lists Apache-2.0, BSD-2/3-Clause, BSL-1.0, MIT, LLVM exception) | 2.14.1 (CPU) |
| torchvision | BSD | 0.29.1 (CPU) |
| open_clip_torch | MIT | 3.3.0 |
| faster-whisper | MIT | 1.2.1 |
| av (PyAV) | BSD-3-Clause (bundles FFmpeg libraries, see below) | 18.1.0 |

## Notable transitive dependencies

| Package | License | Why it matters |
| --- | --- | --- |
| ctranslate2 | MIT | Runs the speech model for faster-whisper |
| huggingface_hub | Apache-2.0 | Downloads and caches model weights |
| timm | Apache-2.0 | Used by open_clip_torch |
| onnxruntime | MIT | Installed by faster-whisper |

## Bundled native libraries inside the wheels

Binary wheels ship their own copies of native libraries. Where they are
reachable by `pip install` on Linux, the installed wheels contained:

- **opencv-python-headless** bundles FFmpeg, which its own
  `LICENSE-3RD-PARTY.txt` states is licensed under LGPLv2.1. It also ships
  libraries such as libaom, libavif, libvpx, libpng, OpenBLAS and OpenSSL 1.1.1.
- **pillow-heif** bundles libheif (LGPLv3), libde265 (LGPLv3) and x265, which its
  own `LICENSES_bundled.txt` lists as **GPLv2**. Anyone redistributing
  an environment or application that contains this wheel should review that.
- **av** (used by faster-whisper) bundles FFmpeg libraries; the
  bundled libavcodec reports "LGPL version 3 or later". The wheel also contains
  libx264 and libx265 files, which are GPL-licensed codecs.

shotseek does not redistribute any of these wheels; they are installed from
PyPI onto the user's own machine. Other platforms' wheels (macOS, Windows) may
bundle a different set of libraries. HEIC support is optional in practice: if
pillow-heif is unwanted, the rest still works and HEIC files are skipped.

## FFmpeg executables

`ffmpeg` and `ffprobe` are **not bundled**. The user installs them separately
(for example with a system package manager) and they run as external programs.
Their license depends on how the user's build was made (LGPL or GPL); see the
license of the build you install.

## Models and weights

Weights are downloaded once on first use from the Hugging Face Hub into the
local model cache. They are not part of this repository.

| Model | Where used | License | Source |
| --- | --- | --- | --- |
| OpenCLIP ViT-B-32, `laion2b_s34b_b79k` (`laion/CLIP-ViT-B-32-laion2B-s34b-b79k`) | Default image and text embedding | MIT, per the model card | [model card](https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34b-b79k) |
| Whisper `base` via faster-whisper (`Systran/faster-whisper-base`) | Default local speech transcription | MIT, per the model card | [model card](https://huggingface.co/Systran/faster-whisper-base) |
| Whisper `large-v3` via faster-whisper (`Systran/faster-whisper-large-v3`) | Optional larger speech model | MIT, per the model card | [model card](https://huggingface.co/Systran/faster-whisper-large-v3) |

Things to know about the OpenCLIP weights:

- They were trained on the English subset of LAION-5B (LAION-2B), a large
  uncurated collection of images and captions scraped from the public web. The
  model card notes the data may include disturbing content and that the dataset
  is intended for research.
- The model card says deployed use cases are out of scope without thorough
  task-specific testing, and that surveillance and facial recognition uses are
  always out of scope. shotseek never does face recognition or identifies people.
- Training on scraped web data may raise copyright questions that the MIT
  license on the weights does not resolve.
- Selecting a different model pair (for example `ViT-L-14` with
  `laion2b_s32b_b82k`, suggested in the README for GPUs) means that model's own
  license applies; check its card.

The Systran faster-whisper models are conversions of OpenAI's Whisper weights.
OpenAI publishes the original Whisper weights under MIT; the converted
repositories above also declare MIT on their cards.
