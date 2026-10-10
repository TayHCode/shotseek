# Output reference

Commands print one UTF-8 JSON document with a newline. The envelope contains
`schema_version`, `tool`, `tool_version`, `command`, `ok`, and `warnings`.
Failures add `error` with `code`, `message`, `hint`, and `exit_code`. Logs and
progress go to stderr. Both streams use UTF-8, including native Windows pipes;
consuming scripts should decode them explicitly as UTF-8. `--quiet` silences them; `--verbose` enables tracebacks
for unexpected errors. Global `--config`, `--index-dir`, `--quiet`, and
`--verbose` work before or after subcommands. Command-specific options such as
`--device` go after their subcommand.

Exceptions are help, version, `schema NAME` (raw schema), `agent-prompt`
(Markdown), and search/B-roll with CSV or text output. `--output FILE` writes
the chosen format and prints an envelope containing `output_path` and counts.
CSV files use UTF-8 with BOM. All output destinations must be outside libraries.

```sh
shotseek schema search
shotseek search "ceramic mug on a white background" --media photo --orientation square
shotseek search "boots on a trail" --media video --min-duration 2 --max-duration 60
shotseek search --queries-file /path/outside/library/queries.csv --format csv --output /path/outside/library/results.csv
```

Search accepts positional queries, repeated `--query`, CSV `query_id,query`
rows, plain text lines, or standard input with `--queries-file -`. `--like`
uses a stored item vector without a model. Defaults: 20 results, offset 0,
maximum 3 moments per file, clips 2–12 seconds, dedupe threshold 0.95. Filters
cover media type, libraries, folder prefixes, path substrings, orientation,
width, height, megapixels, duration, date, and excluded file or item IDs.
Dates use capture time if known, otherwise modification time. Blank frames
are excluded unless `--include-blank`. Zero results is success.

Results carry file and item IDs, library-relative and absolute paths,
`open_path`, dimensions, capture and modification times, size, thumbnail,
brightness and sharpness, score, relevance, and near-duplicate count. Videos
also carry `timestamp`, `start`, `end`, `timecode`, duration, and matched-frame
count; photo times are null. Scores have four decimals, relevance two, and
seconds at most three. Timecodes use `HH:MM:SS.mmm`. Item IDs combine a stable
file ID and video milliseconds. File IDs derive from library name and relative
path, never media contents.

B-roll accepts exactly one of A-roll, transcript, talking points, points file,
or edited beats. It returns source information, transcript, beats, score
statistics and candidates. `matched_query` explains each candidate;
`recommended` marks one per beat and `repeat` flags reused recommendations.
Defaults are video candidates, 5 per beat, one moment per file, and automatic 4–10 second windows. Transcribe returns source, transcript and beats without image search.

Malformed edited beats, JSON transcripts, and query CSVs return `usage` with
exit 2 and an explanation. Times must be finite numbers (never booleans),
nonnegative and ordered, or both null. Queries must be nonempty strings.
Beat IDs must be unique strings; segment IDs must be positive integers and
refer to the supplied transcript when present. JSON rejects duplicate keys
and nonfinite constants. CSV requires `query` and optionally `query_id`, with
one cell per declared column. A missing or unreadable media input, an invalid
text/cue transcript, or a valid transcript with no text still uses exit 7.

Search CSV columns, in order:

`query_id, query, rank, score, relevance, media_type, path, open_path, filename, folder, timestamp, start, end, timecode, duration, width, height, orientation, captured_at, thumbnail, item_id, library, review_status, notes`

B-roll CSV columns, in order:

`beat_id, beat_start, beat_end, beat_timecode, beat_text, matched_query, rank, recommended, score, relevance, media_type, path, open_path, filename, clip_start, clip_end, clip_timecode, duration, width, height, thumbnail, item_id, review_status, notes`

Review status and notes start empty. Text cells beginning with `=`, `+`, `-`,
or `@`, including after leading whitespace or control characters, gain a
leading single quote before the original cell contents. Absolute path and thumbnail columns are
unchanged. JSON schemas are draft 2020-12; use `schema` to list them. Invented
[search](examples/search.json) and [B-roll](examples/broll.json) outputs show
the complete contracts.

| Exit | Meaning |
| --- | --- |
| 0 | Success, including empty results and budgeted partial indexing |
| 1 | Unexpected internal error |
| 2 | Usage or configuration problem |
| 3 | Missing, empty, incompatible, or corrupt index |
| 4 | Unreachable or stalled storage; checkpoints preserved |
| 5 | Writer lock held by another process |
| 6 | Missing dependency, weights, or requested device |
| 7 | Invalid A-roll or transcript, or no speech |
| 8 | Strict indexing finished with failed files |
| 130 | Interrupted; completed work checkpointed |

Indexing continues past individual file failures and normally exits 0 with a
`files_failed` warning, `totals.failed`, and `failures_sample`. `--strict` makes
those failures exit 8; `--retry-failed --strict` retries previously failed files.
`too_small` means the photo was under the 512-byte input-size cutoff (including
an empty or short corrupt file); it does not measure image dimensions.
`decode_failed` means a larger input could not be decoded, while `read_error`
means the path could not be read. Inspect or replace the original input before
retrying. When the root itself becomes unavailable, discovered files that
could not be reached count in `totals.not_reached` and each library's
`not_reached`, not `failed` or `failures_sample`. The `files_not_reached` warning
says they were not reached because the folder became unavailable. They do not
create failed records or consume retry attempts; reconnect and rerun normally.
`status.last_run.not_reached` retains the count. Files never discovered cannot
be counted. Fatal storage/dependency errors retain the exit codes above.

Stable errors: `usage`, `config_missing`, `config_invalid`, `config_exists`,
`library_unknown`, `library_overlap`, `library_name_invalid`,
`index_inside_library`, `output_inside_library`, `index_dir_not_empty`,
`confirmation_required`, `unknown_id`, `index_not_found`, `index_empty`,
`index_model_mismatch`, `index_format_unsupported`, `index_corrupt`,
`library_unreachable`, `storage_stalled`, `index_locked`, `ffmpeg_missing`,
`dependency_missing`, `model_unavailable`, `device_unavailable`,
`aroll_not_found`, `aroll_no_audio`, `transcript_unparseable`,
`transcript_empty`, `no_speech_detected`, `files_failed`, `interrupted`, `internal`.

Warnings: `files_not_reached`, `index_incomplete`, `library_unreachable`, `prune_deferred`,
`query_truncated`, `config_model_differs`, `fake_embedder`,
`whisper_cuda_unavailable`, `heic_support_missing`, `thumbnails_disabled`,
`aroll_excluded`, `times_estimated`.

Every command uses `schema_version: 1`. B-roll also carries a `revision` identifier. Keep `revision`, `source`, beat IDs, and segment IDs
when editing saved JSON. Revision records live under `index/broll/` and contain
private transcript/result metadata. Candidate objects supplied in a beats file
are never trusted as cached results. Only local computed records can be reused.

On `--beats`, array order controls the output and recommendations. Keep an
existing beat ID when editing it; remove its row to remove it. New rows without
IDs receive stable IDs on their first output. Unchanged beats reuse candidates
and score statistics when the index snapshot, search options, source identity,
and beat inputs agree. Edited beats are searched again. Changes to the index,
filters, per-beat count, clip rules, or filler option invalidate reuse. Selection
flags are recalculated in order on every run so removed or reordered beats
cannot leave stale recommendations. Pass the desired search options again;
only saved explicit exclusions are inherited automatically.

When only linked transcript segments change, their text/times flow into the
unedited beat without changing its ID. Removing all its segments drops that
beat. New unassigned segments are appended in transcript order. Explicit edits
to a beat's text/times take priority; editing its segment links requires those
links to exist. Removing a beat does not re-add its old segments. If local
revision history is missing, a warning explains that supplied beats are
authoritative and every result is recomputed. This preserves portable input
without guessing which of two conflicting edits was intended.

The original A-roll path is retained through every saved-beats rerun and is
checked again for identity, copied content, and near-duplicates. A missing
source retains saved excluded file IDs and reports a warning. A changed source or edited source metadata for a known
revision requires a fresh `--aroll` run. This keeps its transcript tied to the
correct source. Source-protection warnings still apply on cached reruns.

All supplied transcript/beat timestamps and duration/clip/beat options are
limited to **0 through 10,000,000 seconds**, with positive durations where
required. The bound keeps millisecond formatting, interval arithmetic, and
stored timestamps representable. NaN, infinities, booleans, and larger finite
values return `usage`, exit 2, at the input boundary before model work.

Query provenance survives roundtrips. `topic`, `sentence`, `keywords`, and `point`
queries are automatic and are rebuilt from current beat text; they never
activate filler by themselves. `visual_queries`, `source: "agent"`, and
source-less query objects are explicit overrides. With an available revision,
editing a generated query's text promotes that query to `agent`. Without that
history, mark the edit explicitly using `visual_queries` or `source: "agent"`.
Explicit queries take priority over any remaining automatic queries. The
`--include-filler` option applies to that invocation only.

Every beat includes `need_score`, `need_reasons`, `topic` (or null),
`suggested_broll`, `search_terms`, and `placement: {start, end}`. The suggested
placement lasts the chunk length clamped to 3–6 seconds. Skip reasons are
`too_short`, `filler`, `low_need`, or `over_limit`. Points and agent queries
are always active. Default automatic queries are topic terms, a keyword photo
query, and the first 50 words of the sentence, scored separately.

`--segmenter windows|pauses`, `--min-need` (default 0.45), and `--max-beats`
(default 12, 0 unlimited) apply to B-roll and transcription. `search --raw-frames`
keeps top individual frames instead of moments. Review status and notes remain
editable empty cells. Saved A-roll sources also carry `size`, `content_sample`,
and `excluded_file_ids`; unavailable source paths keep those exclusions active.
