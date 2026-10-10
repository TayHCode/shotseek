"""Local speech backend with explicit device resolution."""
import sys
from ..embed.openclip import dependency, offline_mode
from ..errors import AppError, warning


def extract_audio(video_path, audio_path, timeout=120):
    from pathlib import Path
    from ..media.ffmpeg import LOCAL_INPUT, run
    path = Path(audio_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         *LOCAL_INPUT, "-i", str(video_path), "-vn", "-acodec",
         "pcm_s16le", "-ar", "16000", "-ac", "1", str(path)], timeout)


class WhisperTranscriber:
    def __init__(self, model="base", device="cpu", offline=False):
        offline = offline_mode(offline)
        whisper = dependency("faster_whisper")
        self.warnings = []
        self.device = device
        index = 0
        if device == "auto" or device.startswith("cuda"):
            translate = dependency("ctranslate2")
            count = translate.get_cuda_device_count()
            if device == "auto":
                device = "cuda" if count else "cpu"
            if device.startswith("cuda"):
                index = int(device.split(":")[1]) if ":" in device else 0
                if index >= count:
                    raise AppError("device_unavailable",
                        "The requested speech device is unavailable.", "Use --device cpu.", 6)
                device = "cuda"
        if device not in {"cpu", "cuda"}:
            raise AppError("device_unavailable", "Local speech supports CPU and CUDA devices.",
                "Use --device cpu for speech.", 6)
        if not offline:
            print("Loading speech model " + model + "; missing weights will be downloaded once.",
                file=sys.stderr)
        try:
            self.model = whisper.WhisperModel(model, device=device, device_index=index,
                compute_type="int8" if device == "cpu" else "float16", local_files_only=offline)
        except Exception:
            if device != "cuda":
                raise AppError("model_unavailable", "Speech model weights could not be loaded.",
                    "Check cached weights or allow the first download.", 6) from None
            try:
                self.model = whisper.WhisperModel(model, device="cpu", compute_type="int8",
                    local_files_only=offline)
                self.warnings.append(warning("whisper_cuda_unavailable",
                    "Speech could not initialize on CUDA; using CPU."))
                device = "cpu"
            except Exception:
                raise AppError("model_unavailable",
                    "The speech model could not be loaded on CUDA or CPU.", exit_code=6) from None
        self.device = device

    def transcribe(self, path, language=None):
        try:
            segments, info = self.model.transcribe(str(path), vad_filter=True, language=language or None)
            result = [dict(id=i + 1, start=round(s.start, 3), end=round(s.end, 3),
                text=s.text.strip()) for i, s in enumerate(segments) if s.text.strip()]
            return result, info.language
        except Exception:
            raise AppError("transcript_unparseable", "Local speech decoding failed.",
                exit_code=7) from None
