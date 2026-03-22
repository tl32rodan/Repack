"""Tests for Flow API: add_step, add_dep, build, to_mermaid."""

import unittest
from typing import Any, Dict, List

from kitdag.core.flow import Flow
from kitdag.core.step import Step, StepInput
from kitdag.core.task import TaskStatus


# --- Test step implementations ---

class DummyStep(Step):
    name = "dummy"
    base_command = "echo"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        return ["ok"]


# --- Helpers ---

def _make_flow():
    """Create a simple 3-step flow: extract -> char -> merge."""
    flow = Flow("test")
    flow.add_step("extract", kit=DummyStep())
    flow.add_step("char", kit=DummyStep())
    flow.add_step("merge", kit=DummyStep())
    flow.add_dep("char", on="extract")
    flow.add_dep("merge", on="char")
    return flow


def _get_branches(lib: str, step: str) -> List[str]:
    """All steps expand by branch except merge."""
    if step == "merge":
        return []
    return ["ss", "tt", "ff"]


def _get_inputs(lib: str, branch: str, step: str) -> Dict[str, Any]:
    return {"library_name": lib}


class TestFlowAddStep(unittest.TestCase):

    def test_add_step(self):
        flow = Flow("test")
        flow.add_step("extract", kit=DummyStep())
        self.assertIn("extract", flow.steps)

    def test_duplicate_step_raises(self):
        flow = Flow("test")
        flow.add_step("extract", kit=DummyStep())
        with self.assertRaises(ValueError):
            flow.add_step("extract", kit=DummyStep())


class TestFlowAddDep(unittest.TestCase):

    def test_add_dep(self):
        flow = Flow("test")
        flow.add_step("a", kit=DummyStep())
        flow.add_step("b", kit=DummyStep())
        flow.add_dep("b", on="a")
        self.assertEqual(len(flow.deps), 1)

    def test_unknown_step_raises(self):
        flow = Flow("test")
        flow.add_step("a", kit=DummyStep())
        with self.assertRaises(ValueError):
            flow.add_dep("b", on="a")

    def test_branch_map(self):
        flow = Flow("test")
        flow.add_step("a", kit=DummyStep())
        flow.add_step("b", kit=DummyStep())
        flow.add_dep("b", on="a", branch_map={"corner": ["corner", "em"]})
        self.assertEqual(flow.deps[0].branch_map, {"corner": ["corner", "em"]})


class TestFlowBuild(unittest.TestCase):

    def test_basic_expansion(self):
        """3 steps, 2 libs, extract/char expand by branch, merge per-lib."""
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a", "lib_b"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        # extract: 2 libs × 3 branches = 6
        # char: 2 libs × 3 branches = 6
        # merge: 2 libs × 0 branches = 2
        self.assertEqual(len(pipeline.tasks), 14)

    def test_task_ids(self):
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        task_ids = set(pipeline.tasks.keys())
        self.assertIn("extract/branch=ss/lib=lib_a", task_ids)
        self.assertIn("char/branch=tt/lib=lib_a", task_ids)
        self.assertIn("merge/lib=lib_a", task_ids)

    def test_same_branch_deps(self):
        """char/lib_a/ss should depend on extract/lib_a/ss."""
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        dag = pipeline.dag
        char_ss_id = "char/branch=ss/lib=lib_a"
        deps = dag.get_dependencies(char_ss_id)
        self.assertIn("extract/branch=ss/lib=lib_a", deps)
        self.assertNotIn("extract/branch=tt/lib=lib_a", deps)

    def test_fan_in_deps(self):
        """merge/lib_a should depend on ALL char/lib_a/* branches."""
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        dag = pipeline.dag
        merge_id = "merge/lib=lib_a"
        deps = dag.get_dependencies(merge_id)
        self.assertEqual(len(deps), 3)  # ss, tt, ff
        self.assertIn("char/branch=ss/lib=lib_a", deps)
        self.assertIn("char/branch=tt/lib=lib_a", deps)
        self.assertIn("char/branch=ff/lib=lib_a", deps)

    def test_cross_lib_isolation(self):
        """Tasks for lib_a should not depend on tasks for lib_b."""
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a", "lib_b"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        dag = pipeline.dag
        merge_a_deps = dag.get_dependencies("merge/lib=lib_a")
        for dep in merge_a_deps:
            self.assertIn("lib_a", dep)
            self.assertNotIn("lib_b", dep)


class TestFlowBranchMap(unittest.TestCase):

    def test_cross_branch_dep(self):
        """step2/corner should depend on step1/{corner, em, lvl}."""
        flow = Flow("test")
        flow.add_step("step1", kit=DummyStep())
        flow.add_step("step2", kit=DummyStep())
        flow.add_dep("step2", on="step1", branch_map={
            "corner": ["corner", "em", "lvl"],
        })

        def get_branches(lib, step):
            return ["corner", "em", "lvl"]

        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )

        dag = pipeline.dag
        s2_corner = "step2/branch=corner/lib=lib_a"
        deps = dag.get_dependencies(s2_corner)
        self.assertEqual(len(deps), 3)
        self.assertIn("step1/branch=corner/lib=lib_a", deps)
        self.assertIn("step1/branch=em/lib=lib_a", deps)
        self.assertIn("step1/branch=lvl/lib=lib_a", deps)

    def test_cross_branch_auto_intersect(self):
        """If lib only has corner+lvl, em should be skipped."""
        flow = Flow("test")
        flow.add_step("step1", kit=DummyStep())
        flow.add_step("step2", kit=DummyStep())
        flow.add_dep("step2", on="step1", branch_map={
            "corner": ["corner", "em", "lvl", "lvf"],
        })

        def get_branches(lib, step):
            return ["corner", "lvl"]  # no em, no lvf

        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )

        dag = pipeline.dag
        s2_corner = "step2/branch=corner/lib=lib_a"
        deps = dag.get_dependencies(s2_corner)
        self.assertEqual(len(deps), 2)  # only corner + lvl
        self.assertIn("step1/branch=corner/lib=lib_a", deps)
        self.assertIn("step1/branch=lvl/lib=lib_a", deps)

    def test_intra_step_branch_dep(self):
        """step/em depends on step/corner (same step, different branch)."""
        flow = Flow("test")
        flow.add_step("step1", kit=DummyStep())
        flow.add_dep("step1", on="step1", branch_map={
            "em": ["corner"],
            "lvl": ["corner"],
        })

        def get_branches(lib, step):
            return ["corner", "em", "lvl"]

        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )

        dag = pipeline.dag
        em_deps = dag.get_dependencies("step1/branch=em/lib=lib_a")
        self.assertIn("step1/branch=corner/lib=lib_a", em_deps)
        lvl_deps = dag.get_dependencies("step1/branch=lvl/lib=lib_a")
        self.assertIn("step1/branch=corner/lib=lib_a", lvl_deps)
        # corner has no intra-step deps
        corner_deps = dag.get_dependencies("step1/branch=corner/lib=lib_a")
        self.assertEqual(len(corner_deps), 0)


class TestFlowMermaid(unittest.TestCase):

    def test_step_level_mermaid(self):
        flow = _make_flow()
        mermaid = flow.to_mermaid()
        self.assertIn("graph LR", mermaid)
        self.assertIn("extract --> char", mermaid)
        self.assertIn("char --> merge", mermaid)

    def test_concrete_mermaid(self):
        flow = _make_flow()
        mermaid = flow.to_mermaid(lib="lib_a", get_branches=_get_branches)
        self.assertIn("graph LR", mermaid)
        self.assertIn("subgraph extract", mermaid)
        self.assertIn("subgraph merge", mermaid)

    def test_branch_map_mermaid(self):
        flow = Flow("test")
        flow.add_step("s1", kit=DummyStep())
        flow.add_step("s2", kit=DummyStep())
        flow.add_dep("s2", on="s1", branch_map={"corner": ["corner", "em"]})
        mermaid = flow.to_mermaid()
        self.assertIn("s1_corner --> s2_corner", mermaid)
        self.assertIn("s1_em --> s2_corner", mermaid)


class TestFlowTopologicalSort(unittest.TestCase):

    def test_topological_order(self):
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        order = pipeline.dag.topological_sort()
        # All extract tasks before char tasks, all char before merge
        extract_indices = [order.index(t) for t in order if t.startswith("extract")]
        char_indices = [order.index(t) for t in order if t.startswith("char")]
        merge_indices = [order.index(t) for t in order if t.startswith("merge")]
        self.assertTrue(max(extract_indices) < min(char_indices))
        self.assertTrue(max(char_indices) < min(merge_indices))


class TestPipelineHelpers(unittest.TestCase):

    def test_libs(self):
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a", "lib_b"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        self.assertEqual(pipeline.libs, ["lib_a", "lib_b"])

    def test_tasks_for_lib(self):
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a", "lib_b"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        lib_a_tasks = pipeline.tasks_for_lib("lib_a")
        self.assertEqual(len(lib_a_tasks), 7)  # 3+3+1

    def test_get_task(self):
        flow = _make_flow()
        pipeline = flow.build(
            libs=["lib_a"],
            get_branches=_get_branches,
            get_inputs=_get_inputs,
            output_root="/tmp/out",
        )
        task = pipeline.get_task("extract", "lib_a", "ss")
        self.assertIsNotNone(task)
        self.assertEqual(task.step_name, "extract")


if __name__ == "__main__":
    unittest.main()
