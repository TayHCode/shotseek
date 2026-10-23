# shotseek

shotseek is a small local tool for people with a lot of media: a job's asset
folder, a creator's camera roll, or a club's shared drive. Point it at a folder
of photos and videos. It builds a search index on your computer. Ask your own
Claude or Codex agent for pictures or video moments, or hand it a talking-head
video and get B-roll suggestions for each passage. It runs offline after a
one-time model download, uses no paid service, and never changes your media.

## What you can ask for

- "Find a landscape picture of latte art for the cafe website."
- "Find a portrait photo of our hiking club at a trailhead for a social post."
- "Find B-roll for this product shoot A-roll, especially hands unboxing and
  close-ups of the ceramic mug."

## Requirements

Python 3.11+ (3.12 was used for the platform checks), `ffmpeg` and `ffprobe`,
and space for packages, model weights, package caches, and your index. Linux,
Apple Silicon macOS, and native Windows have been tested with the qualifications
below. Additional models need more space. See [platform setup](docs/platforms.md)
for isolated Python installs, portable ffmpeg, and Windows setup. Native Windows
x64 also needs the Microsoft Visual C++ v14 Redistributable for the Python
packages that load native libraries. Installing it may require administrator
approval and a restart.

shotseek has been tested on a desktop with an NVIDIA RTX-class GPU. It runs on CPU by default and does not need a GPU; add `--device cuda` to use one.

## Quickstart (about ten minutes)

About ten minutes to a first search means searching a partial index. Package
and model download time depends on the connection; a large or cloud-mounted
library can take hours to finish indexing.

1. Without Git, use **Code → Download ZIP** on this repository, extract it, and
   open a terminal in the extracted folder containing `pyproject.toml`. An
   existing source archive works too. With Git, clone this repository:
   ```sh
   git clone <this repository's address> shotseek && cd shotseek
   ```
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and let
   it create a Python 3.12 environment. It downloads Python when needed, avoiding
   old macOS Python and Linux's missing `ensurepip`. On Linux/macOS:
   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   uv venv --python 3.12
   . .venv/bin/activate
   ```
   The installer normally writes `uv` and `uvx` to `~/.local/bin` and updates
   your shell profile. The PATH line makes them available in this shell;
   opening a new terminal also works. If `XDG_BIN_HOME`, `UV_INSTALL_DIR`, or
   `UV_UNMANAGED_INSTALL` selects another directory, replace `$HOME/.local/bin`
   in that line with the chosen directory. A custom or unmanaged install may
   provide no `env` setup file. For an isolated install without profile changes,
   see [platform setup](docs/platforms.md).

   On native Windows, use PowerShell:
   ```powershell
   winget install --id astral-sh.uv -e
   ```
   Reopen PowerShell so `uv` is on PATH, then return to the checkout. Alternatively,
   use the PowerShell installer in the current session:
   ```powershell
   New-Item -ItemType Directory -Force .scratch | Out-Null
   Invoke-WebRequest -UseBasicParsing https://astral.sh/uv/install.ps1 -OutFile .scratch\install-uv.ps1
   & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File .scratch\install-uv.ps1
   $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
   uv venv --python 3.12
   ```
   The PowerShell installer normally writes `uv.exe` and `uvx.exe` into
   `%USERPROFILE%\.local\bin` and updates your user PATH. Restart PowerShell
   or use the explicit PATH line above to make it available in this session.
   Follow the printed location if you chose another install directory.

   After winget, also run `uv venv --python 3.12`. No venv activation or execution
   policy change is needed to run the venv executables. The installer above uses
   Bypass only in its child process; it leaves the caller and persistent policies
   unchanged. An enforced Group Policy can still block it. In subsequent commands replace `shotseek`
   with `& .\.venv\Scripts\shotseek.exe`.

   **Alternative without uv:** first run `python3 --version`; it must be **3.11+**.
   If it is older, use uv above, which downloads a compatible Python. Then run
   `python3 -m venv .venv && . .venv/bin/activate`. On Debian/Ubuntu, an
   `ensurepip`/venv failure needs `sudo apt install python3-venv` (or the matching
   version package, such as `python3.12-venv`); use uv if you cannot install it.
   Windows with Python 3.12 already installed can use `py -3.12 -m venv .venv`.
   For this alternative replace `uv pip install` below with `python -m pip install`
   (Windows: `& .\.venv\Scripts\python.exe -m pip install`).
3. Install **both ffmpeg and ffprobe** before indexing. They must be on PATH;
   Python dependency wheels do not provide these command-line programs.
   Debian/Ubuntu: `sudo apt install ffmpeg`. macOS with Homebrew:
   `brew install ffmpeg`. Windows: `winget install --id Gyan.FFmpeg -e`, then
   reopen PowerShell and return to the checkout.

   Without administrator access, Linux x86_64 can use a
   [John Van Sickle static build](https://johnvansickle.com/ffmpeg/):
   ```sh
   mkdir -p .scratch/ffmpeg
   curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o .scratch/ffmpeg.tar.xz
   tar -xJf .scratch/ffmpeg.tar.xz -C .scratch/ffmpeg --strip-components=1
   export PATH="$PWD/.scratch/ffmpeg:$PATH"
   ```
   On Apple Silicon without Homebrew, download both arm64 executables from
   [OSXExperts](https://www.osxexperts.net/):
   ```sh
   mkdir -p .scratch/ffmpeg
   curl -L https://www.osxexperts.net/ffmpeg9arm.zip -o .scratch/ffmpeg.zip
   curl -L https://www.osxexperts.net/ffprobe9arm.zip -o .scratch/ffprobe.zip
   unzip .scratch/ffmpeg.zip -d .scratch/ffmpeg
   unzip .scratch/ffprobe.zip -d .scratch/ffmpeg
   chmod +x .scratch/ffmpeg/ffmpeg .scratch/ffmpeg/ffprobe
   export PATH="$PWD/.scratch/ffmpeg:$PATH"
   ```
   Intel Macs need Intel builds from that page. A quarantined browser download
   may need approval for that individual file in macOS Privacy & Security.
   On Windows without winget, use [Gyan's portable essentials ZIP](https://www.gyan.dev/ffmpeg/builds/):
   ```powershell
   New-Item -ItemType Directory -Force .scratch | Out-Null
   Invoke-WebRequest -UseBasicParsing https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile .scratch\ffmpeg.zip
   Expand-Archive .scratch\ffmpeg.zip -DestinationPath .scratch\ffmpeg
   $ffmpegBin = (Get-ChildItem .scratch\ffmpeg -Directory | Select-Object -First 1).FullName + '\bin'
   $env:PATH = "$ffmpegBin;$env:PATH"
   ```
   These portable PATH changes last only for the current shell. Verify both:
   ```sh
   ffmpeg -version
   ffprobe -version
   ```
4. On Windows x64, install the Microsoft Visual C++ v14 Redistributable before
   loading PyTorch or the speech runtime:
   ```powershell
   New-Item -ItemType Directory -Force .scratch | Out-Null
   Invoke-WebRequest -UseBasicParsing https://aka.ms/vc14/vc_redist.x64.exe -OutFile .scratch\vc_redist.x64.exe
   Start-Process .scratch\vc_redist.x64.exe -ArgumentList '/install' -Wait
   ```
   Complete the installer and restart if requested. Stop if installation fails;
   reinstalling Python wheels does not install the Windows native runtime.

   On Linux or Windows CPU installs, install PyTorch and torchvision together
   from the CPU wheel index. Both must use matching builds. **Skip this first
   command on macOS**; its PyPI wheels support CPU and Apple Silicon MPS.
   Windows CUDA users should use the matching CUDA pair in
   [platform setup](docs/platforms.md) instead (about 2.75 GB for torch alone).
   ```sh
   uv pip install 'torch>=2.2' 'torchvision>=0.17' --index-url https://download.pytorch.org/whl/cpu
   uv pip install .
   ```
   The second command installs shotseek and remaining dependencies from PyPI;
   do not keep the CPU wheel index as a global index. CPU torch wheels measured
   roughly 125–200 MB, plus other dependencies; a Linux CPU environment measured
   about 1.6 GB. Sizes vary by version and platform.

   For the Python venv alternative in step 2, the equivalent commands are:
   ```sh
   python -m pip install 'torch>=2.2' 'torchvision>=0.17' --index-url https://download.pytorch.org/whl/cpu
   python -m pip install .
   ```
   On macOS, skip the first command as above.
   On Windows, check the native libraries before downloading model weights:
   ```powershell
   & .\.venv\Scripts\python.exe -c "import torch, torchvision, open_clip, faster_whisper; print(torch.ones(1).item())"
   ```
   Expect `1.0`. A DLL-loading error means the native runtime or matching wheels
   still need attention. Continue only after the imports succeed.

5. Check local requirements, including torchvision's CPU operators.
   A missing config is a warning at this stage. If ffmpeg or ffprobe is absent,
   JSON shows a `fail` check with detail `Missing` and hint
   `Install ffmpeg and ffprobe.`, `ok: false`, and exit 6. Install them using
   step 3, restore PATH in this shell, and rerun doctor:
   ```sh
   shotseek doctor
   ```
6. Choose a media folder; the index stays outside it:
   ```sh
   shotseek init --library media=/path/to/media
   ```
   Quote the entire argument when the path contains spaces. On native Windows:
   ```powershell
   & .\.venv\Scripts\shotseek.exe init --library "media=C:\Media\Generated Photos"
   ```
   To **add another folder** later, keep the existing config and use two separate
   arguments (no `=`):
   ```sh
   shotseek library add extra "/path/to/second media folder"
   shotseek library list
   ```
   Then run `shotseek index` to index both libraries. Do not rerun `init` to add
   a folder: `init --force` replaces the whole config, including libraries and
   custom settings. Use separate `--config` and `--index-dir` paths when sharing
   an account with another installation.
7. Start a five-minute indexing pass. The first pass downloads the image model
   (stored once in the local model cache):
   ```sh
   shotseek index --time-budget 300
   ```
8. Search the committed partial index:
   ```sh
   shotseek search "a barista pouring latte art" --format text
   ```
9. Finish indexing. This command can be stopped and resumed:
   ```sh
   shotseek index
   ```

Downloaded default model files measured 605.14 MB for OpenCLIP image/text and
147.88 MB for base speech (decimal MB). Package and model disk use depends on
installed versions. The measured PyPI environment occupied 6.34 GB and its pip
cache 3.23 GB, including CUDA runtime dependencies; execution used CPU. Leave
additional space for the media index (all sizes here use decimal units).

## Connect your agent

For Claude Code, copy `agents/claude/shotseek/` to
`~/.claude/skills/shotseek/`. For Codex, paste `agents/codex/AGENTS.md` into a
project's `AGENTS.md` or `~/.codex/AGENTS.md`. For another agent, paste
`agents/generic/PROMPT.md` into its instructions. See [agent setup](agents/README.md).
Then say: "Use shotseek to find a landscape cafe photo for the website."

## B-roll for a talking-head video

```sh
shotseek broll --media any --point "coffee and pastry at the counter" --point "opening the cafe at dawn"
shotseek broll --aroll /path/to/aroll/intro.mp4 --save-transcript /path/outside/library/aroll.json --format json --output /path/outside/library/beats.json
shotseek broll --beats /path/outside/library/beats.json --format csv --output /path/outside/library/broll.csv
```

B-roll searches **videos only by default**; add `--media any` to include photos,
   as the first example does, or `--media photo` for stills only. A-roll must
   contain speech; silent videos need `--transcript` or `--point` instead.

The `--aroll` command above writes the complete editable B-roll document to
`beats.json` with `--output`; `--save-transcript` writes the separate transcript
`aroll.json`, which is not the beats file. Replace the three example paths with
your A-roll and an output folder outside your libraries. The two commands run
in order as written, including without edits. To refine the plan, open
`beats.json` between runs and add two to four concrete `visual_queries` strings
to weak beats, then run the `--beats` command to write `broll.csv`.

You can also supply `--transcript` with text, SRT, VTT, or JSON. Abstract speech
is often a poor description of visible footage. Each beat recommends one candidate, preferring variety.
The default local speech model is `base`. Automatic planning uses consecutive
4–10 second windows, the need score, and five generic topic hints. Every beat
includes `need_score`, `need_reasons`, `topic`, `suggested_broll`, `search_terms`,
and a 3–6 second `placement`. Low-need, short, filler, and over-limit beats stay
visible with a skip reason. Points and explicit visual queries are always searched.

Use `--segmenter pauses` for pause and similarity boundaries. `--min-need 0.45`
and `--max-beats 12` are defaults; `--max-beats 0` removes the limit.
`--include-filler` searches every beat for that invocation. Keep the source,
revision, and IDs in an edited document so source exclusions survive reruns.
`--keep-near-duplicates` disables visual similarity exclusion while retaining
physical identity and content-sample checks.

Recommendations rank the available candidates; they can be unrelated when the
library has no matching footage. Review each choice before using it. The text
score is cosine similarity followed by `(relevance)`, a z-score relative to the
filtered candidates, **not a probability or confidence percentage**. With only
two candidates, relevance can be +1 and -1 even when both are poor matches.
B-roll ranking is only meaningful on real footage; generated test clips can rank arbitrarily.

## Using a GPU

Install matching CUDA builds of both PyTorch and torchvision using the
[PyTorch selector](https://pytorch.org/get-started/locally/) and your driver
version (the tested Windows torch wheel was about 2.75 GB); [platform setup](docs/platforms.md) records the tested Windows pair. Then add `--device cuda` or set
`device = "cuda"` under `[model]` in the config. `cuda:N`, `mps`, and `auto`
are also accepted by image embedding. CPU is the default, and search uses CPU
unless a flag or environment variable selects another device. Larger OpenCLIP
models can improve visual matching: `ViT-L-14` with `laion2b_s32b_b82k`
(768 dimensions) is the suggested GPU choice. The default is `ViT-B-32` with
`laion2b_s34b_b79k` (512 dimensions). `large-v3` is an optional larger
speech model. Speech on CUDA needs CUDA libraries; initialization failure falls
back to CPU with a warning. Local speech does not support MPS.

## Where your media can live

Use local folders, a NAS path, or a mounted cloud folder such as Google Drive.
There is no cloud API integration. Keep the index on local storage. See
[storage guidance](docs/storage.md) for mounts, remapping, and safe pruning.

## What it stores and what it never does

On Linux and macOS, config defaults to `~/.config/shotseek/config.toml` and the
index to `~/.local/share/shotseek/index`; XDG settings and explicit flags override
them. Native Windows uses `%APPDATA%\shotseek\config.toml` and
`%LOCALAPPDATA%\shotseek\index`.
The index contains relative file paths, metadata, vectors, transcripts, and
320 px JPEG thumbnails. It is as private as the library: protect it accordingly.
Set `thumbnails = false` under `[index]` to disable future thumbnail storage.
A rebuild removes existing thumbnails while preserving cached transcripts.

Each 512-dimensional float16 vector occupies 1,024 bytes, plus metadata and
optional thumbnails. Thumbnail sizes depend on image content. Generated-input
measurements describe only the tested fixtures, not real media or mounts.

CPU measurements on Linux used an eight-core desktop CPU, eight PyTorch threads,
and generated inputs, with models already cached. The PyPI installation included
CUDA runtime packages, but all model execution below used CPU. These fixtures
cannot predict performance or match quality on a real library.

| Generated-input operation | Wall time |
| --- | ---: |
| Index 300 solid-colour JPEG photos, model already loaded | 12.639 s |
| Add 12 frames from one 60-second video | 1.322 s |
| First text searches, including image/text model loading | 0.976–1.124 s |
| Repeat searches using cached query vectors | 0.0049–0.0058 s |
| Transcribe 4.465 seconds of synthetic speech with base | 2.297 s |
| Reuse the cached transcript | 0.0357 s |

The cached image model loaded in 2.018 seconds. Generated JPEG thumbnails averaged
1,829 bytes; detailed photographs can produce larger thumbnails. A separate
400,000-vector synthetic search took 1.255 seconds with 523 MB peak resident memory.
On four generated images, the 448-pixel pre-fit changed cosine similarity by at
most 0.00337; direct image/text model calls agreed within 0.0001.

The tool never writes to a library, copies original media, reads GPS data,
phones home, checks for updates, or calls a model API. It makes no network
calls of its own; model libraries download weights once when first needed.
Model loading and dependency download progress appear on stderr. A Hugging Face
unauthenticated-request warning is informational; no account is required. `--offline` or `SHOTSEEK_OFFLINE=1` blocks
them, and missing cached weights produce a clear error. Temporary extracted
A-roll audio is deleted after transcription.

## Commands

| Command | Purpose |
| --- | --- |
| `init` | Create configuration with named libraries |
| `library` | `library add NAME PATH`, `library list`, or `library remove NAME` |
| `index` | Incrementally index photos and video frames |
| `status` | Inspect progress and index coverage |
| `search` | Rank photos and video moments |
| `broll` | Find candidates for each spoken passage or point |
| `transcribe` | Transcribe locally without an image index |
| `show` | Inspect one file and all its frames |
| `doctor` | Check installation and storage; `--report` adds a pasteable platform report |
| `compact` | Reclaim dead vector rows |
| `schema` | Print JSON contract schemas |
| `agent-prompt` | Print agent instructions |

Use `--config /path/to/config.toml` and `--index-dir /path/to/index` to keep
separate configurations and indexes outside your media folders.

Default output is JSON; search and B-roll also support CSV and text.
`search --raw-frames` returns individual frames in descending score order,
without moment merging, per-file limits, or duplicate folding. Batch query CSVs
use `query_id,query`; see [invented queries](docs/examples/queries.csv).

`index` can exit 0 even when individual files fail: successful files remain
indexed, and `warnings`, `totals.failed`, and `failures_sample` report failures.
Use `shotseek index --strict` for exit 8 when files fail, or
`shotseek index --retry-failed --strict` to retry them. Storage and other fatal
errors still have their own nonzero codes. Files not reached because a folder
became unavailable are counted separately in `totals.not_reached` and each
library's `not_reached`, with a `files_not_reached` warning. Reconnect and rerun
indexing normally; these files are not recorded as failed. The run still exits 4
and preserves completed rows. Put command-specific flags such as
`--device` after the subcommand: `shotseek search "a red mug" --device cpu`.

`index --max-files-per-library N` caps newly indexed files separately for each
library and leaves a resumable partial run. There is no default file cap.

Under `[indexing]`, `frame_reader` accepts `auto`, `opencv`, or `ffmpeg`.
`auto` uses the guarded OpenCV seek/read path with an ffmpeg fallback.
`video_sampling = "interval"` samples every five seconds by default, spreading
capped samples across the full sample range. `video_sampling = "fixed"` uses
`video_samples_per_file = 4` positions from 15% through 85% of the video. See the
[output reference](docs/output.md) for fields, flags, and exit codes.

## Limitations and not in this version

English queries only. Video timestamps are accurate to the sampling interval.
RAW files are counted but not decoded: portable generated RAW fixtures are
unavailable, files are large on slow mounts, and JPEG or HEIC companions are
common. HEIC requires pillow-heif. Animated images use their first frame.

There is no graphical or web interface, MCP server, cloud API, OCR, library
speech search, shot-boundary detection, clip export or copying, file watcher,
background service, timer, or package-registry publication in this version.
Face recognition and identifying people are never planned. Platform checks use
small generated fixtures and do not establish performance on large libraries.
Mounted-storage checks cover small generated libraries and available media;
cold cloud placeholders, completed cloud synchronization, physical network
partitions, packet-level throttling, and large network libraries remain
unverified. A-roll transcription does not make library speech searchable.

On macOS, OpenCV and PyAV wheels can emit duplicate AVFoundation class warnings
(`AVFFrameReceiver` / `AVFAudioReceiver`). The tested CPU/MPS runs completed
without a crash; this does not establish that every wheel combination is safe.
See [platform setup](docs/platforms.md) if these warnings accompany a failure.

## Known issues

A few timing-based tests may flake on a heavily loaded machine. One unexplained,
one-off Python 3.12 test-step failure during release verification did not
reproduce in two clean runs.

## What has been verified

Platform checks on 2026-10-09 used the default OpenCLIP model, generated media,
Python 3.12, isolated package/model folders, and no administrator changes.
Earlier checks identified prerequisite and shell gaps now covered in the
quickstart and
[platform setup](docs/platforms.md).

| Platform or storage | Verified coverage | Still untested |
| --- | --- | --- |
| Linux CPU | Quickstart, doctor report, 60 generated photos + 3 short videos, image/video search, long paths, compact and rebuild | Large real libraries |
| Apple Silicon macOS, CPU and MPS | Quickstart, doctor reports, the same media and searches on both devices; CPU ffmpeg paths up to 395 characters, compact and rebuild; doctor identifies the CPU | MPS speech (unsupported); browser-download Gatekeeper approval |
| Native Windows, CPU and NVIDIA RTX-class CUDA | PowerShell quickstart, doctor reports, generated photos/videos on both devices; UTF-8 legacy pipes, 376-character media paths with long-path policy disabled, auto/ffmpeg decoders, compact and rebuild | AMD GPU execution, CUDA speech |
| NAS, read-only SSHFS | Two bundled OS icons indexed and searched through a live remote mount; unchanged rerun; source hashes and timestamps unchanged | Personal or large NAS libraries, mount outages |

### Mounted storage

Live checks on 2026-10-10 used generated media, local indexes, and the default
CPU OpenCLIP model. A verified read means the file opened normally through its
mounted path; it does not establish an online-only cloud state.

| Storage and platform | Verified live coverage | Mounted / identical local index time |
| --- | --- | ---: |
| NFS 4.1, Linux | 64 photos and three videos; init/add, index/search, unchanged and mutation reruns, doctor, point/spoken B-roll, permission failure/retry, writer locking; bounded injected listing stall | 9.848 / 9.839 s |
| Google Drive for desktop, macOS File Provider | The tested install read 64 photos and three videos normally; 424-character paths, case/Unicode, index/search/reruns, doctor, spoken B-roll, permission failure/retry, writer locking; provider reported a generated file uploading | 8.651 / 8.042 s |
| Google Drive for desktop, Windows streaming | Available files read normally: 64 photos and three videos, 366-character paths with long-path policy disabled, case/Unicode, index/search/reruns, doctor, spoken B-roll, partial-write failure/retry, writer locking | 8.719 / 8.703 s |
| SMB, macOS | 64 photos and three videos; index/search, second library, doctor, spaces/Unicode, unchanged pass with zero media reads, case-alias overlap/write guards, share-removal failure and recovery | 8.456 / 4.043 s |
| SMB, Linux GVfs/gio | The same generated-media flow, zero-read unchanged pass, share-removal recovery and case-alias guards despite synthetic inode IDs | 5.586 / 5.095 s |
| SMB, Windows drive letter | The same generated-media flow, zero-read unchanged pass, share-removal recovery and case-alias guards | 4.907 / 4.688 s |
| SMB, Windows UNC | The same generated-media flow and guards; existing-index search also passed while the scratch share was absent | 5.141 / 4.688 s |

Timings are single whole CLI commands with models cached, including model
startup; SMB timings use matching cached rebuilds. They do not establish
large-library throughput or ranking quality. The earlier platform timings below
measure a different, in-process flow.

Fault checks retained searchable successes, pruned no rows after share removal,
and recovered on retry. Partial writes and injected slow reads were reported;
wrong credentials and temporary account expiry rejected fresh SMB connections.
Case aliases cannot bypass library-overlap or output-write guards, and writes
are refused when alias verification is incomplete. Account expiry does not test
password-policy expiry.

**Not verified:** truly online-only (cold) Drive files, Drive mirrored mode,
physical network partition or packet-level throttling, password-policy expiry,
guaranteed offline availability, completed cloud upload, large real libraries,
or other SMB servers/dialects. Tests could not produce and independently confirm
a cold Drive file. The later exact scratch folder was absent on the Mac install,
so that supplemental cold-file check could not run there. The Windows Drive
ACL-denial attempt also did not establish native permission-denial coverage.

An additional Windows streaming check used four cloud-created JPEGs of
995–1,175 bytes. First reads succeeded in 172–231 ms each, with one content open
per file; search and doctor passed, and unchanged indexing opened no media.
Windows reported only Normal attributes, without offline/recall/pinned/reparse
flags. Unpinning left those attributes unchanged; rebuild reads took 2–5 ms.
Neither cloud creation nor these timings proved a first or second cold pass.
Doctor checks reachability, not individual cloud placeholder state.

For online-only files, shotseek opens the mounted path and the Drive client
triggers a download. Slow or failed reads are retried and reported as `timeout`
or `read_error`; successful files remain searchable. Let downloads finish and
rerun with `--retry-failed --strict`. A bounded worker can stop the CLI waiting,
but cannot cancel the provider's download or a stalled kernel read. Keep the
model cache, config, and index on local storage outside the mounted library.
See [network drives and cloud mounts](docs/platforms.md#network-drives-and-cloud-mounts)
for setup, retry limits, change-detection limits, and storage-specific gaps.

The measured indexing passes used 60 generated photos and three six-second
videos, with the model already loaded and eight CPU threads. Each device used
its default batch size (16 on CPU, 64 on GPU); media decoding still used CPU.
These are single small-fixture passes, not reliable GPU speedup estimates.

| Platform and device | Files | Index time | Files/s |
| --- | ---: | ---: | ---: |
| Linux CPU, eight-core desktop | 63 | 7.574 s | 8.318 |
| Apple Silicon macOS, CPU | 63 | 0.901 s | 69.949 |
| Apple Silicon macOS, MPS | 63 | 0.862 s | 73.121 |
| Windows CPU | 63 | 1.223 s | 51.522 |
| Windows NVIDIA RTX-class GPU, CUDA | 63 | 0.637 s | 98.907 |
| Second Linux machine, CPU | 63 | 6.438 s | 9.786 |
| NAS read-only SSHFS, CPU (two OS icons) | 2 | 0.280 s | 7.134 |

The maintainer previously verified a run limited to 200 videos. Libraries of
tens of thousands of files remain unverified. All timings here are generated
fixtures or the explicitly identified NAS sample, not a real-media benchmark.

To help close these gaps, run this on your machine and paste the result into an
issue:

```sh
shotseek doctor --report
```

On tested macOS wheels, the two AVFoundation duplicate-class warnings
(`AVFFrameReceiver` / `AVFAudioReceiver`) on stderr were harmless and the runs
completed. They can also appear above a pasted report if stderr is merged;
`shotseek doctor --report > doctor-report.txt` saves just the report on stdout.

It prints your OS, Python, CPU, GPU/MPS availability, whether `ffmpeg` and
`ffprobe` are found, whether the model is cached, and PASS or FAIL for indexing
and searching three generated photos in a scratch folder. The first run
downloads the model if it is not cached; add `--offline` to forbid that and
`--device cuda` (or `mps`) to test an accelerator. Home folders are shown as `~`
and your media and config paths are not printed. To test a NAS or mounted
folder, run `shotseek init --library media=<path>` and `shotseek doctor`
first; `doctor` then also reports whether each library is reachable.

## Related tools

Full photo managers with smart search include Immich and PhotoPrism; shotseek
is a small command-line index for agents.

## Third-party components and licenses

OpenCLIP and its default weights, faster-whisper and its models, PyTorch,
torchvision, OpenCV, Pillow, pillow-heif, and numpy each have their own terms.
[THIRD-PARTY.md](THIRD-PARTY.md) lists them, the model licenses, and the native
libraries that some wheels bundle. `ffmpeg` is an external program you install
yourself, not bundled.

Some dependency wheels bundle GPL/LGPL native libraries, including GPL codecs
in pillow-heif and PyAV. shotseek does not redistribute these wheels. Review
their terms before redistributing an installed environment or application.

## License

MIT. See [LICENSE](LICENSE).
