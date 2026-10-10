import copy
import os
import tomllib
from unittest.mock import patch
from tests.support import Sandbox
from shotseek import config
from shotseek.errors import AppError
from shotseek.names import env


class Config(Sandbox):
    def test_defaults_roundtrip(self):
        data = config.validate({})
        self.assertEqual(data["model"]["device"], "cpu")
        self.assertEqual(data["indexing"]["workers"], 0)
        for root in [str(self.library), str(self.base / 'café "mug"'), str(self.base / 'a\\b')]:
            data["library"] = [dict(name="media", root=root, display_root="G:\\My Drive\\Media", exclude=["*/skip*"])]
            self.assertEqual(config.validate(tomllib.loads(config.dumps(data))), config.validate(data))

    def test_reject_values(self):
        for value in ({"odd": 1}, {"model": {"odd": 1}}, {"indexing": {"workers": -1}}, {"config_version": True}, {"index": {"thumbnails": 1}}):
            with self.assertRaises(AppError) as error:
                config.validate(value)
            self.assertEqual(error.exception.code, "config_invalid")
        for name in ("UPPER", "", "x" * 33):
            with self.assertRaises(AppError) as error:
                config.validate({"library": [dict(name=name, root=str(self.library))]})
            self.assertEqual(error.exception.code, "library_name_invalid")
        with self.assertRaises(AppError) as error:
            config.validate({"library": [dict(name="one", root=str(self.library)), dict(name="two", root=str(self.library / "sub"))]})
        self.assertEqual(error.exception.code, "library_overlap")

    def test_cli_library(self):
        code, doc, _ = self.cli("init", "--library", "media=" + str(self.library))
        self.assertEqual(code, 0, doc)
        self.assertEqual(self.cli("init", "--library", "media=" + str(self.library))[1]["error"]["code"], "config_exists")
        extra = self.base / "more"
        extra.mkdir()
        self.assertEqual(self.cli("library", "add", "extra", extra)[0], 0)
        self.assertEqual(len(self.cli("library", "list")[1]["libraries"]), 2)
        self.assertEqual(self.cli("library", "remove", "extra")[0], 0)
        self.assertEqual(len(self.cli("library", "list")[1]["libraries"]), 1)
        self.assertEqual(self.cli("library", "remove", "missing")[1]["error"]["code"], "library_unknown")

    def test_existing_init_preserves_config_and_guides_add(self):
        self.assertEqual(self.cli("init", "--library", "media=" + str(self.library))[0], 0)
        data = tomllib.loads(self.config.read_text())
        data["indexing"]["workers"] = 3
        config.write(self.config, data)
        before = self.config.read_bytes()
        extra = self.base / "second folder"
        extra.mkdir()
        code, doc, _ = self.cli("init", "--library", "extra=" + str(extra))
        self.assertEqual(code, 2)
        self.assertEqual(doc["error"]["code"], "config_exists")
        self.assertIn("shotseek library add NAME PATH", doc["error"]["hint"])
        self.assertIn("replaces the whole config", doc["error"]["hint"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.cli("library", "add", "extra", extra)[0], 0)
        updated = tomllib.loads(self.config.read_text())
        self.assertEqual([entry["name"] for entry in updated["library"]], ["media", "extra"])
        self.assertEqual(updated["indexing"]["workers"], 3)
        self.assertEqual(self.cli("init", "--library", "extra=" + str(extra), "--force")[0], 0)
        replaced = tomllib.loads(self.config.read_text())
        self.assertEqual([entry["name"] for entry in replaced["library"]], ["extra"])
        self.assertNotEqual(replaced["indexing"]["workers"], 3)

    def test_precedence_and_global_options(self):
        data = copy.deepcopy(config.DEFAULTS)
        data["model"]["device"] = "mps"
        with patch.dict(os.environ, {env("DEVICE"): "cuda"}):
            self.assertEqual(config.device(data, "cpu"), "cpu")
            self.assertEqual(config.device(data), "cuda")
        self.cli("--config", self.config, "init", "--library", "media=" + str(self.library))
        self.assertEqual(self.cli("--config", self.config, "library", "list")[0], 0)
        self.assertEqual(self.cli("library", "list", "--config", self.config)[0], 0)


class MediaSettings(Sandbox):
    def test_reader_sampling_and_base(self):
        from shotseek.config import validate
        from shotseek.errors import AppError
        data = validate({})
        self.assertEqual(data["indexing"]["frame_reader"], "auto")
        self.assertEqual(data["transcribe"]["model"], "base")
        for field_name in ("frame_reader", "video_sampling"):
            with self.assertRaises(AppError) as raised:
                validate({"indexing": {field_name: "invalid"}})
            self.assertEqual(raised.exception.code, "config_invalid")

    def test_root_deadline(self):
        import time
        from unittest.mock import patch
        from shotseek.config import root_reachable
        started = time.monotonic()
        with patch("pathlib.Path.is_dir", side_effect=lambda: time.sleep(1)):
            self.assertFalse(root_reachable(self.library))
        self.assertLess(time.monotonic() - started, .6)
