from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave
from tests.legacy_stubs import load
from tests.support import Sandbox, make_video


class Transcribe(Sandbox):
    def test_audio_and_segments(self):
        module = load("transcribe")
        video = make_video(self.library / "voice.mp4", [("red", 2)], audio=True)
        audio = self.base / "audio.wav"
        module.extract_audio(str(video), audio)
        with wave.open(str(audio)) as handle:
            self.assertEqual((handle.getframerate(), handle.getnchannels()), (16000, 1))
        segment = SimpleNamespace(start=.12345, end=1.23456, text=" coffee ")
        blank = SimpleNamespace(start=1, end=2, text="  ")
        model = Mock()
        model.transcribe.return_value = ([segment, blank], SimpleNamespace(language="en"))
        constructor = Mock(return_value=model)
        modules = {"faster_whisper": SimpleNamespace(WhisperModel=constructor),
                   "ctranslate2": SimpleNamespace(get_cuda_device_count=lambda: 1)}
        with patch.dict("sys.modules", modules):
            backend = module.WhisperTranscriber(offline=True)
            values, language = backend.transcribe(audio)
            self.assertEqual(values, [{"id": 1, "start": .123, "end": 1.235, "text": "coffee"}])
        constructor.assert_called_once_with("base", device="cpu", device_index=0,
                                            compute_type="int8", local_files_only=True)
        model.transcribe.assert_called_once_with(str(audio), vad_filter=True, language=None)
