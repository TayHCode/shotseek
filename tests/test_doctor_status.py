import os
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS
from tests.test_indexer import IndexCase
from tests.support import make_image
from shotseek.cli import build_parser
from shotseek.doctor import inspect, bounded_probe


class Diagnostics(IndexCase):
    def test_status_transitions(self):
        self.assertFalse(self.cli("status")[1]["index"]["exists"])
        for i in range(3):
            make_image(self.library / f"mug{i}.jpg", "red")
        self.index_run("--max-files", "1")
        self.assertEqual(self.cli("status")[1]["last_run"]["status"], "partial")
        self.index_run()
        result = self.cli("status")[1]
        self.assertEqual(result["last_run"]["status"], "complete")
        self.assertEqual(result["libraries"][0]["files"]["photos"], 3)

    def test_doctor_probes(self):
        torch = NS(__version__="0", version=NS(cuda=None), cuda=NS(is_available=lambda: False), backends=NS(mps=NS(is_available=lambda: False)), zeros=lambda shape: None, ones=lambda n: None)
        def imports(name):
            return torch if name == "torch" else NS(__version__="0", get_cuda_device_count=lambda: 0, ops=NS(nms=lambda *a: None))
        args = build_parser().parse_args(["doctor"])
        good = inspect(args, imports=imports, which=lambda n: n, roots=lambda p: True)
        self.assertEqual(good["_exit"], 0)
        self.assertEqual(good["summary"]["fail"], 0)
        def incompatible(name):
            if name == "torchvision":
                raise RuntimeError("operator torchvision::nms does not exist")
            return imports(name)
        broken = inspect(args, imports=incompatible, which=lambda n: n, roots=lambda p: True)
        self.assertEqual(broken["_exit"], 6)
        check = next(c for c in broken["checks"] if c["id"] == "torchvision")
        self.assertEqual(check["status"], "fail")
        self.assertIn("torch and torchvision together", check["hint"])
        def missing(name):
            raise ImportError()
        bad = inspect(args, imports=missing, which=lambda n: None, roots=lambda p: False)
        self.assertEqual(bad["_exit"], 6)
        self.assertEqual(next(c for c in bad["checks"] if c["id"] == "heic")["status"], "warn")
        self.config.unlink()
        absent = inspect(args, imports=imports, which=lambda n: n, roots=lambda p: True)
        self.assertEqual(next(c for c in absent["checks"] if c["id"] == "config")["status"], "warn")
        self.config.write_text("bad = 1")
        invalid = inspect(args, imports=imports, which=lambda n: n, roots=lambda p: True)
        self.assertEqual(next(c for c in invalid["checks"] if c["id"] == "config")["status"], "fail")

    def test_bounded_probe(self):
        import threading
        event = threading.Event()
        self.addCleanup(event.set)
        self.assertEqual(bounded_probe(lambda: event.wait(), .01), (False, None))


def _imports(name):
    torch = NS(__version__="0", version=NS(cuda=None), cuda=NS(is_available=lambda: False),
        backends=NS(mps=NS(is_available=lambda: False)), zeros=lambda shape: None, ones=lambda n: None)
    return torch if name == "torch" else NS(__version__="0", get_cuda_device_count=lambda: 0,
        ops=NS(nms=lambda *a: None))


STUBS = dict(imports=_imports, which=lambda n: n, roots=lambda p: True)


class PlatformReport(IndexCase):
    def test_native_dependency_failure_has_guidance_in_json_and_report(self):
        from shotseek.doctor import command

        def imports(name):
            if name in {"torch", "torchvision", "open_clip", "faster_whisper"}:
                raise OSError("DLL load failed")
            return _imports(name)

        for mode in ([], ["--report"]):
            args = build_parser().parse_args(["doctor", "--offline", *mode])
            result = command(args, imports=imports, which=lambda n: n, roots=lambda p: True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["_exit"], 6)
            for name in ("torch", "torchvision", "open_clip", "faster_whisper"):
                check = next(c for c in result["checks"] if c["id"] == name)
                self.assertEqual(check["status"], "fail")
                self.assertIn("Visual C++", check["hint"])
                if mode:
                    self.assertIn(check["hint"], result["_raw"])

    def test_sample_uses_configured_image_device(self):
        import json
        from shotseek.config import write
        from shotseek.doctor import smoke_test
        self.data["model"]["device"] = "mps"
        write(self.config, self.data)
        reply = NS(returncode=0, stdout=json.dumps(dict(ok=True,
            queries=[dict(results=[dict(path="red.jpg")])])), stderr="")
        args = build_parser().parse_args(["doctor", "--report"])
        with patch("shotseek.doctor.subprocess.run", return_value=reply) as run:
            self.assertTrue(smoke_test(args)[0])
        for call in run.call_args_list[1:]:
            words = call.args[0]
            self.assertEqual(words[words.index("--device") + 1], "mps")

    def test_report_text_and_smoke(self):
        from shotseek.doctor import command
        args = build_parser().parse_args(["doctor", "--report", "--offline"])
        with patch.dict(os.environ, {"SHOTSEEK_EMBEDDER": "fake"}):
            result = command(args, **STUBS)
        text = result["_raw"]
        for label in ("shotseek platform report", "OS: ", "Python: ", "CPU: ", "Accelerator: ",
                "ffmpeg: ", "ffprobe: ", "Model cache: ", "Sample index and search (3 files): PASS"):
            self.assertIn(label, text)
        self.assertNotIn(str(self.base), text)
        self.assertNotIn(str(self.library), text)

    def test_unavailable_device_agrees_in_json_and_report(self):
        from shotseek.doctor import command
        for selected in ("cuda", "cuda:8", "mps"):
            results = []
            for mode in ([], ["--report"]):
                args = build_parser().parse_args(["doctor", "--device", selected, *mode])
                with patch("shotseek.doctor.smoke_test") as sample:
                    result = command(args, **STUBS)
                sample.assert_not_called()
                self.assertFalse(result["ok"])
                self.assertEqual(result["_exit"], 6)
                check = next(c for c in result["checks"] if c["id"] == "device")
                self.assertEqual(check["status"], "fail")
                self.assertIn(selected, check["detail"])
                self.assertIn("--device cpu", check["hint"])
                if mode:
                    self.assertIn(check["detail"], result["_raw"])
                    self.assertIn(check["hint"], result["_raw"])
                results.append(check)
            self.assertEqual(*results)
        for selected in ("cpu", "auto"):
            result = command(build_parser().parse_args(["doctor", "--device", selected]), **STUBS)
            self.assertEqual(result["_exit"], 0)
            self.assertEqual(next(c for c in result["checks"] if c["id"] == "device")["status"], "ok")

    def test_report_masks_home_and_fails_on_smoke_failure(self):
        from shotseek.doctor import command, tilde
        self.assertEqual(tilde(str(Path.home() / "x")), "~/x")
        args = build_parser().parse_args(["doctor", "--report", "--offline"])
        with patch("shotseek.doctor.smoke_test", return_value=(False, "index failed: model_unavailable")):
            result = command(args, **STUBS)
        self.assertIn("FAIL - index failed: model_unavailable", result["_raw"])
        self.assertEqual(result["_exit"], 6)


class CpuDescription(IndexCase):
    def test_macos_brand_and_bounded_fallback(self):
        import subprocess
        from shotseek.doctor import cpu_name
        with patch("shotseek.doctor.sys.platform", "darwin"), \
                patch("shotseek.doctor.subprocess.run", return_value=NS(stdout="Example arm64 CPU\n")) as run:
            self.assertEqual(cpu_name(), "Example arm64 CPU")
            self.assertEqual(run.call_args.kwargs["timeout"], 2)
        with patch("shotseek.doctor.sys.platform", "darwin"), \
                patch("shotseek.doctor.subprocess.run", side_effect=subprocess.TimeoutExpired("sysctl", 2)), \
                patch("shotseek.doctor.Path.read_text", side_effect=OSError), \
                patch("shotseek.doctor.platform.processor", return_value="arm"):
            self.assertEqual(cpu_name(), "arm")
