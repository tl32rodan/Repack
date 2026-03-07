"""Tests for StateManager with spec-hash change detection."""

import os
import tempfile
import unittest

from kitdag.core.spec import SpecCollection
from kitdag.core.target import KitTarget, TargetStatus
from kitdag.state.manager import StateManager


class TestStateManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.specs = SpecCollection(global_spec={"version": "1.0"})
        self.specs.set_kit_spec("kitA", {"param": "value1"})

    def test_fresh_run(self):
        state = StateManager(self.tmpdir, self.specs)
        loaded = state.load()
        self.assertEqual(loaded, {})

    def test_save_and_load(self):
        state = StateManager(self.tmpdir, self.specs)
        targets = [
            KitTarget("kitA", pvt="ALL", status=TargetStatus.PASS, spec_hash="abc"),
        ]
        state.set_targets(targets)
        state.save()

        state2 = StateManager(self.tmpdir, self.specs)
        loaded = state2.load()
        self.assertIn("kitA::ALL", loaded)
        self.assertEqual(loaded["kitA::ALL"].status, TargetStatus.PASS)

    def test_reconcile_fail_becomes_pending(self):
        """Previously FAIL targets should become PENDING."""
        state = StateManager(self.tmpdir, self.specs)
        targets = [
            KitTarget("kitA", pvt="ALL", status=TargetStatus.FAIL, spec_hash="abc"),
        ]
        state.set_targets(targets)
        state.save()

        new_targets = [KitTarget("kitA", pvt="ALL")]
        state2 = StateManager(self.tmpdir, self.specs)
        result = state2.reconcile(new_targets)
        self.assertEqual(result[0].status, TargetStatus.PENDING)

    def test_reconcile_pass_unchanged_stays_pass(self):
        """PASS with unchanged spec stays PASS."""
        h = self.specs.compute_hash("kitA")
        state = StateManager(self.tmpdir, self.specs)
        targets = [
            KitTarget("kitA", pvt="ALL", status=TargetStatus.PASS, spec_hash=h),
        ]
        state.set_targets(targets)
        state.save()

        new_targets = [KitTarget("kitA", pvt="ALL")]
        state2 = StateManager(self.tmpdir, self.specs)
        result = state2.reconcile(new_targets)
        self.assertEqual(result[0].status, TargetStatus.PASS)

    def test_reconcile_pass_spec_changed_becomes_pending(self):
        """PASS but spec changed -> PENDING."""
        state = StateManager(self.tmpdir, self.specs)
        targets = [
            KitTarget("kitA", pvt="ALL", status=TargetStatus.PASS, spec_hash="old_hash"),
        ]
        state.set_targets(targets)
        state.save()

        new_targets = [KitTarget("kitA", pvt="ALL")]
        state2 = StateManager(self.tmpdir, self.specs)
        result = state2.reconcile(new_targets)
        self.assertEqual(result[0].status, TargetStatus.PENDING)

    def test_reconcile_new_target(self):
        state = StateManager(self.tmpdir, self.specs)
        state.set_targets([])
        state.save()

        new_targets = [KitTarget("kitB", pvt="ALL")]
        state2 = StateManager(self.tmpdir, self.specs)
        result = state2.reconcile(new_targets)
        self.assertEqual(result[0].status, TargetStatus.PENDING)

    def test_summary(self):
        state = StateManager(self.tmpdir, self.specs)
        state.set_targets([
            KitTarget("a", pvt="ALL", status=TargetStatus.PASS),
            KitTarget("b", pvt="ALL", status=TargetStatus.FAIL),
            KitTarget("c", pvt="ALL", status=TargetStatus.PASS),
        ])
        s = state.summary()
        self.assertEqual(s["PASS"], 2)
        self.assertEqual(s["FAIL"], 1)


class TestSpecCollection(unittest.TestCase):

    def test_hash_deterministic(self):
        specs = SpecCollection(global_spec={"a": 1})
        h1 = specs.compute_hash("kit1")
        h2 = specs.compute_hash("kit1")
        self.assertEqual(h1, h2)

    def test_hash_changes_with_spec(self):
        specs = SpecCollection()
        specs.set_kit_spec("kit1", {"param": "v1"})
        h1 = specs.compute_hash("kit1")

        specs.set_kit_spec("kit1", {"param": "v2"})
        h2 = specs.compute_hash("kit1")
        self.assertNotEqual(h1, h2)

    def test_has_changed(self):
        specs = SpecCollection()
        specs.set_kit_spec("kit1", {"param": "v1"})
        h = specs.compute_hash("kit1")
        self.assertFalse(specs.has_changed("kit1", h))

        specs.set_kit_spec("kit1", {"param": "v2"})
        self.assertTrue(specs.has_changed("kit1", h))

    def test_merge_with_global(self):
        specs = SpecCollection(global_spec={"g": "global_val"})
        specs.set_kit_spec("kit1", {"k": "kit_val"})
        merged = specs.get_kit_spec("kit1")
        self.assertEqual(merged["g"], "global_val")
        self.assertEqual(merged["k"], "kit_val")


if __name__ == "__main__":
    unittest.main()
