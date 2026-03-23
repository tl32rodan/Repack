"""Tests for Task data model."""

import unittest

from kitdag.core.task import Task, TaskStatus, VariantDetail


class TestTask(unittest.TestCase):

    def test_id_no_scope(self):
        t = Task(step_name="extract")
        self.assertEqual(t.id, "extract")

    def test_id_with_scope(self):
        t = Task(step_name="extract", scope={"lib": "lib_a", "branch": "ss"})
        self.assertEqual(t.id, "extract/branch=ss/lib=lib_a")

    def test_id_lib_only(self):
        t = Task(step_name="merge", scope={"lib": "lib_a"})
        self.assertEqual(t.id, "merge/lib=lib_a")

    def test_lib_branch_shortcuts(self):
        t = Task(step_name="x", scope={"lib": "lib_a", "branch": "ss"})
        self.assertEqual(t.lib, "lib_a")
        self.assertEqual(t.branch, "ss")

    def test_variant_summary(self):
        t = Task(step_name="x", variant_details=[
            VariantDetail("ss", ".lib", ok=True),
            VariantDetail("ss", ".db", ok=False, message="missing"),
            VariantDetail("tt", ".lib", ok=True),
        ])
        self.assertEqual(t.variant_summary, "2/3 OK")

    def test_variant_summary_empty(self):
        t = Task(step_name="x")
        self.assertEqual(t.variant_summary, "")

    def test_equality(self):
        t1 = Task(step_name="x", scope={"lib": "a"})
        t2 = Task(step_name="x", scope={"lib": "a"})
        self.assertEqual(t1, t2)

    def test_hash(self):
        t1 = Task(step_name="x", scope={"lib": "a"})
        t2 = Task(step_name="x", scope={"lib": "a"})
        self.assertEqual(hash(t1), hash(t2))


if __name__ == "__main__":
    unittest.main()
