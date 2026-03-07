"""Tests for Engine, focusing on false-negative prevention."""

import os
import tempfile
import unittest
from typing import Any, Dict, List

from kitdag.config import Config
from kitdag.core.kit import Kit
from kitdag.core.spec import SpecCollection
from kitdag.core.target import KitTarget, TargetStatus
from kitdag.engine.engine import Engine
from kitdag.executor.local import LocalExecutor


class SimpleKit(Kit):
    """Test kit that echoes and creates expected output."""

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        out = os.path.join(self.get_output_path(config), "output.txt")
        return ["sh", "-c", f"echo 'ok' > {out}"]

    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        return ["output.txt"]


class FailKit(Kit):
    """Test kit that always fails."""

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        return ["sh", "-c", "exit 1"]

    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        return ["output.txt"]


class LogErrorKit(Kit):
    """Test kit that succeeds (exit 0) but has ERROR in log.

    This tests false-negative #2: log has ERROR but return code is 0.
    """

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        out = os.path.join(self.get_output_path(config), "output.txt")
        return ["sh", "-c", f"echo 'ok' > {out} && echo 'ERROR: something went wrong'"]

    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        return ["output.txt"]


class MissingOutputKit(Kit):
    """Test kit that exits 0 but doesn't produce expected output.

    This tests false-negative #1: exit code 0 but output is missing.
    """

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        return ["sh", "-c", "echo 'done'"]

    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        return ["expected_but_missing.lib"]


class CornerKit(Kit):
    """Test kit that produces per-PVT targets."""

    def get_targets(self, config: Any) -> List[KitTarget]:
        pvts = config.extra.get("pvts", [])
        return [KitTarget(kit_name=self.name, pvt=pvt) for pvt in pvts]

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out = os.path.join(out_dir, "output.lib")
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'ok' > {out}"]

    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        return [os.path.join(target.pvt, "output.lib")]


def _make_config(tmpdir: str, pvts: List[str] = None) -> Config:
    specs = SpecCollection()
    extra = {}
    if pvts is not None:
        extra["pvts"] = pvts
    else:
        extra["pvts"] = ["ss_100c", "ff_0c"]
    return Config(
        library_name="test_lib",
        output_root=tmpdir,
        max_workers=2,
        specs=specs,
        extra=extra,
    )


class TestEngineBasic(unittest.TestCase):

    def test_simple_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir)
            kits = [SimpleKit("simple")]
            engine = Engine(config, kits, LocalExecutor(2))
            self.assertTrue(engine.run())

    def test_fail_kit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir)
            kits = [FailKit("fail")]
            engine = Engine(config, kits, LocalExecutor(2), max_retries=0)
            self.assertFalse(engine.run())


class TestFalseNegativePrevention(unittest.TestCase):
    """Tests for the four false-negative scenarios."""

    def test_fn1_missing_output_detected(self):
        """FN#1: Kit exits 0 but expected output is missing -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir)
            kits = [MissingOutputKit("missing")]
            engine = Engine(config, kits, LocalExecutor(2), max_retries=0)
            result = engine.run()
            self.assertFalse(result)

            targets = engine.get_targets()
            t = targets["missing::ALL"]
            self.assertEqual(t.status, TargetStatus.FAIL)
            self.assertIn("Missing", t.error_message)

    def test_fn2_log_error_detected(self):
        """FN#2: Kit exits 0 but log contains ERROR -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir)
            kits = [LogErrorKit("logerr")]
            engine = Engine(config, kits, LocalExecutor(2), max_retries=0)
            result = engine.run()
            self.assertFalse(result)

            targets = engine.get_targets()
            t = targets["logerr::ALL"]
            self.assertEqual(t.status, TargetStatus.FAIL)
            self.assertIn("Log error", t.error_message)

    def test_fn3_cascade_invalidation(self):
        """FN#3: When upstream re-runs, downstream should also re-run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir, pvts=[])

            kitA = SimpleKit("A")
            kitB = SimpleKit("B", dependencies=["A"])

            # First run: both pass
            engine = Engine(config, [kitA, kitB], LocalExecutor(2))
            self.assertTrue(engine.run())

            # Now change spec for A
            config.specs.set_kit_spec("A", {"changed": True})

            # Second run: A should re-run, and B should cascade
            engine2 = Engine(config, [kitA, kitB], LocalExecutor(2))
            engine2._collect_targets()
            engine2._all_targets = engine2.state.reconcile(engine2._all_targets)

            # A should be pending (spec changed)
            a_target = next(t for t in engine2._all_targets if t.kit_name == "A")
            self.assertEqual(a_target.status, TargetStatus.PENDING)

            # Build DAG and cascade
            engine2._build_dag()
            engine2._cascade_invalidation()

            # B should now also be pending due to cascade
            targets = engine2.state.get_targets()
            self.assertEqual(targets["B::ALL"].status, TargetStatus.PENDING)

    def test_auto_retry(self):
        """Engine should auto-retry failed targets up to max_retries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir)
            kits = [FailKit("fail")]
            engine = Engine(config, kits, LocalExecutor(2), max_retries=2)
            result = engine.run()
            self.assertFalse(result)


class TestCornerBasedKits(unittest.TestCase):

    def test_corner_kit_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir, pvts=["ss_100c", "ff_0c"])
            kit = CornerKit("liberty")
            targets = kit.get_targets(config)
            self.assertEqual(len(targets), 2)
            self.assertEqual(targets[0].pvt, "ss_100c")
            self.assertEqual(targets[1].pvt, "ff_0c")

    def test_corner_kit_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(tmpdir, pvts=["ss_100c", "ff_0c"])
            kits = [CornerKit("liberty")]
            engine = Engine(config, kits, LocalExecutor(2))
            self.assertTrue(engine.run())


if __name__ == "__main__":
    unittest.main()
