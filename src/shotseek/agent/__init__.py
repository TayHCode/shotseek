from importlib.resources import files
from ..names import NAME
from ..errors import AppError

DESCRIPTION = "Find photos, video moments and B-roll in the user's local media library by plain-English search. Use when the user wants pictures for a website or social post, B-roll on a subject, or B-roll that fits what an A-roll video says."


def format_document(target="generic"):
    guide = files(__package__).joinpath("guide.md").read_text(encoding="utf-8")
    if target == "generic":
        return guide
    if target == "claude-skill":
        return "---\nname: " + NAME + "\ndescription: " + DESCRIPTION + "\n---\n\n" + guide
    if target == "codex":
        return "## " + NAME + " (local media search)\n\n" + "\n".join("#" + line if line.startswith("#") else line for line in guide.splitlines()) + "\n"
    raise AppError("usage", "Unknown agent target.")


def command(args):
    return {"_raw": format_document(args.target).rstrip("\n")}
