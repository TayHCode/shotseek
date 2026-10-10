# Platform setup

Use a short, writable local checkout and Python 3.11 or newer. The field checks
used Python 3.12. Keep the virtual environment, model cache, config, and index
outside your media libraries. Use the README quickstart after installing the
prerequisites below. Dependency wheels are platform specific: do not copy a
virtual environment between machines.

## Python without administrator changes

The system Python on macOS may be 3.9, which cannot install shotseek. Some Linux
distributions omit `ensurepip`, so `python3 -m venv` fails. You can use
[uv's official installer](https://docs.astral.sh/uv/reference/installer/) without
changing system Python or shell profiles. This optional POSIX setup keeps uv,
its Python install, and its cache in the checkout's ignored scratch folder:

```sh
mkdir -p .scratch/tools/bin
export UV_UNMANAGED_INSTALL="$PWD/.scratch/tools/bin"
export UV_PYTHON_INSTALL_DIR="$PWD/.scratch/tools/python"
export UV_PYTHON_BIN_DIR="$PWD/.scratch/tools/bin"
export UV_CACHE_DIR="$PWD/.scratch/tools/cache"
curl -LsSf https://astral.sh/uv/install.sh -o .scratch/tools/install-uv.sh
sh .scratch/tools/install-uv.sh
export PATH="$PWD/.scratch/tools/bin:$PATH"
.scratch/tools/bin/uv python install 3.12
.scratch/tools/bin/uv venv --seed --python 3.12 .venv
. .venv/bin/activate
```

`UV_UNMANAGED_INSTALL` writes the uv executables into `.scratch/tools/bin`
without changing shell profiles or creating the usual `~/.local/bin/env` file.
The PATH line immediately after installation is required for the README's
subsequent `uv pip install` commands in this same shell. Repeat it after opening
a new shell, or use `.scratch/tools/bin/uv` explicitly for every uv command.

**Alternative without uv:** if `python3 --version` reports 3.11+, run
`python3 -m venv .venv && . .venv/bin/activate`, then replace `uv pip install`
with `python -m pip install`. This needs the system's venv/ensurepip support;
if unavailable, use the isolated uv route above. On Windows with Python 3.12,
use `py -3.12 -m venv .venv` and `& .\.venv\Scripts\python.exe -m pip install`.

Specifying `UV_PYTHON_BIN_DIR` matters: selecting an install directory alone does
not keep Python launcher links or caches inside it. If you use a temporary test
folder, also set `HF_HOME`, `HF_HUB_CACHE`, `TORCH_HOME`, `XDG_CACHE_HOME`,
`PIP_CACHE_DIR`, `CUDA_CACHE_PATH` for NVIDIA, and the OS temporary-directory
variable inside that folder before
installation or the first model load. `HF_HUB_CACHE` overrides `HF_HOME`'s default
hub location. Delete the test folder only after processes exit and mounts are
unmounted.

## ffmpeg and ffprobe

Both executables must be on the current process's `PATH`. Installing
`opencv-python-headless`, PyAV, or a Python package named ffmpeg does not provide
both programs. Verify before indexing:

```sh
ffmpeg -version
ffprobe -version
```

Choose a build for your OS and architecture from the
[FFmpeg download page](https://ffmpeg.org/download.html). On Linux you can unpack
a static build in a user folder and prepend its directory to `PATH`. For x86_64,
[John Van Sickle](https://johnvansickle.com/ffmpeg/) provides both programs:

```sh
mkdir -p .scratch/ffmpeg
curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o .scratch/ffmpeg.tar.xz
tar -xJf .scratch/ffmpeg.tar.xz -C .scratch/ffmpeg --strip-components=1
export PATH="$PWD/.scratch/ffmpeg:$PATH"
ffmpeg -version
ffprobe -version
```

On Apple Silicon use arm64 binaries. The field check used the separate ffmpeg
and ffprobe 9.0 downloads from [OSXExperts](https://www.osxexperts.net/), unpacked
in a temporary folder. Both ran without a Gatekeeper change when downloaded
with curl. A browser download may be quarantined: verify its source using the
distributor page above, then approve that individual executable through macOS Privacy & Security if
needed. Do not disable Gatekeeper globally. If the build needs ad-hoc signing,
follow its distributor's instructions for that downloaded file only. The
quarantine/approval workflow was not exercised by the field check.

On Windows the tested portable distribution was Gyan's
[release essentials ZIP](https://www.gyan.dev/ffmpeg/builds/). Expand it into a
user folder and prepend the extracted `bin` directory for the current PowerShell
session, replacing the example with the actual extracted path:

```powershell
$env:PATH = "$PWD\tools\ffmpeg\bin;$env:PATH"
ffmpeg -version
ffprobe -version
```

This does not persist a system PATH change. The essentials build is sufficient
for indexing. The optional synthetic speech test additionally needs ffmpeg's
`flite` filter, which is absent from some builds.

## Native Windows and CUDA

The POSIX activation command in the README does not run in cmd or PowerShell.
Install uv using the README quickstart. Use PowerShell and the virtual
environment executables directly; no activation or execution-policy change
is required:

```powershell
uv venv --python 3.12
uv pip install 'torch>=2.2' 'torchvision>=0.17' --index-url https://download.pytorch.org/whl/cpu
uv pip install .
& .\.venv\Scripts\shotseek.exe doctor
& .\.venv\Scripts\shotseek.exe init --library "media=C:\Media\Generated Photos"
& .\.venv\Scripts\shotseek.exe index --time-budget 300
& .\.venv\Scripts\shotseek.exe search 'a barista pouring latte art' --format text
& .\.venv\Scripts\shotseek.exe index
& .\.venv\Scripts\shotseek.exe doctor --report
```

For NVIDIA CUDA replace the CPU wheel step before installing shotseek. Use the
[PyTorch selector](https://pytorch.org/get-started/locally/) for a CUDA build
compatible with your installed driver. The Windows NVIDIA RTX-class GPU check used driver
616.92, torch 2.11.0+cu128, and torchvision 0.26.0+cu128:

```powershell
uv pip install 'torch==2.11.0' 'torchvision==0.26.0' --index-url https://download.pytorch.org/whl/cu128
& .\.venv\Scripts\python.exe -c "import torch, torchvision; print(torch.__version__, torchvision.__version__); print(torch.cuda.is_available())"
& .\.venv\Scripts\shotseek.exe index --device cuda
& .\.venv\Scripts\shotseek.exe search 'a red rectangle' --device cuda
& .\.venv\Scripts\shotseek.exe doctor --report --device cuda
```

Matching torch and torchvision builds are required. CUDA availability must be
true; an AMD integrated GPU cannot use NVIDIA CUDA. The wheel download was about
2.75 GB for torch alone. These wheels contain the CUDA runtime for image
embedding; this test required no system CUDA toolkit install. Speech uses a
separate CTranslate2 runtime, whose CUDA library requirements differ. The package
constrains PyAV below 19 for the speech decoder API; reinstall shotseek after
upgrading dependencies so this compatibility constraint is applied. Windows
CPU execution can use the same CUDA environment with `--device cpu`; a separate
CPU-only Windows wheel installation was verified in the subsequent stranger checks.

Use quoted, ordinary Windows paths; do not paste a POSIX `/path/to/media` into
PowerShell. TOML literal strings avoid backslash escapes when editing a config:

```toml
[[library]]
name = "media"
root = 'C:\Media\Generated Photos'
```

shotseek emits UTF-8 on stdout and stderr, including redirected pipes. Decode
JSON and text output as UTF-8 in consuming scripts; older PowerShell versions may
use a different encoding when redirecting native output to a file. Use shotseek's
`--output` option for UTF-8 search exports.

Keep the checkout, virtual environment, and index paths short. shotseek uses
Win32 extended paths internally when walking libraries and reading media, while
keeping ordinary paths in config and results. This addresses the tested machine's
disabled `LongPathsEnabled` setting without changing its registry policy. It does
not establish support in every native dependency, network provider, or editor
opening the result. The verified coverage table records the actual long-path
checks. Use a shorter path when another program cannot open long media paths.

## Apple Silicon MPS

Use an arm64 Python and macOS PyPI wheels; skip the CPU/CUDA wheel-index step.
Check `torch.backends.mps.is_available()` or the doctor report, then select MPS
for both image indexing and search:

```sh
shotseek index --device mps
shotseek search 'a red rectangle' --device mps
shotseek doctor --report --device mps
```

CPU remains the default. MPS image/text embedding was tested; local speech uses
CPU on macOS and does not support MPS. Small fixtures and first-run shader costs
are unsuitable for estimating GPU speedups on a large library.

OpenCV and PyAV macOS wheels may both bundle AVFoundation classes, producing
`AVFFrameReceiver` and `AVFAudioReceiver` duplicate-class warnings. CPU and MPS
checks passed with these warnings, without a crash. They originate in native
dependency wheels and are not suppressed by shotseek. If a crash accompanies
them, record both package versions and try a fresh environment with matching
platform wheels; report the failure with `doctor --report`.

## Network drives and cloud mounts

Mount the media through the operating system, then pass that mounted folder to
`init --library NAME=PATH` or `library add NAME PATH`. shotseek has no Drive,
SMB, or NFS client and does not manage credentials or reconnect mounts. Keep
the Python environment, model cache, config, index, and output files on a local
disk outside the library. Use explicit paths so another installation cannot
reuse the same config or index:

```sh
shotseek --config /path/to/local/config.toml --index-dir /path/to/local/index init --library media=/path/to/mounted/media
shotseek --config /path/to/local/config.toml --index-dir /path/to/local/index index --time-budget 300 --strict
shotseek --config /path/to/local/config.toml --index-dir /path/to/local/index search "a red rectangle"
```

### Drive for desktop

For repeatable indexing, prefer a mirrored My Drive folder or mark the selected
streamed media folder available offline in Drive for desktop and let downloads
finish before indexing. Mirroring keeps a local copy; streaming fetches files
when opened unless made available offline. macOS streaming uses File Provider.
See Google's [streaming and mirroring guide](https://support.google.com/drive/answer/13401938)
and [macOS File Provider guide](https://support.google.com/drive/answer/12178485).
shotseek cannot determine that a folder has finished uploading or guarantee that
cached files remain available offline. An ordinary successful read does not
verify cold-placeholder hydration or persistence without a network connection.

The supplemental Windows streaming check used four JPEGs created in the cloud
before any test content read. All four first reads succeeded, taking 172–231 ms
each; indexing opened each file once and did not add a separate hashing pass.
Search and `doctor --report` passed. An unchanged rerun opened no media, while
still walking and checking size/mtime. Windows exposed only `Normal` (128)
attributes before reading, with no Offline, RecallOnDataAccess, Pinned, or
ReparsePoint flag; `fsutil` reported no reparse point. These observations do
not independently prove online-only state. `attrib +U -P` succeeded but left
attributes unchanged, and rebuild reads took 2–5 ms each: a second cold pass
was not established. Sizes and mtimes stayed stable after reading and unpinning.
The exact cloud-created scratch folder was absent from the macOS File Provider
mount, so macOS placeholder metadata, hydration, and a second cold pass could
not be tested. Mirrored Drive mode and independently confirmed cold Drive reads
remain untested.

Doctor checks library reachability and a generated local sample; it does not
inspect or flag individual cloud placeholders. Photo reads use
`[indexing].file_timeout_seconds` (120 seconds by default), including time spent
waiting for provider hydration. A fake provider read failure returned
`read_error`, and a stalled read returned `timeout`; successful files remained
searchable and a later pass retried the failed file. These are injected error
and delay checks, not a real Drive outage. The CLI can stop waiting for a
blocked daemon worker, but cannot cancel the underlying provider download.

The first pass opens every supported image and samples every video, potentially
downloading the full video into the Drive client's local cache. Leave room for
that cache in addition to models and the index. Indexing while a file is still
being written can record a decode failure; let the upload/download finish and
rerun with `--retry-failed --strict`. A stable timestamp or size is not proof
that cloud synchronization completed. Use the Drive client's status for that.
Deleting a test folder through the mount sends its cloud contents to Drive
Trash; deleting the local index does not empty cloud Trash.

### SMB and NFS

Use an existing authenticated OS mount. A read-only media share is sufficient;
shotseek writes its index locally. On Windows, quote the UNC root supplied by
the share's administrator. Extended UNC paths are converted internally, but
support still depends on the SMB client and media-decoder libraries. On macOS,
use the mounted volume's path. On Linux, use the administrator's existing NFS
mount or user-level SMB mount; shotseek needs no root privileges.

The live Linux NFS check used NFS 4.1 with a hard mount and normal attribute
caching. It did not change mount options. Keep the options selected by the
share administrator; a stalled kernel read on a hard mount cannot be canceled
by shotseek, though its bounded daemon workers let the CLI stop waiting. Use
`--time-budget` for a resumable pass, `--workers 2` to limit concurrent reads,
and `--no-prune` when a share is temporarily incomplete. Reconnect through the
OS before retrying. The SMB checks removed only a generated scratch share to
exercise real read failures and recovery; physical network partitions and NFS
disconnects were not induced.

Initial indexing costs directory listings, file stats, media reads, decoding,
and embedding. Unchanged reruns still walk and stat the library, but do not
read unchanged media; they also load the image model. Network latency therefore
matters even when the index is up to date. Normal change detection uses size and
mtime with a two-second tolerance, not a full media hash or inode identity.
Same-size edits inside that tolerance can be missed. For unreliable timestamps,
`change_detection = "size"` avoids timestamp-driven reindexing but also misses
every same-size edit; use a deliberate rebuild when content may have changed.

Transient filesystem errors during photo stat/read under a reachable root are
recorded as `read_error`
and retried automatically up to three failed attempts; `--retry-failed` allows
an explicit retry afterward. Slow reads are bounded by per-file deadlines and
reported as `timeout`; retry after the provider recovers. Decoder failures
remain `decode_failed`. Default indexing retains partial results with exit 0; `--strict` returns 8 for failed
files. If the root becomes unavailable, discovered files not reached count
separately as `not_reached`; reconnect and rerun normally without a retry flag.
Directory traversal errors return 4 and prevent pruning. Symlink files
and directories are skipped unless `follow_symlinks = true`; providers with
zero inode numbers use resolved directory paths for traversal-cycle detection.
Library-overlap and output-write checks also verify case aliases on mounted
providers, including providers with synthetic inode IDs. They refuse writes
when alias verification cannot complete because listing fails or its bounded
inspection limit is reached.

### Mounted-storage verification scope

Checks use small generated fixtures, a local index, and default CPU OpenCLIP.
They establish the specific mounted-path operations recorded in the README
table, not large-library performance or every provider state. A doctor report
checks library reachability and runs its generated sample on local temporary
storage; a passing report alone does not verify mounted media decoding.

| Storage | OS | Verified | Unverified or blocked |
| --- | --- | --- | --- |
| NFS 4.1 | Linux | 64 photos and three videos, init/add, index/search, unchanged and mutation reruns, doctor, B-roll, permission failure/retry, writer locking, simulated listing stall; 9.848 s index vs 9.839 s local | Actual disconnect, other mount options/clients, large libraries |
| Drive File Provider | Apple Silicon macOS | 64 photos and three videos, 424-character paths, case/Unicode, init/add, index/search/reruns, doctor, spoken B-roll, permission failure/retry, writer locking, simulated listing stall; 8.651 s index vs 8.042 s local; provider reported a generated file uploading | Eviction failed (`brctl` exit 1); cold placeholders, offline guarantees, upload completion, mirrored mode |
| Drive virtual mount | Native Windows | 64 photos and three videos, 366-character paths with long-path policy disabled, case/Unicode, index/search/reruns, doctor, spoken B-roll, partial-write failure/retry, writer locking; 8.719 s cached rebuild vs 8.703 s local | `attrib +U -P` returned 0 but attributes stayed 128; no cold file established. ACL deny attempt returned 87. Offline guarantees, upload completion, mirrored mode and provider disconnects unverified |
| SMB | macOS | 64 photos and three videos; index/search, second library, doctor, spaces/Unicode, zero-read unchanged pass, case-alias overlap/write guards, scratch-share removal/recovery; 8.456 s SMB vs 4.043 s local | Physical network partitions, packet-level throttling, password-policy expiry, other servers/dialects, large libraries |
| SMB drive letter | Windows | The same generated-media flow, zero-read unchanged pass, alias guards and scratch-share removal/recovery; 4.907 s SMB vs 4.688 s local | The same unverified SMB states |
| SMB UNC | Windows | The same generated-media flow and guards; existing-index search while share absent; 5.141 s SMB vs 4.688 s local | The same unverified SMB states |
| SMB GVfs/gio | Linux | The same generated-media flow, zero-read unchanged pass, alias guards with synthetic inode IDs, scratch-share removal/recovery; 5.586 s SMB vs 5.095 s local | The same unverified SMB states |

All live timings are single whole CLI commands with models cached and local
indexes. They include model loading, unlike the earlier in-process benchmarks.
These fixtures cannot establish relative performance on a real library. Live
SMB scratch-share removal tested post-disconnect errors without disrupting
the network. Successful rows stayed searchable, zero rows were pruned, and all
68 generated files recovered after restoring the share and retrying. Controlled
application-level delays tested deadlines; packet-level throttling was not used.
Wrong credentials and temporary account expiry rejected fresh SMB connections;
password-policy expiry and saved-credential behavior remain unverified.
No owner data was examined, and generated mount folders were removed after use.

## Known issues

A few timing-based tests may flake on a heavily loaded machine. One unexplained,
one-off Python 3.12 test-step failure during release verification did not
reproduce in two clean runs.
