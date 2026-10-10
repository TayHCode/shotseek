# How it works

Streaming discovery visits every eligible folder without sorting the entire
library. Hidden files, known cache folders, and configured globs are ignored.
Photos yield one oriented RGB image. Interval sampling starts at half the
interval (at least one second), ends at the mirrored distance from the end,
and advances by the interval. A clip shorter than the interval uses its middle.
If the cap applies, the capped count is spread evenly between the first and
last sample. Fixed mode places four samples from 15% through 85%; clips under
five seconds use their middle. Defaults are a five-second interval and 60 frames.

A whitelisted ffprobe runs first. OpenCV receives only allowlisted video
containers and local-file protocols. It seeks by frame number, reads, and
immediately fits the frame within 448 by 448. A failed frame falls back to a
bounded ffmpeg subprocess. `frame_reader = "ffmpeg"` forces that reader.

SQLite stores files, frames, and runs in WAL mode. Normalized vectors live in
an append-only little-endian float16 file. Checkpoints occur every 64 finished
files or 30 seconds: append and fsync vectors, atomically write thumbnails,
then commit metadata. Readers use only committed rows. After interruption a
writer truncates uncommitted bytes before resuming. Changed or removed files
leave dead vector rows; compaction writes a new generation before swapping
metadata. Only one writer holds the operating-system lock. Readers remain
available and report incomplete coverage during a run.

Exact search memory-maps vectors in 32,768-row chunks, casts to float32, and
scores all queries by matrix multiplication. Filtered candidates supply mean,
standard deviation, and maximum scores. Relevance is `(score - mean) / std`,
with a small floor for constant scores. A query-vector cache avoids reloading
the image model for repeated text. At the v0.1 design target of roughly
400,000 vectors, exact search avoids approximate recall loss and another binary
dependency. 430,000 vectors of 512 dimensions occupy about 440 MB. Multi-million
vector libraries, especially long videos, exceed the target; increase the
sampling interval or lower the frame cap.

The highest scoring pool is merged into video moments. Consecutive samples
within 1.5 sample intervals share a moment, anchored on the best frame. Clip
limits clamp or widen the interval within the video. Near-duplicate anchor
vectors are grouped at cosine similarity 0.95 by default. Sampling limits the
accuracy of all suggested clip boundaries.

A-roll audio becomes a temporary 16 kHz mono WAV. Local speech produces timed
segments, cached by file path, size, modification time, model, and language.
Default beat boundaries use consecutive segments fitting within ten-second
windows. Windows under four seconds remain visible but are skipped. The original
keyword rule keeps up to eight words, with alphabetical frequency ties. Need
scores incorporate concrete topics, questions, length, and alternating eligible
windows. `--segmenter pauses` enables pause, length, and text-similarity boundaries;
both segmenters use the same need scoring.
Untimed text uses estimated speaking rate internally but returns null times
unless a duration is supplied. Filler and production chatter are skipped.

The image model matches descriptions of what is visible. Spoken sentences are
often abstract, so automatic candidates can be weak. Run B-roll once, read the
beats, have the agent write two to four concrete visual descriptions for weak
beats, and run `broll --beats` again. Each row scores by its best visual query.
Recommended picks prefer a file not already recommended for an earlier beat.
Relevance guidance and beat segmentation are heuristics that need human review.

A-roll exclusions use device/inode identity plus file size and a bounded
SHA-256 content sample. Files up to 192 KiB are read entirely; larger files
use 64 KiB at the beginning, middle, and end. Matching samples are excluded
conservatively: they are evidence of a copy, not proof that unsampled bytes
match. Size/mtime checks before and after reading reject unstable files.
This content check applies to B-roll source protection only; incremental
indexing still uses size and modification time.

For videos, at most 12 evenly spread A-roll frames are embedded with the
index's image model. At most 12 stored candidate frames are compared, with
cosine similarity **at least 0.985** and **at least 80% coverage in both
directions** required for file exclusion. This detects visually similar
re-encodes independently of names, sizes, and container bytes. Such files
are reported as `aroll_near_duplicate`, never as proven byte copies. Sparse
sampling can miss changes and similar scenes can be false positives; review
on real footage is still needed. `--no-dedupe` does not disable A-roll
protection. `--keep-near-duplicates` disables only visual similarity exclusion. Unreadable identities and candidates changed since indexing are
omitted with `library_unreachable` and `index_stale` warnings respectively.

Candidate selection starts with an over-fetched score pool and doubles that
pool after exclusions, moment grouping, per-file limits, and duplicate removal
when too few results remain. Each expansion re-groups and re-ranks the pool,
with row number breaking score ties. Selection stops when the requested count
(including a search offset) survives or all filtered rows have been considered.
Excluded files are checked only once per ranking call. B-roll emits an
`insufficient_candidates` warning per active beat when fewer than requested
survive; skipped filler beats are not shortages. Score statistics still cover
the metadata-filtered rows before source checks and duplicate grouping.

Raw-frame search bypasses moment merging, per-file limits, and near-duplicate
folding. Its descending dot-product order can be compared against a prior index
using the same vectors. The float16 store can quantize values compared with an
older float32 index.

Before any video job is handed to a worker, its key and recovery metadata are
flushed to `inflight.jsonl`. Checkpoints retain only jobs still in flight. A new
writer records leftover jobs as `interrupted_decode`, then clears the journal.
These files retry automatically below three failures, always through ffmpeg.
Explicit `--retry-failed` can retry after that limit.
