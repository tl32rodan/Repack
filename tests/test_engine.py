"""Tests for Engine execution with scoped tasks."""

import os
import tempfile
import unittest
from typing import Any, Dict, List

from kitdag.core.flow import Flow
from kitdag.core.step import Step, StepInput, StepOutput
from kitdag.core.task import TaskStatus
from kitdag.engine.local import LocalEngine


# --- Test step implementations ---

class SimpleStep(Step):
    name = "simple"
    base_command = "sh"
    inputs = [StepInput("library_name")]
    outputs = [StepOutput("output_dir")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        out = os.path.join(out_dir, "output.txt")
        return ["-c", f"mkdir -p {out_dir} && echo 'ok' > {out}"]


class FailStep(Step):
    name = "fail"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        return ["-c", "exit 1"]


class LogErrorStep(Step):
    name = "logerr"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        return ["-c", f"mkdir -p {out_dir} && echo 'ERROR: something wrong'"]


class VariantStep(Step):
    name = "variant_step"
    base_command = "sh"
    variant_key = "pvts"
    inputs = [StepInput("library_name"), StepInput("pvts", type="string[]")]
    outputs = [StepOutput("output_dir")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "test")
        pvts = inputs.get("pvts", [])
        cmds = []
        for pvt in pvts:
            pvt_dir = os.path.join(out_dir, pvt)
            cmds.append(f"mkdir -p {pvt_dir} && echo 'ok' > {pvt_dir}/{lib}_{pvt}.lib")
        return ["-c", " && ".join(cmds)] if cmds else ["-c", "true"]

    def get_expected_variant_outputs(self, variant, inputs):
        lib = inputs.get("library_name", "test")
        return [f"{variant}/{lib}_{variant}.lib"]

    def get_variant_products(self):
        return [".lib"]


# --- Helpers ---

def _build_single_step_pipeline(tmpdir, step_cls, extra_inputs=None):
    """Build a single-step pipeline for testing."""
    flow = Flow("test")
    flow.add_step("test_step", kit=step_cls())

    def get_branches(lib, step):
        return ["ss"]

    base_inputs = {"library_name": "test_lib"}
    if extra_inputs:
        base_inputs.update(extra_inputs)

    def get_inputs(lib, branch, step):
        return dict(base_inputs)

    pipeline = flow.build(
        libs=["lib_a"],
        get_branches=get_branches,
        get_inputs=get_inputs,
        output_root=tmpdir,
    )
    return pipeline, get_inputs


class TestEngineBasic(unittest.TestCase):

    def test_simple_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline, get_inputs = _build_single_step_pipeline(tmpdir, SimpleStep)
            engine = LocalEngine(pipeline, get_inputs)
            self.assertTrue(engine.run())

    def test_fail_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline, get_inputs = _build_single_step_pipeline(tmpdir, FailStep)
            engine = LocalEngine(pipeline, get_inputs, max_retries=0)
            self.assertFalse(engine.run())

    def test_log_error_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline, get_inputs = _build_single_step_pipeline(tmpdir, LogErrorStep)
            engine = LocalEngine(pipeline, get_inputs, max_retries=0)
            result = engine.run()
            self.assertFalse(result)
            tasks = engine.get_tasks()
            t = list(tasks.values())[0]
            self.assertEqual(t.status, TaskStatus.FAIL)


class TestMultiStepPipeline(unittest.TestCase):

    def test_dependency_chain(self):
        """A -> B: both should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flow = Flow("test")
            flow.add_step("step_a", kit=SimpleStep())
            flow.add_step("step_b", kit=SimpleStep())
            flow.add_dep("step_b", on="step_a")

            def get_branches(lib, step):
                return ["ss"]

            def get_inputs(lib, branch, step):
                return {"library_name": "test"}

            pipeline = flow.build(
                libs=["lib_a"],
                get_branches=get_branches,
                get_inputs=get_inputs,
                output_root=tmpdir,
            )
            engine = LocalEngine(pipeline, get_inputs)
            self.assertTrue(engine.run())

    def test_upstream_failure_cascades(self):
        """If A fails, B should also fail (dep failed)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flow = Flow("test")
            flow.add_step("step_a", kit=FailStep())
            flow.add_step("step_b", kit=SimpleStep())
            flow.add_dep("step_b", on="step_a")

            def get_branches(lib, step):
                return ["ss"]

            def get_inputs(lib, branch, step):
                return {"library_name": "test"}

            pipeline = flow.build(
                libs=["lib_a"],
                get_branches=get_branches,
                get_inputs=get_inputs,
                output_root=tmpdir,
            )
            engine = LocalEngine(pipeline, get_inputs, max_retries=0)
            self.assertFalse(engine.run())

            tasks = engine.get_tasks()
            for t in tasks.values():
                self.assertEqual(t.status, TaskStatus.FAIL)

    def test_fan_in(self):
        """merge (per-lib) should wait for all branches of char."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flow = Flow("test")
            flow.add_step("char", kit=SimpleStep())
            flow.add_step("merge", kit=SimpleStep())
            flow.add_dep("merge", on="char")

            def get_branches(lib, step):
                if step == "char":
                    return ["ss", "tt"]
                return []

            def get_inputs(lib, branch, step):
                return {"library_name": "test"}

            pipeline = flow.build(
                libs=["lib_a"],
                get_branches=get_branches,
                get_inputs=get_inputs,
                output_root=tmpdir,
            )

            # Verify merge depends on both char branches
            dag = pipeline.dag
            merge_id = "merge/lib=lib_a"
            deps = dag.get_dependencies(merge_id)
            self.assertEqual(len(deps), 2)

            engine = LocalEngine(pipeline, get_inputs)
            self.assertTrue(engine.run())


class TestVariantOutputChecking(unittest.TestCase):

    def test_variant_outputs_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline, get_inputs_fn = _build_single_step_pipeline(
                tmpdir, VariantStep,
                extra_inputs={"pvts": ["ss_0p75v", "tt_0p85v"]},
            )
            engine = LocalEngine(pipeline, get_inputs_fn, max_retries=0)
            self.assertTrue(engine.run())

            tasks = engine.get_tasks()
            t = list(tasks.values())[0]
            self.assertEqual(t.status, TaskStatus.PASS)
            self.assertEqual(len(t.variant_details), 2)
            self.assertTrue(all(d.ok for d in t.variant_details))


class TestIncrementalRun(unittest.TestCase):

    def test_skip_unchanged(self):
        """Second run should skip unchanged PASS tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            flow = Flow("test")
            flow.add_step("step_a", kit=SimpleStep())

            def get_branches(lib, step):
                return ["ss"]

            def get_inputs(lib, branch, step):
                return {"library_name": "test"}

            pipeline = flow.build(
                libs=["lib_a"],
                get_branches=get_branches,
                get_inputs=get_inputs,
                output_root=tmpdir,
            )

            # First run
            engine1 = LocalEngine(pipeline, get_inputs)
            self.assertTrue(engine1.run())

            # Second run with same inputs
            pipeline2 = flow.build(
                libs=["lib_a"],
                get_branches=get_branches,
                get_inputs=get_inputs,
                output_root=tmpdir,
            )
            engine2 = LocalEngine(pipeline2, get_inputs)
            self.assertTrue(engine2.run())

            # Should still be PASS (skipped, not re-run)
            tasks = engine2.get_tasks()
            t = list(tasks.values())[0]
            self.assertEqual(t.status, TaskStatus.PASS)


if __name__ == "__main__":
    unittest.main()
