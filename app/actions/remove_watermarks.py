"""Find watermarks and take them out.

The detectors and removers live in app/actions/watermarks/ (imported from the
standalone wmremove tool); this module is the action around them.

mode remove: every finding at least min_confidence sure is removed, and the
cleaned PDF is the output. mode check: nothing is written; the result lists
every finding with its evidence and an id, and a remove run whose picked
holds some of those ids removes exactly those, however sure each was. That is
how the page lets a person look first and choose. An id is worked out from
the PDF's own structure, so the same file gives the same ids every time.

Removal is surgical: a phrase loses only its own glyphs (with a gap of the
same width left, so nothing beside it moves), an overlay loses only its `Do`,
and a page's pictures are never touched: a watermark baked into a scan is
reported, not "fixed".

The browser twin is static/js/local/remove_watermarks.js.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from typing import Annotated, Any, Literal

import msgspec
import pikepdf
from msgspec import Meta

from app.actions import Action, ActionError, Context
from app.actions.pages import stem
from app.actions.pdf import open_pdf
from app.actions.watermarks import remove as removal
from app.actions.watermarks.detect import Options as ScanOptions
from app.actions.watermarks.detect import run_all
from app.actions.watermarks.model import Candidate
from app.actions.watermarks.pdfdoc import Document

NAME = "remove_watermarks"
DETECTORS = ("xobject", "phrase", "textstyle", "annot", "ocg", "imagepage")
# What a run's result holds at most, so its record stays small.
MAX_FINDINGS = 100
MAX_EVIDENCE = 8

Detector = Literal["xobject", "phrase", "textstyle", "annot", "ocg", "imagepage"]


class Options(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    mode: Annotated[Literal["remove", "check"], Meta(description="remove writes the cleaned PDF; check only lists what it finds, each with an id for picked.")] = "remove"
    phrases: Annotated[list[Annotated[str, Meta(max_length=200)]], Meta(max_length=50, description="Words to find and remove wherever they are, matched ignoring case and spaces.")] = []
    regexes: Annotated[list[Annotated[str, Meta(max_length=200)]], Meta(max_length=20, description="Regular expressions to find and remove, ignoring case.")] = []
    builtin: Annotated[bool, Meta(description="Also look for common watermark wording (CONFIDENTIAL, DRAFT, Journal Pre-proof ...) in short standalone text.")] = True
    min_confidence: Annotated[float, Meta(ge=0.0, le=1.0, description="How sure a finding must be to be removed, from 0 to 1.")] = 0.5
    detectors: Annotated[list[Detector], Meta(description="Which detectors to run; empty runs them all.")] = []
    picked: Annotated[list[Annotated[str, Meta(max_length=32)]], Meta(max_length=500, description="Finding ids from a check run: only these are removed, however sure each was.")] = []


def finding_id(cand: Candidate) -> str:
    """The same finding in the same file always gets the same id."""
    payload = cand.payload
    if cand.detector == "xobject":
        target = payload.get("target")
        key = f"{target[0]} {target[1]}" if isinstance(target, tuple) else f"{payload.get('name')} {cand.pages}"
    elif cand.detector in ("phrase", "textstyle"):
        key = f"{payload.get('source')} {payload.get('needle')}"
    elif cand.detector == "annot":
        key = f"{payload.get('page')} {payload.get('index')}"
    elif cand.detector == "ocg":
        key = f"{payload.get('target')} {payload.get('name')}"
    else:
        key = cand.description
    return hashlib.sha256(f"{cand.detector}|{key}".encode()).hexdigest()[:12]


def _finding(cand: Candidate, applied: bool | None) -> dict[str, Any]:
    record = cand.to_dict()
    record["id"] = finding_id(cand)
    record["description"] = record["description"][:200]
    record["evidence"] = [{"label": e["label"][:200], "weight": e["weight"]} for e in record["evidence"][:MAX_EVIDENCE]]
    if len(record["pages"]) > 2000:
        record["pages"] = record["pages"][:2000]
    if applied is not None:
        record["applied"] = applied
    return record


def _check_regexes(patterns: list[str]) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error:
            raise ActionError("bad_regex") from None


def run(context: Context, options: Options) -> dict[str, Any]:
    context.progress(0.0, "")
    _check_regexes(options.regexes)
    scan = ScanOptions(phrases=list(options.phrases), regexes=list(options.regexes), no_builtin=not options.builtin)
    target = context.work / "no-watermarks.pdf"
    with open_pdf(context.source) as pdf:
        doc = Document(pdf)
        context.check()
        context.progress(0.2, "")
        found, _warnings = run_all(doc, scan, only=set(options.detectors) or None)
        context.check()
        context.progress(0.5, "")
        if options.mode == "check":
            return {
                "mode": "check",
                "pages": doc.page_count,
                "min_confidence": options.min_confidence,
                "findings": [_finding(c, None) for c in found[:MAX_FINDINGS]],
                "more": max(0, len(found) - MAX_FINDINGS),
            }

        if options.picked:
            wanted = set(options.picked)
            chosen = [c for c in found if c.actionable and finding_id(c) in wanted]
        else:
            chosen = [c for c in found if c.actionable and c.confidence >= options.min_confidence]
        edits, report = removal.plan(doc, chosen)
        report = removal.apply(doc, edits, report)
        context.check()
        context.progress(0.8, "")
        applied = {finding_id(c) for c in report.applied}
        if report.changed:
            doc.write_back()
            pdf.save(
                target,
                stream_decode_level=pikepdf.StreamDecodeLevel.none,
                object_stream_mode=pikepdf.ObjectStreamMode.preserve,
            )
        page_count = doc.page_count
        findings = [_finding(c, finding_id(c) in applied) for c in found[:MAX_FINDINGS]]
    if not report.changed:
        # Nothing to take out: the file as it was, so a chain goes on.
        shutil.copyfile(context.source, target)
        applied = set()
    name = f"{stem(context.source_name)} - no watermarks.pdf"
    context.add_output(name, target, {"pages": page_count, "first_page": 1, "last_page": page_count, "title": context.source_info.get("title", "")})
    context.progress(1.0, name)
    return {
        "mode": "remove",
        "pages": page_count,
        "min_confidence": options.min_confidence,
        "removed": len(applied),
        **report.counts(),
        "findings": findings,
        "more": max(0, len(found) - MAX_FINDINGS),
    }


def keeps_upload(options: Options) -> bool:
    """A check is followed by a remove run on the same upload."""
    return options.mode == "check"


ACTION = Action(name=NAME, options=Options, run=run, keeps_upload=keeps_upload)
