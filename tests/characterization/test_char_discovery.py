from tests.legacy_stubs import load
from tests.support import Sandbox


class Discovery(Sandbox):
    def test_recursion_caps_and_file_root(self):
        root2 = self.base / "second"
        root2.mkdir()
        paths = [self.library / "a.MP4", self.library / "nested" / "b.mov", root2 / "c.mkv"]
        for p in paths:
            p.parent.mkdir(exist_ok=True)
            p.touch()
        (self.library / "ignore.jpg").touch()
        discover = load("broll_library").discover_video_files
        self.assertEqual(set(discover([self.library, root2])), set(paths))
        self.assertEqual(len(discover([self.library, root2], max_videos=2)), 2)
        self.assertEqual(len(discover([self.library, root2], max_videos_per_root=1)), 2)
        self.assertEqual(discover([paths[0]]), [paths[0]])
