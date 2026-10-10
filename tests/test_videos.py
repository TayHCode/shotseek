import subprocess
from unittest.mock import Mock
import numpy as np
from tests.support import Sandbox, make_video
from shotseek.media.videos import sample_times, probe, video_info, load_video
from shotseek.media.ffmpeg import run
from shotseek.media import MediaError
from shotseek.config import DEFAULTS


class Videos(Sandbox):
    def test_sampling(self):
        for duration, count in ((.5, 1), (3, 1), (30, 6), (600, 60), (7200, 60)):
            times, step = sample_times(duration)
            self.assertEqual(len(times), count)
            self.assertEqual(times[0], round(min(2.5, duration / 2) * 1000))
            self.assertLess(times[-1], duration * 1000)

    def test_generated_video(self):
        path = make_video(self.library / "colors.mp4")
        info = video_info(probe(path))
        self.assertEqual((info["width"], info["height"]), (320, 240))
        self.assertAlmostEqual(info["duration"], 12, places=1)
        frames = load_video(path, DEFAULTS["indexing"])["frames"]
        self.assertEqual([np.asarray(x["image"]).mean(axis=(0, 1)).argmax() for x in frames], [0, 1])
        self.assertEqual([x["t_ms"] for x in frames], [2500, 7500])

    def test_failure_timeout(self):
        path = self.library / "bad.mp4"
        path.write_text("cafe")
        with self.assertRaises(MediaError) as error:
            probe(path)
        self.assertEqual(error.exception.reason, "probe_failed")
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("test", 1), (b"", b"")]
        with self.assertRaises(MediaError) as error:
            run(["test"], 1, popen=lambda *a, **k: process)
        self.assertEqual(error.exception.reason, "timeout")
        process.kill.assert_called_once()
