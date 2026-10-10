from typing import Protocol
import hashlib
import json
import os
from pathlib import Path as Path
import tempfile
from .. import config
from ..beats import split, validate_limits
from ..errors import AppError
from ..media import MediaError
from ..media.ffmpeg import require, run as run
from ..media.videos import probe
from ..names import env
from ..paths import absolute, atomic_write, ensure_index, writable
from .parse import segments


class Transcriber(Protocol):
    def transcribe(self, path, language=None): ...


def get_transcriber(model, device, offline=False):
    selected = os.environ.get(env("TRANSCRIBER"), "")
    if selected.startswith("fake:"):
        from .fake import FakeTranscriber
        return FakeTranscriber(selected[5:])
    from .whisper import WhisperTranscriber
    return WhisperTranscriber(model, device, offline)


def transcribe_file(path, data, index, args):
    path = absolute(path)
    if not path.is_file():
        raise AppError("aroll_not_found", "The A-roll file does not exist.", exit_code=7)
    require()
    try:
        info = probe(path)
    except MediaError:
        raise AppError("transcript_unparseable", "The A-roll cannot be probed.", exit_code=7) from None
    if not any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
        raise AppError("aroll_no_audio", "The A-roll has no audio stream.",
            "Choose a video with speech, or use --transcript or --point instead.", 7)
    duration = float(info.get("format", {}).get("duration", 0))
    model = args.whisper_model or data["transcribe"]["model"]
    language = args.language if args.language is not None else data["transcribe"]["language"]
    stat = path.stat()
    key = hashlib.sha1(json.dumps([str(path), stat.st_size, stat.st_mtime_ns, model,
        language]).encode()).hexdigest()
    ensure_index(index, data["library"])
    cache = writable(index / "transcripts" / (key + ".json"), data["library"])
    cached = cache.exists() and not getattr(args, "no_transcript_cache", False)
    warnings = []
    if cached:
        try:
            stored = json.loads(cache.read_text())
            values, detected = segments(stored), stored.get("language", language)
        except (OSError, ValueError, TypeError):
            cached = False
    if not cached:
        temporary = writable(index / "tmp", data["library"])
        temporary.mkdir(parents=True, exist_ok=True)
        for leftover in temporary.glob("*.wav"):
            ensure_index(index, data["library"], create=False)
            writable(leftover, data["library"]).unlink()
        fd, name = tempfile.mkstemp(suffix=".wav", dir=temporary)
        os.close(fd)
        audio = writable(name, data["library"])
        try:
            from .whisper import extract_audio
            extract_audio(path, audio, max(120, duration))
            backend = get_transcriber(model, config.device(data, args.device, speech=True), args.offline)
            values, detected = backend.transcribe(audio, language or None)
            values = segments(values)
            warnings.extend(getattr(backend, "warnings", []))
        except MediaError:
            raise AppError("transcript_unparseable", "Audio extraction failed.", exit_code=7) from None
        except ValueError:
            raise AppError("transcript_unparseable", "Transcription returned invalid segments.",
                exit_code=7) from None
        finally:
            ensure_index(index, data["library"], create=False)
            writable(audio, data["library"]).unlink(missing_ok=True)
        if values:
            atomic_write(cache, json.dumps(dict(segments=values, language=detected)), data["library"])
    if not values:
        raise AppError("no_speech_detected", "No speech was detected in the A-roll.", exit_code=7)
    return dict(kind="aroll", path=str(path), duration=duration, language=detected,
        whisper_model=model, transcript_cached=cached), dict(timed=True, segments=values), warnings


def public_transcript(transcript):
    return dict(timed=transcript["timed"], segments=[{key: value for key,
        value in row.items() if not key.startswith("_")} for row in transcript["segments"]])


def save(args, data, source, transcript, beats):
    if args.save_transcript:
        from ..cli import envelope
        document = envelope("transcribe")
        document.update(source=source, transcript=public_transcript(transcript), beats=[{k: v for k,
            v in beat.items() if k not in {"candidates", "score_stats"}} for beat in beats])
        atomic_write(args.save_transcript, json.dumps(document, ensure_ascii=False,
            indent=2) + "\n", data["library"])


def command(args):
    validate_limits(args.min_beat_seconds, args.max_beat_seconds)
    data, path, index = config.load(args, optional=True)
    if args.save_transcript:
        writable(args.save_transcript, data["library"])
    source, transcript, warnings = transcribe_file(args.file, data, index, args)
    beats = split(transcript, args.min_beat_seconds, args.max_beat_seconds,
                  segmenter=args.segmenter, min_need=args.min_need, max_beats=args.max_beats)
    save(args, data, source, transcript, beats)
    return dict(source=source, transcript=public_transcript(transcript), beats=beats, warnings=warnings)
