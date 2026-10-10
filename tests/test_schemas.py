import json
from tests.test_search import SearchCase
from tests.support import ROOT, validate_schema, make_video
from shotseek.names import env


class Schemas(SearchCase):
    def test_allowed_subset(self):
        allowed = {"$schema", "type", "properties", "required", "items", "enum", "additionalProperties", "$ref", "description"}
        def visit(schema):
            self.assertFalse(set(schema) - allowed)
            for child in schema.get("properties", {}).values():
                visit(child)
            for key in ("items", "additionalProperties"):
                if isinstance(schema.get(key), dict):
                    visit(schema[key])
        files = list((ROOT / "src/shotseek/schemas").glob("*.json"))
        self.assertEqual(len(files), 12)
        for path in files:
            visit(json.loads(path.read_text()))

    def test_real_commands(self):
        commands = [
            ("init", ["init", "--force", "--library", "media=" + str(self.library)]),
            ("library", ["library", "list"]), ("index", ["index"]),
            ("status", ["status"]), ("search", ["search", "red"]),
            ("broll", ["broll", "--point", "coffee and pastry at the cafe"]),
            ("doctor", ["doctor", "--offline"]),
        ]
        ident = self.search("red")["queries"][0]["results"][0]["file_id"]
        commands.append(("show", ["show", ident]))
        fixture = self.base / "speech.json"
        fixture.write_text('[{"start":0,"end":6,"text":"Coffee and pastry at the cafe."}]')
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        path = make_video(self.base / "aroll.mp4", audio=True)
        commands.append(("transcribe", ["transcribe", str(path)]))
        for name, command in commands:
            with self.subTest(name=name):
                code, result, _ = self.cli(*command)
                if name != "doctor":
                    self.assertEqual(code, 0, result)
                validate_schema(result, name)
        validate_schema(self.cli("search", "--bad")[1], "error")
        validate_schema(self.cli("schema")[1], "envelope")
