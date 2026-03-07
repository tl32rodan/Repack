"""Tests for StateManager with input-hash change detection."""

import os
import tempfile
import unittest

from kitdag.core.target import KitTarget, PvtStatus, TargetStatus
from kitdag.state.manager import StateManager


class TestStateManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_fresh_run(self):
        state = StateManager(self.tmpdir)
        loaded = state.load()
        self.assertEqual(loaded, {})

    def test_save_and_load(self):
        state = StateManager(self.tmpdir)
        targets = [
            KitTarget("kitA", status=TargetStatus.PASS, input_hash="abc123"),
        ]
        state.set_targets(targets)
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        self.assertIn("kitA", loaded)
        self.assertEqual(loaded["kitA"].status, TargetStatus.PASS)
        self.assertEqual(loaded["kitA"].input_hash, "abc123")

    def test_save_and_load_with_pvt_details(self):
        state = StateManager(self.tmpdir)
        targets = [
            KitTarget(
                "liberty",
                status=TargetStatus.PASS,
                input_hash="abc",
                pvt_details=[
                    PvtStatus("ss_0p75v", ok=True),
                    PvtStatus("tt_0p85v", ok=False, missing_files=["tt.lib"]),
                ],
            ),
        ]
        state.set_targets(targets)
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        t = loaded["liberty"]
        self.assertEqual(len(t.pvt_details), 2)
        self.assertTrue(t.pvt_details[0].ok)
        self.assertEqual(t.pvt_details[0].pvt, "ss_0p75v")
        self.assertFalse(t.pvt_details[1].ok)

    def test_summary(self):
        state = StateManager(self.tmpdir)
        state.set_targets([
            KitTarget("a", status=TargetStatus.PASS),
            KitTarget("b", status=TargetStatus.FAIL),
            KitTarget("c", status=TargetStatus.PASS),
        ])
        s = state.summary()
        self.assertEqual(s["PASS"], 2)
        self.assertEqual(s["FAIL"], 1)

    def test_error_message_preserved(self):
        state = StateManager(self.tmpdir)
        state.set_targets([
            KitTarget("kitA", status=TargetStatus.FAIL,
                      error_message="PVT check: 2/3"),
        ])
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        self.assertEqual(loaded["kitA"].error_message, "PVT check: 2/3")

    def test_state_path(self):
        state = StateManager(self.tmpdir)
        self.assertTrue(state.state_path.endswith("kitdag_status.csv"))


if __name__ == "__main__":
    unittest.main()
