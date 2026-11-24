"""Check that the browser's split by bookmarks makes the same files as the
server's: the same names, pages, bookmarks and links, and page content copied
byte for byte. The browser side is static/js/local/split_bookmarks.js on the
real static/vendor/qpdf/qpdf.wasm, run under node (scripts/local_split.js).

  .venv/bin/python scripts/check_local_split.py            # built-in test books
  .venv/bin/python scripts/check_local_split.py a.pdf ...  # and these too

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
from pikepdf import Array, Dictionary, Name, OutlineItem, String  # noqa: E402

from app.actions import Context  # noqa: E402
from app.actions.split_bookmarks import Options, run  # noqa: E402

OPTION_SETS = [
    {},
    {"level": 2},
    {"level": 3},
    {"level": 2, "front_matter": False, "numbered": False},
    {"level": 2, "inner_bookmarks": False},
]


def make_book(path: Path, indirect_annots: bool) -> None:
    """A small book with what a split has to get right: a part's title page
    before its first chapter, a named target, two bookmarks on one page, one
    that points nowhere, an index with nothing under it, front matter, links
    inside and outside a section (direct, GoTo and named), and odd titles."""
    pdf = pikepdf.Pdf.new()
    for index in range(30):
        pdf.add_blank_page(page_size=(200, 200))
        pdf.pages[index].Contents = pdf.make_stream(f"BT /F1 24 Tf 20 100 Td (Page {index + 1}) Tj ET".encode())

    def link(page: int, dest: object = None, goto: object = None) -> None:
        annot = Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=[0, 0, 50, 50])
        if dest is not None:
            annot.Dest = dest
        if goto is not None:
            annot.A = Dictionary(S=Name.GoTo, D=goto)
        obj = pdf.pages[page].obj
        if "/Annots" not in obj:
            obj.Annots = pdf.make_indirect(Array()) if indirect_annots else Array()
        obj.Annots.append(pdf.make_indirect(annot))

    link(5, Array([pdf.pages[6].obj, Name.Fit]))
    link(5, Array([pdf.pages[19].obj, Name.Fit]))
    link(7, String("chap3"))
    link(7, Array([5, Name.Fit]))
    link(10, goto=Array([pdf.pages[2].obj, Name.Fit]))
    link(10, goto=Array([pdf.pages[11].obj, Name.Fit]))
    pdf.Root.Names = Dictionary(Dests=Dictionary(Names=Array([String("chap3"), Array([pdf.pages[12].obj, Name.Fit])])))
    with pdf.open_outline() as outline:
        part_one = OutlineItem("Part One: Begin", 3)
        part_one.children.append(OutlineItem("Chapter 1", 4))
        chapter_two = OutlineItem("Chapter 2 / Odd:Name?", 8)
        chapter_two.children.append(OutlineItem("Section 2.1", 9))
        deep = OutlineItem("Section 2.2", 10)
        deep.children.append(OutlineItem("Section 2.2.1  spaced   out ..", 11))
        chapter_two.children.append(deep)
        part_one.children.append(chapter_two)
        named = OutlineItem("Chapter 3 named", 0)
        named.destination = String("chap3")
        part_one.children.append(named)
        part_two = OutlineItem("Part Two", 15)
        part_two.children.append(OutlineItem("Chapter 4", 15))
        part_two.children.append(OutlineItem("Same page", 15))
        part_two.children.append(OutlineItem("Chapter 5 ünïcödé — 日本語", 19))
        nowhere = OutlineItem("Nowhere", 0)
        nowhere.destination = String("missing")
        part_two.children.append(nowhere)
        outline.root.extend([part_one, part_two, OutlineItem("Index", 25)])
    pdf.save(path)


def server_split(source: Path, out: Path, options: dict) -> dict:
    out.mkdir(parents=True)
    files = []

    def add(name: str, made: Path, meta: dict) -> None:
        made.rename(out / name)
        files.append({"name": name, **meta})

    context = Context(run_id="check", source=source, work=out, source_info={},
                      progress=lambda *_: None, cancelled=lambda: False, add_output=add)
    return {"result": run(context, Options(**options)), "files": files}


def local_split(source: Path, out: Path, options: dict) -> dict:
    answer = subprocess.run(["node", str(ROOT / "scripts" / "local_split.js"), str(source), str(out), json.dumps(options)],
                            capture_output=True, text=True)
    if answer.returncode != 0:
        raise SystemExit(f"local split failed: {answer.stderr.strip()}")
    return json.loads(answer.stdout)


def summary(path: Path) -> dict:
    """What a section is, apart from object numbers and layout: its pages'
    content, its bookmarks, and where each link points."""
    with pikepdf.open(path) as pdf:
        pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}

        def where(target: object) -> object:
            if isinstance(target, Array) and len(target):
                first = target[0]
                if isinstance(first, Dictionary):
                    return ["page", pages.get(first.objgen)]
                return ["raw", repr(first)]
            return ["other", repr(target)]

        def outline(items) -> list:
            return [[str(item.title), where(item.destination), outline(item.children)] for item in items]

        links = []
        for index, page in enumerate(pdf.pages):
            for annot in page.obj.get("/Annots", []):
                target = annot.get("/Dest")
                if target is None and "/A" in annot:
                    target = annot.A.get("/D")
                links.append([index, where(target)])
        with pdf.open_outline() as tree:
            marks = outline(tree.root)
        contents = [b"".join(stream.read_raw_bytes() for stream in (page.obj.Contents if isinstance(page.obj.Contents, Array) else [page.obj.Contents])) for page in pdf.pages]
        return {"pages": len(pdf.pages), "outline": marks, "links": links, "contents": [c.hex() for c in contents]}


def compare(source: Path, options: dict, work: Path) -> None:
    label = f"{source.name} {json.dumps(options)}"
    server = server_split(source, work / "server", options)
    local = local_split(source, work / "local", options)
    if server["result"] != local["result"]:
        raise SystemExit(f"{label}: result differs\n  server {server['result']}\n  local  {local['result']}")
    if server["files"] != local["files"]:
        raise SystemExit(f"{label}: files differ\n  server {server['files']}\n  local  {local['files']}")
    for made in server["files"]:
        theirs, ours = summary(work / "server" / made["name"]), summary(work / "local" / made["name"])
        for key in theirs:
            if theirs[key] != ours[key]:
                raise SystemExit(f"{label}: {made['name']}: {key} differs\n  server {theirs[key]}\n  local  {ours[key]}")
    print(f"ok  {label}: {len(server['files'])} files")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        books = [temp_dir / "book.pdf", temp_dir / "book-indirect-annots.pdf"]
        make_book(books[0], indirect_annots=False)
        make_book(books[1], indirect_annots=True)
        books += [Path(arg).resolve() for arg in sys.argv[1:]]
        for book_index, book in enumerate(books):
            for option_index, options in enumerate(OPTION_SETS):
                compare(book, options, temp_dir / f"run-{book_index}-{option_index}")
    print("The browser and the server split the same way.")


if __name__ == "__main__":
    main()
