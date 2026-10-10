import contextlib
import io
import json
import subprocess
import sys
from unittest.mock import patch
from tests.support import Sandbox
from shotseek.cli import main
from shotseek.names import NAME


class Contract(Sandbox):
    def test_help_version(self):
        for option in ("--help", "--version"):
            result = subprocess.run([sys.executable, "-m", NAME, option], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(NAME, result.stdout)

    def test_old_python_has_friendly_error_before_dependencies(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("shotseek.cli.sys.version_info", (3, 9, 6)), patch("shotseek.cli.dispatch") as dispatch, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["doctor"])
        dispatch.assert_not_called()
        doc = json.loads(out.getvalue())
        self.assertEqual(code, 6)
        self.assertIn("Python 3.11", doc["error"]["message"])
        self.assertIn("uv venv --python 3.12", doc["error"]["hint"])

    def test_usage(self):
        code, doc, err = self.cli("--invalid")
        self.assertEqual(code, 2)
        self.assertEqual(doc["error"]["code"], "usage")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["schema_version"], 1)

    def test_library_add_suggests_positional_syntax(self):
        code, doc, _ = self.cli("library", "add", "empty=/path/to/media")
        self.assertEqual(code, 2)
        self.assertIn("library add NAME PATH", doc["error"]["hint"])

    def test_internal(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("shotseek.cli.dispatch", side_effect=RuntimeError("private detail")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["status"]), 1)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "internal")
        self.assertNotIn("private detail", out.getvalue() + err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_reported_failure_goes_to_stderr_and_quiet_hides_it(self):
        from shotseek.errors import AppError
        for flags in ([], ["--quiet"]):
            out, err = io.StringIO(), io.StringIO()
            payload = dict(_exit=4, ok=False, error=AppError("storage_stalled", "Storage stopped.", exit_code=4).as_dict())
            with patch("shotseek.cli.dispatch", return_value=payload), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(["index", *flags]), 4)
            self.assertEqual(bool(err.getvalue()), not flags)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "storage_stalled")

    def test_documented_exit_codes(self):
        from shotseek.store.db import Store
        self.assertEqual(self.cli("init", "--library", "media=" + str(self.library))[0], 0)
        code, result, _ = self.cli("search", "red")
        self.assertEqual((code, result["error"]["code"]), (3, "index_not_found"))
        (self.library / "broken.jpg").touch()
        code, result, _ = self.cli("index", "--strict")
        self.assertEqual((code, result["error"]["code"]), (8, "files_failed"))
        with Store(self.index, write=True):
            code, result, _ = self.cli("index")
            self.assertEqual((code, result["error"]["code"]), (5, "index_locked"))
        code, result, _ = self.cli("transcribe", self.base / "missing.mp4")
        self.assertEqual((code, result["error"]["code"]), (7, "aroll_not_found"))
        self.env["PATH"] = str(self.base / "no-tools")
        code, result, _ = self.cli("index")
        self.assertEqual((code, result["error"]["code"]), (6, "ffmpeg_missing"))
        self.env.pop("PATH")
        self.library.rename(self.base / "unmounted")
        code, result, _ = self.cli("index")
        self.assertEqual((code, result["error"]["code"]), (4, "library_unreachable"))


class Utf8Output(Sandbox):
    def test_success_and_failure_with_legacy_pipe_encoding(self):
        from shotseek.errors import AppError
        for raw in (False, True):
            for failure in (False, True):
                buffer = io.BytesIO()
                out = io.TextIOWrapper(buffer, encoding="cp1252")
                err_buffer = io.BytesIO()
                err = io.TextIOWrapper(err_buffer, encoding="cp1252")
                words = "caf\u00e9 \u2615"
                options = dict(side_effect=AppError("usage", words)) if failure else dict(
                    return_value={"_raw": words} if raw else {"path": words})
                with patch("shotseek.cli.dispatch", **options), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(main(["status"]), 2 if failure else 0)
                    out.flush()
                    text = buffer.getvalue().decode("utf-8")
                    self.assertIn(words, text)
                    if not raw or failure:
                        doc = json.loads(text)
                        self.assertEqual(doc["ok"], not failure)
                    if failure:
                        err.flush()
                        self.assertIn(words, err_buffer.getvalue().decode("utf-8"))
                out.close()
                err.close()
