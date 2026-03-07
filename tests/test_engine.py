"""Tests for Engine, focusing on false-negative prevention."""

import os
import tempfile
import unittest
from typing import Any, Dict, List

from kitdag.core.kit import Kit, KitInput, KitOutput
from kitdag.core.target import KitTarget, TargetStatus
from kitdag.engine.local import LocalEngine
from kitdag.pipeline import PipelineConfig, StepConfig


# ---------------------------------------------------------------------------
# Test kit implementations
# ---------------------------------------------------------------------------

class SimpleKit(Kit):
    """Test kit that creates expected output."""

    name = "simple"
    base_command = "sh"

    inputs = [KitInput("library_name")]
    outputs = [KitOutput("output_dir"), KitOutput("log")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        out = os.path.join(out_dir, "output.txt")
        return ["-c", f"mkdir -p {out_dir} && echo 'ok' > {out}"]


class FailKit(Kit):
    """Test kit that always fails."""

    name = "fail"
    base_command = "sh"

    inputs = [KitInput("library_name")]
    outputs = [KitOutput("output_dir"), KitOutput("log")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        return ["-c", "exit 1"]


class LogErrorKit(Kit):
    """Test kit that succeeds (exit 0) but has ERROR in log.

    Tests false-negative #2: log has ERROR but return code is 0.
    """

    name = "logerr"
    base_command = "sh"

    inputs = [KitInput("library_name")]
    outputs = [KitOutput("output_dir"), KitOutput("log")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        out = os.path.join(out_dir, "output.txt")
        return ["-c", f"mkdir -p {out_dir} && echo 'ok' > {out} && echo 'ERROR: something went wrong'"]


class PvtKit(Kit):
    """Test kit with per-PVT outputs."""

    name = "pvt_kit"
    base_command = "sh"
    pvt_key = "pvts"

    inputs = [
        KitInput("library_name"),
        KitInput("pvts", type="string[]"),
    ]
    outputs = [KitOutput("output_dir"), KitOutput("log")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        lib_name = inputs.get("library_name", "test")
        pvts = inputs.get("pvts", [])

        cmds = []
        for pvt in pvts:
            pvt_dir = os.path.join(out_dir, pvt)
            out_file = os.path.join(pvt_dir, f"{lib_name}_{pvt}.lib")
            cmds.append(f"mkdir -p {pvt_dir} && echo 'ok' > {out_file}")

        return ["-c", " && ".join(cmds)] if cmds else ["-c", "true"]

    def get_expected_pvt_outputs(self, pvt: str, inputs: Dict[str, Any]) -> List[str]:
        lib_name = inputs.get("library_name", "test")
        return [f"{pvt}/{lib_name}_{pvt}.lib"]


class PvtMissingKit(Kit):
    """Kit that claims per-PVT outputs but doesn't create them all."""

    name = "pvt_missing"
    base_command = "sh"
    pvt_key = "pvts"

    inputs = [
        KitInput("library_name"),
        KitInput("pvts", type="string[]"),
    ]
    outputs = [KitOutput("output_dir"), KitOutput("log")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        lib_name = inputs.get("library_name", "test")
        pvts = inputs.get("pvts", [])

        # Only create output for the first PVT
        if pvts:
            pvt = pvts[0]
            pvt_dir = os.path.join(out_dir, pvt)
            out_file = os.path.join(pvt_dir, f"{lib_name}_{pvt}.lib")
            return ["-c", f"mkdir -p {pvt_dir} && echo 'ok' > {out_file}"]
        return ["-c", "true"]

    def get_expected_pvt_outputs(self, pvt: str, inputs: Dict[str, Any]) -> List[str]:
        lib_name = inputs.get("library_name", "test")
        return [f"{pvt}/{lib_name}_{pvt}.lib"]


# ---------------------------------------------------------------------------
# Helper to build pipeline configs
# ---------------------------------------------------------------------------

def _make_pipeline(tmpdir: str, kit_name: str = "simple",
                   deps: List[str] = None,
                   inputs: Dict[str, Any] = None) -> PipelineConfig:
    """Create a single-step pipeline for testing."""
    step_inputs = inputs or {"library_name": "test_lib"}
    return PipelineConfig(
        steps={
            kit_name: StepConfig(
                name=kit_name,
                run=kit_name,
                inputs=step_inputs,
                output_dir=os.path.join(tmpdir, kit_name),
                log_path=os.path.join(tmpdir, kit_name, f"{kit_name}.log"),
                dependencies=deps or [],
            ),
        },
        output_root=tmpdir,
        executor="local",
        max_workers=2,
    )


def _make_multi_pipeline(tmpdir: str, steps_config: Dict) -> PipelineConfig:
    """Create a multi-step pipeline for testing.

    steps_config: {name: {"run": kit_name, "deps": [...], "inputs": {...}}}
    """
    steps = {}
    for name, cfg in steps_config.items():
        run = cfg.get("run", name)
        steps[name] = StepConfig(
            name=name,
            run=run,
            inputs=cfg.get("inputs", {"library_name": "test_lib"}),
            output_dir=os.path.join(tmpdir, name),
            log_path=os.path.join(tmpdir, name, f"{name}.log"),
            dependencies=cfg.get("deps", []),
        )
    return PipelineConfig(
        steps=steps,
        output_root=tmpdir,
        executor="local",
        max_workers=2,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEngineBasic(unittest.TestCase):

    def test_simple_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(tmpdir, "simple")
            kits = {"simple": SimpleKit()}
            engine = LocalEngine(pipeline, kits)
            self.assertTrue(engine.run())

    def test_fail_kit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(tmpdir, "fail")
            kits = {"fail": FailKit()}
            engine = LocalEngine(pipeline, kits, max_retries=0)
            self.assertFalse(engine.run())


class TestFalseNegativePrevention(unittest.TestCase):

    def test_fn2_log_error_detected(self):
        """FN#2: Kit exits 0 but log contains ERROR -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(tmpdir, "logerr")
            kits = {"logerr": LogErrorKit()}
            engine = LocalEngine(pipeline, kits, max_retries=0)
            result = engine.run()
            self.assertFalse(result)

            targets = engine.get_targets()
            t = targets["logerr"]
            self.assertEqual(t.status, TargetStatus.FAIL)
            self.assertIn("Log error", t.error_message)

    def test_fn3_cascade_invalidation(self):
        """FN#3: When upstream re-runs, downstream should also re-run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_multi_pipeline(tmpdir, {
                "A": {"run": "simple"},
                "B": {"run": "simple", "deps": ["A"]},
            })
            kits = {"simple": SimpleKit()}

            # First run: both pass
            engine = LocalEngine(pipeline, kits)
            self.assertTrue(engine.run())

            # Change inputs for A
            pipeline.steps["A"].inputs["library_name"] = "changed_lib"

            # Second run: A re-runs, B should cascade
            engine2 = LocalEngine(pipeline, kits)
            self.assertTrue(engine2.run())

            targets = engine2.get_targets()
            self.assertEqual(targets["A"].status, TargetStatus.PASS)
            self.assertEqual(targets["B"].status, TargetStatus.PASS)

    def test_auto_retry(self):
        """Engine should auto-retry failed targets up to max_retries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(tmpdir, "fail")
            kits = {"fail": FailKit()}
            engine = LocalEngine(pipeline, kits, max_retries=2)
            result = engine.run()
            self.assertFalse(result)


class TestPvtOutputChecking(unittest.TestCase):
    """Tests for the two-layer status model."""

    def test_pvt_outputs_all_present(self):
        """All per-PVT outputs present -> PASS with pvt_details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(
                tmpdir, "pvt_kit",
                inputs={"library_name": "test", "pvts": ["ss", "ff"]},
            )
            kits = {"pvt_kit": PvtKit()}
            engine = LocalEngine(pipeline, kits, max_retries=0)
            self.assertTrue(engine.run())

            targets = engine.get_targets()
            t = targets["pvt_kit"]
            self.assertEqual(t.status, TargetStatus.PASS)
            self.assertEqual(len(t.pvt_details), 2)
            self.assertTrue(all(p.ok for p in t.pvt_details))
            self.assertEqual(t.pvt_summary, "2/2 PVTs OK")

    def test_pvt_outputs_missing(self):
        """Some per-PVT outputs missing -> FAIL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(
                tmpdir, "pvt_missing",
                inputs={"library_name": "test", "pvts": ["ss", "ff"]},
            )
            kits = {"pvt_missing": PvtMissingKit()}
            engine = LocalEngine(pipeline, kits, max_retries=0)
            self.assertFalse(engine.run())

            targets = engine.get_targets()
            t = targets["pvt_missing"]
            self.assertEqual(t.status, TargetStatus.FAIL)
            self.assertEqual(len(t.pvt_details), 2)
            # First PVT created, second missing
            self.assertTrue(t.pvt_details[0].ok)
            self.assertFalse(t.pvt_details[1].ok)
            self.assertIn("PVT output check", t.error_message)

    def test_dependency_chain_with_pvts(self):
        """Multi-step pipeline with PVT kits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_multi_pipeline(tmpdir, {
                "pvt_kit": {
                    "run": "pvt_kit",
                    "inputs": {"library_name": "test", "pvts": ["ss", "ff"]},
                },
                "simple": {
                    "run": "simple",
                    "deps": ["pvt_kit"],
                },
            })
            kits = {"pvt_kit": PvtKit(), "simple": SimpleKit()}
            engine = LocalEngine(pipeline, kits)
            self.assertTrue(engine.run())


class TestInputValidation(unittest.TestCase):

    def test_missing_input_detected(self):
        """Missing required input should fail validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = _make_pipeline(tmpdir, "pvt_kit", inputs={})
            kits = {"pvt_kit": PvtKit()}
            engine = LocalEngine(pipeline, kits, max_retries=0)
            result = engine.run()
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
