"""The browser's split by bookmarks (static/js/local/) against the server's:
scripts/check_local_split.py runs both on the same books and compares every
file they make. Needs node, which runs the page's own qpdf.wasm."""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(shutil.which("node") is None, "node runs the browser's split")
class LocalSplitTest(unittest.TestCase):
    def test_the_browser_splits_like_the_server(self) -> None:
        answer = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_local_split.py")],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)

    def test_the_browser_rotates_and_compresses_like_the_server(self) -> None:
        answer = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_local_tools.py")],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)

    def test_the_browser_removes_watermarks_like_the_server(self) -> None:
        answer = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_local_watermarks.py")],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)
