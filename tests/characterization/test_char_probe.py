import subprocess
from tests.legacy_stubs import load
from tests.support import Sandbox, make_video


class Probe(Sandbox):
    def test_fields(self):
        path = make_video(self.library / "colors.mp4")
        result = load("broll_library").probe_video(path)
        self.assertEqual(set(result), {"path", "filename", "folder", "duration", "size",
                                       "width", "height", "frame_rate"})
        self.assertEqual((result["width"], result["height"], result["duration"]), (320, 240, 12))
        self.assertEqual(result["frame_rate"], "10/1")
        self.assertEqual(result["size"], path.stat().st_size)

    def test_bad_and_audio_only(self):
        path = self.library / "broken.mp4"
        path.write_text("invalid video")
        probe = load("broll_library").probe_video
        self.assertIsNone(probe(path))
        audio = self.library / "audio.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "sine=duration=1", "-c:a", "aac", str(audio)],
                       check=True, capture_output=True)
        self.assertIsNone(probe(audio))
