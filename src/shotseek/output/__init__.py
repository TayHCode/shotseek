from ..paths import atomic_write, writable


def finish(args, payload, libraries):
    from ..cli import envelope
    from . import jsonout, csvout, textout
    document = envelope(args.command)
    document.update(payload)
    formatter = {"json": jsonout, "csv": csvout, "text": textout}[args.format]
    if args.output:
        target = writable(args.output, libraries)
        text = formatter.format_document(document)
        encoding = "utf-8-sig" if args.format == "csv" else "utf-8"
        atomic_write(target, text.encode(encoding), libraries)
        counts = dict(queries=len(payload.get("queries", [])), beats=len(payload.get("beats", [])),
            results=sum(len(q["results"]) for q in payload.get("queries",
            [])) + sum(len(b.get("candidates", [])) for b in payload.get("beats", [])))
        return dict(output_path=str(target), counts=counts, warnings=payload.get("warnings", []))
    if args.format != "json":
        return {"_raw": formatter.format_document(document).rstrip("\n")}
    return payload
