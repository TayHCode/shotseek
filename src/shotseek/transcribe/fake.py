import json
from pathlib import Path
from .parse import segments


class FakeTranscriber:
    def __init__(self, path):
        self.path = path
        self.warnings = []

    def transcribe(self, path, language=None):
        return segments(json.loads(Path(self.path).read_text())), language or "en"
