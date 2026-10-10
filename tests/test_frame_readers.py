import os
import socket
from unittest.mock import patch
import numpy as np
from shotseek.config import DEFAULTS
from shotseek.media import MediaError
from shotseek.media.videos import frame, load_video, require_container
from tests.support import Sandbox, make_video


class Readers(Sandbox):
    def test_fallback_and_prefit(self):
        path = make_video(self.library / "large.mp4", [("red", 6)], size="960x540")
        for reader in ("auto", "opencv", "ffmpeg"):
            image = frame(path, 2000, reader=reader)
            self.assertLessEqual(max(image.size), 448)
            self.assertEqual(int(np.asarray(image).mean(axis=(0, 1)).argmax()), 0)
        with patch("shotseek.media.videos.extract_frame", return_value=None):
            self.assertIsNotNone(frame(path, 2000))
        with patch("shotseek.media.videos.extract_frame", side_effect=RuntimeError):
            self.assertIsNotNone(frame(path, 2000))
        self.assertIn("file", os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"])

    def test_playlist_cannot_connect(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(.1)
            path = self.library / "playlist.mp4"
            url = "http" + "://127.0.0.1:" + str(listener.getsockname()[1]) + "/clip.ts"
            path.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:8\n#EXTINF:8,\n" + url + "\n")
            with patch("shotseek.media.videos.extract_frame") as reader:
                with self.assertRaises(MediaError):
                    load_video(path, DEFAULTS["indexing"])
                reader.assert_not_called()
            with self.assertRaises(TimeoutError):
                listener.accept()

    def test_container_allowlist(self):
        for name in ("mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm", "avi", "mpegts", "mpeg", "asf"):
            require_container({"format": {"format_name": name}})
        with self.assertRaises(MediaError) as raised:
            require_container({"format": {"format_name": "hls"}})
        self.assertEqual(raised.exception.reason, "unsupported_container")
