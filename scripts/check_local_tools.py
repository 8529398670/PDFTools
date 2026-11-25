"""Check that the browser's rotate and compress make the same files as the
server's: the same names and pages, each page turned the same way, and the
same page content once decoded. The browser side is static/js/local/<tool>.js
on the real static/vendor/qpdf/qpdf.wasm, run under node
(scripts/local_tool.js). Sizes are not compared: both use qpdf 12.3.2, but
pikepdf and the command line can order objects differently.

  .venv/bin/python scripts/check_local_tools.py            # built-in test book
  .venv/bin/python scripts/check_local_tools.py a.pdf ...  # and these too

Exits 1 on the first difference, saying what differs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pikepdf  # noqa: E402

from app.actions import ACTIONS, Context, parse_options  # noqa: E402

CASES = [
    ("rotate", {}),
    ("rotate", {"angle": 180, "pages": "2-4, 9"}),
    ("rotate", {"angle": 270, "pages": "-2,10-"}),
    ("compress", {}),
]


def make_book(path: Path) -> None:
    """Twelve pages with text streams written loosely (so there is something
    to compress) and a page already turned."""
    pdf = pikepdf.Pdf.new()
    for index in range(12):
        pdf.add_blank_page(page_size=(300, 400))
        text = " ".join(f"BT /F1 12 Tf 20 {20 + line * 14} Td (Page {index + 1} line {line}) Tj ET" for line in range(25))
        pdf.pages[index].Contents = pdf.make_stream(text.encode())
    pdf.pages[3].Rotate = 90
    pdf.save(path, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)


def server_run(tool: str, source: Path, out: Path, options: dict) -> dict:
    out.mkdir(parents=True)
    files = []

    def add(name: str, made: Path, meta: dict) -> None:
        made.rename(out / name)
        files.append({"name": name, "pages": meta["pages"]})

    action = ACTIONS[tool]
    context = Context(run_id="check", source=source, source_name=source.name, work=out, source_info={},
                      progress=lambda *_: None, cancelled=lambda: False, add_output=add)
    return {"result": action.run(context, parse_options(action, options)), "files": files}


def local_run(tool: str, source: Path, out: Path, options: dict) -> dict:
    answer = subprocess.run(["node", str(ROOT / "scripts" / "local_tool.js"), tool, str(source), str(out), json.dumps(options)],
                            capture_output=True, text=True)
    if answer.returncode != 0:
        raise SystemExit(f"local {tool} failed: {answer.stderr.strip()}")
    made = json.loads(answer.stdout)
    made["files"] = [{"name": f["name"], "pages": f["pages"]} for f in made["files"]]
    return made


def summary(path: Path) -> dict:
    with pikepdf.open(path) as pdf:
        return {
            "pages": len(pdf.pages),
            "rotate": [int(page.obj.get("/Rotate", 0)) % 360 for page in pdf.pages],
            "contents": [page.obj.Contents.read_bytes().hex() for page in pdf.pages],
        }


def compare(tool: str, source: Path, options: dict, work: Path) -> None:
    label = f"{tool} {source.name} {json.dumps(options)}"
    server = server_run(tool, source, work / "server", options)
    local = local_run(tool, source, work / "local", options)
    same = {key: value for key, value in server["result"].items() if key not in ("after",)}
    theirs = {key: value for key, value in local["result"].items() if key not in ("after",)}
    if same != theirs:
        raise SystemExit(f"{label}: result differs\n  server {server['result']}\n  local  {local['result']}")
    if server["files"] != local["files"]:
        raise SystemExit(f"{label}: files differ\n  server {server['files']}\n  local  {local['files']}")
    for made in server["files"]:
        a, b = summary(work / "server" / made["name"]), summary(work / "local" / made["name"])
        for key in a:
            if a[key] != b[key]:
                raise SystemExit(f"{label}: {made['name']}: {key} differs\n  server {a[key]}\n  local  {b[key]}")
    sizes = ""
    if tool == "compress":
        sizes = f" ({server['result']['before']} -> server {server['result']['after']}, browser {local['result']['after']})"
    print(f"ok  {label}{sizes}")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        books = [temp_dir / "book.pdf"]
        make_book(books[0])
        books += [Path(arg).resolve() for arg in sys.argv[1:]]
        for book_index, book in enumerate(books):
            for case_index, (tool, options) in enumerate(CASES):
                compare(tool, book, options, temp_dir / f"run-{book_index}-{case_index}")
    print("The browser and the server rotate and compress the same way.")


if __name__ == "__main__":
    main()
