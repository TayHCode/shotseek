import json


def format_document(document):
    return json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
