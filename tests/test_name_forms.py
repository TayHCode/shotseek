import re
import tomllib
import unittest
from tests.support import ROOT, repo_files
from shotseek.names import NAME, ENV_PREFIX


class Names(unittest.TestCase):
    def test_forms(self):
        loose = re.compile(re.escape(NAME[:4]) + r"[ _-]?" + re.escape(NAME[4:]), re.I)
        earlier = re.compile("media" + r"[ _-]?" + "finder", re.I)
        hits = []
        for p in repo_files():
            text = p.read_text(errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                if earlier.search(line):
                    hits.append(f"{p.relative_to(ROOT)}:{n}")
                for match in loose.finditer(line):
                    if match.group() != NAME and not line[match.start():].startswith(ENV_PREFIX):
                        hits.append(f"{p.relative_to(ROOT)}:{n}")
        self.assertFalse(hits, "\n".join(hits))
        self.assertTrue((ROOT / "src" / NAME).is_dir())
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(list(data["project"]["scripts"]), [NAME])
