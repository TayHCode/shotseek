# Storage

Keep the index on a local disk, outside every library. Libraries are plain
paths such as `/path/to/media`, `/mnt/nas/media`, or `G:\My Drive\Media`.
Mounted Google Drive, SMB, and NFS folders are read through the operating
system; there are no cloud APIs. Live NFS 4.1 on Linux, a personal macOS Drive
File Provider folder, and a personal native Windows Drive virtual mount were
checked with small generated libraries and local indexes. The earlier read-only
SSHFS check used two bundled OS icons. Live SMB reads, index/search, retries,
and alias guards passed on macOS, Linux GVfs/gio, and Windows drive-letter/UNC
paths. Removing only the generated scratch share tested real read failures and
recovery. Cold Drive placeholders, mirrored Drive mode, offline guarantees,
completed cloud synchronization, physical network partitions, packet-level
throttling, password-policy expiry, and large libraries remain untested. The earlier Drive-shaped local-folder test
only established spaces and Unicode support. See the README coverage table and
[network drives and cloud mounts](platforms.md#network-drives-and-cloud-mounts)
for exact OS coverage, recommended setup, and test qualifications.

Mounted cloud folders download files as they are read. The initial pass is
limited by download speed and grows the cloud client's cache. Later passes
read no unchanged media. Change detection uses size and modification time,
never a media hash. For unstable mount timestamps, set
`change_detection = "size"` under `[indexing]`, accepting that same-size edits
will be missed. The default size/mtime mode also ignores mtime differences of
two seconds or less. Rebuild deliberately when these limits could hide edits.

If a mount drops or stalls, completed checkpoints stay searchable. Reconnect
and repeat indexing after exit 4. Any unavailable selected root makes the run
exit 4, including one missing folder alongside healthy folders. Roots are
checked again after decoding, with at most five seconds per root; a folder that
vanishes or becomes unreadable prevents completion and pruning. Search warns
when a root cannot be confirmed readable: saved paths may be unavailable until
it reconnects. Discovered files not reached because the folder became unavailable
are counted separately as `not_reached`, with a `files_not_reached` warning.
They are not failed/read_error records; earlier searchable rows and retry
counts are preserved. Reconnect and rerun normally without `--retry-failed`.
Files the walk never discovered cannot be counted. A directory listing error under a reachable
root also exits 4 with `library_unreachable`, even if no media was discovered;
an incomplete walk must not report a successful completed run. Completed rows
are retained, and pruning is skipped. A few bad files are recorded and skipped.
The daemon worker pool replaces timed-out workers; eight lost workers or five
consecutive timeouts abort the run. An incomplete directory walk never prunes.
If more than 100 files and more than half a library disappear, pruning is
deferred until `--prune-missing` explicitly confirms it. `--no-prune` disables
removal. Use `--retry-failed` after repairing corrupt inputs.

An unchanged re-index of an existing index loads no image model and reads no
media. A retry of a failed file with no searchable rows counts as `new`; a
previously successful file with changed metadata counts as `changed`.

Filesystem errors while opening or reading a photo under a reachable root are
`read_error`, including
stale handles, I/O failures, timeouts, and permission denial. They retry
automatically for up to three failed attempts; `--retry-failed` overrides that
limit. Decoder failures remain separate. File and directory symlinks are skipped
by default. With `follow_symlinks = true`, a provider's missing inode number
does not collapse distinct folders or identify every B-roll candidate as A-roll.

Move a library by changing only its `root` in the config. Paths stored in the
index are relative. Set `display_root` to the path an editor sees on another
machine; `open_path` then uses that prefix, including backslashes where needed.
Root folders may not overlap. The index also cannot contain a library, so a
rebuild can never remove a nested media folder. Config, index, transcript exports, and search
outputs must all remain outside every configured library, including symlinks
and case aliases on mounted providers. Output writes fail if alias verification
cannot complete; use the original spelling and retry after storage recovers.

```sh
shotseek index --time-budget 300
shotseek status
shotseek library list
```

Config selection is flag, `SHOTSEEK_CONFIG`, then the XDG config default.
Index selection is flag, `SHOTSEEK_INDEX_DIR`, config, then the XDG data default.
Native Windows uses APPDATA and LOCALAPPDATA; macOS follows XDG conventions.
Device selection is flag, `SHOTSEEK_DEVICE`, config, then CPU. Search and B-roll
use CPU by default even if the index was built on a GPU.

A filename that cannot be represented as UTF-8 is skipped with `path_not_utf8`.
A size or nanosecond modification time outside the database's signed 64-bit
range is skipped with `metadata_out_of_range`. Neither reaches media decoding
or a database checkpoint. The run summary counts these as failures; `--strict`
exits 8. Unrepresentable filename bytes appear as escaped code points in the
failure sample so the JSON remains valid UTF-8. These entries are reported once
per pass until corrected; they do not block other files or trigger a retry loop.
Their metadata cannot be stored as a normal file row, so inspect the index run's
failure sample and `status.last_run.failed`. A previously indexed version is
retained when its new metadata is out of range; its search result stays stale
until the metadata is corrected and indexing is repeated.

`status` allows 0.25 seconds to confirm each library root. If a root check
stalls or fails, it reports `reachable: false` with `library_unreachable` and
still returns local index counts. This means reachability was not confirmed,
not that the drive is necessarily absent. All status work, including path
resolution, database reads and index-size inspection, has a two-second deadline.
If that deadline expires, the command returns `storage_stalled` with exit 4.
Slow filesystem calls run in daemon threads and cannot keep the command alive.

B-roll candidate identity checks share a five-second identity budget
across the entire command, including all beats and pool expansions. Each stat
or bounded content read waits at most one second (or the remaining budget).
After a timeout, that library is not probed again during the command; other
libraries may use the remaining budget. Unchecked candidates fail closed with
a `library_unreachable` warning. Slow but healthy libraries can therefore
return fewer results. The budget spans source checks and candidate checks; speech, initial image-model
loading, and local index reads are separate. Daemon probes
cannot cancel a stalled kernel operation, but do not delay process exit.

Video jobs are journaled before decoding. A hard process exit leaves their keys
for the next writer, which records `interrupted_decode` and forces ffmpeg for
retry. Three repeated failures stop automatic retries. No file is pruned during
a run stopped by either file cap, a time budget, or an incomplete walk.

Library add/list/init reachability checks use a 0.25-second bound as well.
