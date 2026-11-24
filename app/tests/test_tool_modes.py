"""Where a person's tools run (app/models/tool_modes.py and
POST /api/account/tool-modes): only known tools and modes are kept, the set
round-trips through /api/me, and {} puts everything back to Automatic."""
from __future__ import annotations

import unittest

from app.actions import TOOL_IDS
from app.models import tool_modes

try:
    from app.tests.route_support import RoutesTestCase
except unittest.SkipTest:  # without httpx2 only the checks below run
    RoutesTestCase = None  # type: ignore[assignment,misc]


class CheckTest(unittest.TestCase):
    def test_known_keys_and_modes_are_kept_in_catalog_order(self) -> None:
        checked = tool_modes.check({"split_bookmarks": "device", "*": "server", "merge": "auto"})
        self.assertEqual(list(checked), ["*", "split_bookmarks", "merge"])

    def test_unknown_tool_is_refused(self) -> None:
        with self.assertRaises(tool_modes.ToolModesError):
            tool_modes.check({"shred": "server"})

    def test_unknown_mode_is_refused(self) -> None:
        with self.assertRaises(tool_modes.ToolModesError):
            tool_modes.check({"*": "gpu"})

    def test_not_an_object_is_refused(self) -> None:
        with self.assertRaises(tool_modes.ToolModesError):
            tool_modes.check(["server"])

    def test_every_catalog_tool_can_be_set(self) -> None:
        everything = {tool: "server" for tool in TOOL_IDS}
        self.assertEqual(tool_modes.check(everything), everything)


@unittest.skipIf(RoutesTestCase is None, "needs httpx2")
class RouteTest(RoutesTestCase or unittest.TestCase):  # type: ignore[misc]
    def set_modes(self, modes: dict) -> tuple[int, dict]:
        return self.call("POST", "/api/account/tool-modes", cookie=self.user_cookie,
                         body={"tool_modes": modes, "csrf_token": self.csrf(self.user_cookie)})

    def test_set_then_me_answers_it(self) -> None:
        wanted = {"*": "server", "split_bookmarks": "device"}
        status, reply = self.set_modes(wanted)
        self.assertEqual(status, 200)
        self.assertEqual(reply["tool_modes"], wanted)
        status, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(me["tool_modes"], wanted)
        # Someone else's are untouched.
        _, other = self.call("GET", "/api/me", cookie=self.owner_cookie)
        self.assertEqual(other["tool_modes"], {})

    def test_empty_set_clears(self) -> None:
        self.set_modes({"*": "device"})
        status, _ = self.set_modes({})
        self.assertEqual(status, 200)
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["tool_modes"], {})

    def test_bad_set_is_refused_and_nothing_changes(self) -> None:
        self.set_modes({"*": "device"})
        status, _ = self.set_modes({"nope": "server"})
        self.assertEqual(status, 400)
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["tool_modes"], {"*": "device"})


if __name__ == "__main__":
    unittest.main()
