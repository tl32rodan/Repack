"""Tests for StateManager with scoped tasks."""

import os
import tempfile
import unittest

from kitdag.core.task import Task, TaskStatus, VariantDetail
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
        tasks = [
            Task("extract", scope={"lib": "lib_a", "branch": "ss"},
                 status=TaskStatus.PASS, input_hash="abc123"),
        ]
        state.set_tasks(tasks)
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        tid = tasks[0].id
        self.assertIn(tid, loaded)
        self.assertEqual(loaded[tid].status, TaskStatus.PASS)
        self.assertEqual(loaded[tid].input_hash, "abc123")
        self.assertEqual(loaded[tid].scope, {"lib": "lib_a", "branch": "ss"})

    def test_save_and_load_variant_details(self):
        state = StateManager(self.tmpdir)
        tasks = [
            Task(
                "compile",
                scope={"lib": "lib_a", "branch": "ss"},
                status=TaskStatus.FAIL,
                input_hash="abc",
                variant_details=[
                    VariantDetail("ss_0p75v", ".lib", ok=True),
                    VariantDetail("ss_0p75v", ".db", ok=False, message="missing"),
                ],
            ),
        ]
        state.set_tasks(tasks)
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        tid = tasks[0].id
        t = loaded[tid]
        self.assertEqual(len(t.variant_details), 2)
        self.assertTrue(t.variant_details[0].ok)
        self.assertEqual(t.variant_details[0].variant, "ss_0p75v")
        self.assertEqual(t.variant_details[0].product, ".lib")
        self.assertFalse(t.variant_details[1].ok)

    def test_summary(self):
        state = StateManager(self.tmpdir)
        state.set_tasks([
            Task("a", status=TaskStatus.PASS),
            Task("b", status=TaskStatus.FAIL),
            Task("c", status=TaskStatus.PASS),
        ])
        s = state.summary()
        self.assertEqual(s["PASS"], 2)
        self.assertEqual(s["FAIL"], 1)

    def test_per_lib_task(self):
        """Task with only lib scope (no branch)."""
        state = StateManager(self.tmpdir)
        tasks = [
            Task("merge", scope={"lib": "lib_a"},
                 status=TaskStatus.PASS, input_hash="xyz"),
        ]
        state.set_tasks(tasks)
        state.save()

        state2 = StateManager(self.tmpdir)
        loaded = state2.load()
        tid = tasks[0].id
        self.assertIn(tid, loaded)
        self.assertEqual(loaded[tid].scope, {"lib": "lib_a"})


if __name__ == "__main__":
    unittest.main()
