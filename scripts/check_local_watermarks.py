"""Check that the browser's remove watermarks finds and removes the same as
the server's: the same findings (ids, words, confidence, evidence), the same
counts, and in what it writes, the same page content once read back, the
same annotations, XObjects and layers. The browser side is
static/js/local/remove_watermarks.js on the real static/vendor/qpdf/qpdf.wasm,
run under node (scripts/local_tool.js); the PDFs are the test fixtures
(app/tests/watermark_fixtures.py).

  .venv/bin/python scripts/check_local_watermarks.py            # the fixtures
  .venv/bin/python scripts/check_local_watermarks.py a.pdf ...  # and these too

Exits 1 on the first difference, saying what differs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pikepdf  # noqa: E402

from app.actions import ACTIONS, Context, parse_options  # noqa: E402
from app.tests.watermark_fixtures import FIXTURES, build  # noqa: E402

CASES: list[dict[str, Any]] = [
    {"mode": "check"},
    {},
    {"phrases": ["Watermark here", "REMOVEME", "SECRETSTAMP", "Page body 3"], "regexes": ["Real (content|page) .*stay"]},
    {"min_confidence": 0.3, "builtin": False},
]


def server_run(source: Path, out: Path, options: dict) -> dict:
    out.mkdir(parents=True)
    files: list[str] = []

    def add(name: str, made: Path, meta: dict) -> None:
        made.rename(out / name)
        files.append(name)

    action = ACTIONS["remove_watermarks"]
    context = Context(run_id="check", source=source, source_name=source.name, work=out, source_info={},
                      progress=lambda *_: None, cancelled=lambda: False, add_output=add)
    return {"result": action.run(context, parse_options(action, options)), "files": files}


def local_run(source: Path, out: Path, options: dict) -> dict:
    answer = subprocess.run(["node", str(ROOT / "scripts" / "local_tool.js"), "remove_watermarks", str(source), str(out), json.dumps(options)],
                            capture_output=True, text=True)
    if answer.returncode != 0:
        raise SystemExit(f"local run failed on {source.name}: {answer.stderr.strip()}")
    made = json.loads(answer.stdout)
    made["files"] = [f["name"] for f in made["files"]]
    return made


def _operand(item: Any) -> Any:
    if isinstance(item, (int, float, Decimal)):
        return round(float(item), 4)
    if isinstance(item, pikepdf.Array):
        return [_operand(one) for one in item]
    if isinstance(item, pikepdf.Dictionary):
        return {str(key): _operand(value) for key, value in item.items()}
    if isinstance(item, pikepdf.String):
        return bytes(item)
    return str(item)


def _content(obj: Any) -> list:
    """A content stream read back, numbers as numbers: 12 and 12.0 are the
    same, and a string is its bytes however it was written."""
    out = []
    for instr in pikepdf.parse_content_stream(obj):
        if isinstance(instr, pikepdf.ContentStreamInlineImage):
            out.append(("INLINE IMAGE",))
            continue
        out.append((str(instr.operator), [_operand(one) for one in instr.operands]))
    return out


def summary(path: Path) -> dict:
    with pikepdf.open(path) as pdf:
        pages = []
        for page in pdf.pages:
            resources = page.obj.get("/Resources") or pikepdf.Dictionary()
            xobjects = resources.get("/XObject") or pikepdf.Dictionary()
            forms = {}
            for name, xobject in sorted(xobjects.items()):
                if xobject.get("/Subtype") == "/Form":
                    forms[name] = _content(xobject)
            pages.append({
                "content": _content(page),
                "xobjects": sorted(str(name) for name in xobjects.keys()),
                "forms": forms,
                "annots": [str(a.get("/Subtype")) for a in page.obj.get("/Annots") or []],
            })
        layers: Any = None
        props = pdf.Root.get("/OCProperties")
        if props is not None:
            def names(items: Any) -> Any:
                return [names(one) if isinstance(one, pikepdf.Array) else str(one.get("/Name") if isinstance(one, pikepdf.Dictionary) else one)
                        for one in items]
            layers = {"ocgs": names(props.get("/OCGs") or []),
                      "order": names((props.get("/D") or pikepdf.Dictionary()).get("/Order") or [])}
        return {"pages": pages, "layers": layers}


def _same_findings(a: list, b: list) -> str:
    if len(a) != len(b):
        return f"{len(a)} findings against {len(b)}"
    for one, two in zip(a, b):
        for key in ("id", "detector", "kind", "description", "pages", "page_summary", "actionable", "applied"):
            if one.get(key) != two.get(key):
                return f"{key}: {one.get(key)!r} against {two.get(key)!r}"
        if abs(one["confidence"] - two["confidence"]) > 0.0011:
            return f"confidence of {one['description']}: {one['confidence']} against {two['confidence']}"
        labels = [(e["label"], round(e["weight"], 6)) for e in one["evidence"]]
        theirs = [(e["label"], round(e["weight"], 6)) for e in two["evidence"]]
        if labels != theirs:
            return f"evidence of {one['description']}:\n    {labels}\n    {theirs}"
    return ""


def compare(source: Path, options: dict, work: Path) -> None:
    label = f"{source.name} {json.dumps(options)}"
    server = server_run(source, work / "server", options)
    local = local_run(source, work / "local", options)
    ours, theirs = server["result"], local["result"]
    differs = _same_findings(ours.get("findings", []), theirs.get("findings", []))
    if differs:
        raise SystemExit(f"{label}: findings differ: {differs}")
    plain = {k: v for k, v in ours.items() if k != "findings"}
    plain_theirs = {k: v for k, v in theirs.items() if k != "findings"}
    if plain != plain_theirs:
        raise SystemExit(f"{label}: result differs\n  server {plain}\n  local  {plain_theirs}")
    if server["files"] != local["files"]:
        raise SystemExit(f"{label}: files differ\n  server {server['files']}\n  local  {local['files']}")
    for name in server["files"]:
        a, b = summary(work / "server" / name), summary(work / "local" / name)
        if a["layers"] != b["layers"]:
            raise SystemExit(f"{label}: layers differ\n  server {a['layers']}\n  local  {b['layers']}")
        for number, (one, two) in enumerate(zip(a["pages"], b["pages"]), start=1):
            for key in one:
                if one[key] != two[key]:
                    raise SystemExit(f"{label}: page {number}: {key} differs\n  server {one[key]}\n  local  {two[key]}")
    print(f"ok  {label} ({len(ours.get('findings', []))} findings, removed {ours.get('removed', '-')})")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        pdfs = [build(name, temp_dir) for name in FIXTURES]
        pdfs += [Path(arg).resolve() for arg in sys.argv[1:]]
        for pdf_index, pdf in enumerate(pdfs):
            for case_index, options in enumerate(CASES):
                compare(pdf, options, temp_dir / f"run-{pdf_index}-{case_index}")
    print("The browser and the server find and remove watermarks the same way.")


if __name__ == "__main__":
    main()
