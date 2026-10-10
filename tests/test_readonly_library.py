import json
from tests.test_indexer import IndexCase
from tests.support import make_library, make_video, tree_manifest


class ReadOnly(IndexCase):
    def test_index_never_writes_library(self):
        make_library(self.library)
        make_video(self.library / "aroll.mp4", audio=True)
        from shotseek.names import env
        fixture = self.base / "speech.json"
        fixture.write_text(json.dumps([dict(start=0, end=6, text="Coffee and pastry at the cafe.")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        before = tree_manifest(self.library)
        entries = [self.library, *self.library.rglob("*")]
        def restore():
            for path in entries:
                path.chmod(0o700 if path.is_dir() else 0o600)
        self.addCleanup(restore)
        for path in entries:
            path.chmod(0o500 if path.is_dir() else 0o400)
        self.assertTrue(self.index_run()["index"]["searchable"])
        self.assertEqual(self.cli("search", "red")[0], 0)
        self.assertEqual(self.cli("broll", "--aroll", self.library / "aroll.mp4")[0], 0)
        self.assertEqual(before, tree_manifest(self.library))
