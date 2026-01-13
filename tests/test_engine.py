import unittest
from unittest.mock import MagicMock, call
from typing import List, Dict, Callable

from repack.core.kit import Kit, KitTarget
from repack.core.request import RepackRequest
from repack.core.state import StateManager, TargetStatus
from repack.executor.base import Executor, Job
from repack.engine.manager import RepackEngine

class MockKit(Kit):
    def __init__(self, name, dependencies=None):
        super().__init__(name)
        self._dependencies = dependencies or []

    def get_output_path(self, request):
        return f"/tmp/{self.name}"

    def get_targets(self, request):
        return [KitTarget(self.name, pvt="default")]

    def get_dependencies(self):
        return self._dependencies

    def construct_command(self, target, request):
        return ["echo", target.id]

class MockExecutor(Executor):
    def __init__(self):
        self.submitted_jobs = []
        self.callbacks = {}

    def submit(self, job: Job, dependency_job_ids: List[str] = None, on_complete: Callable[[str, bool], None] = None) -> str:
        self.submitted_jobs.append((job, dependency_job_ids))
        if on_complete:
            self.callbacks[job.id] = on_complete
        return job.id

    def wait(self, job_ids):
        # Simulate completion
        for jid in job_ids:
            if jid in self.callbacks:
                # Simulate success
                self.callbacks[jid](jid, True)

class TestRepackEngine(unittest.TestCase):
    def setUp(self):
        self.request = RepackRequest(
            library_name="mylib", pvts=["default"], corners=["tt"], cells=["inv"], output_root="/tmp"
        )
        self.state_manager = MagicMock(spec=StateManager)
        self.executor = MockExecutor()

        # Define Kits
        # C -> B -> A (A depends on B, B depends on C)
        self.kit_c = MockKit("KitC")
        self.kit_b = MockKit("KitB", dependencies=["KitC"])
        self.kit_a = MockKit("KitA", dependencies=["KitB"])

        self.kits = [self.kit_a, self.kit_b, self.kit_c]
        self.engine = RepackEngine(self.kits, self.state_manager, self.executor)

    def test_full_run_execution_order(self):
        """
        All targets are PENDING. Should run C -> B -> A.
        """
        self.state_manager.initialize.return_value = False # Full run
        self.state_manager.get_status.return_value = TargetStatus.PENDING

        self.engine.run(self.request)

        submitted = self.executor.submitted_jobs
        self.assertEqual(len(submitted), 3)

        # Verify order and dependencies
        job_c, deps_c = submitted[0]
        job_b, deps_b = submitted[1]
        job_a, deps_a = submitted[2]

        self.assertEqual(job_c.id, "KitC::default")
        self.assertEqual(deps_c, [])

        self.assertEqual(job_b.id, "KitB::default")
        self.assertEqual(deps_b, ["KitC::default"])

        self.assertEqual(job_a.id, "KitA::default")
        self.assertEqual(deps_a, ["KitB::default"])

        # Verify state updates (mock executor simulates success)
        # Should be called with PASS
        self.state_manager.set_status.assert_any_call("KitC::default", TargetStatus.PASS)
        self.state_manager.set_status.assert_any_call("KitB::default", TargetStatus.PASS)
        self.state_manager.set_status.assert_any_call("KitA::default", TargetStatus.PASS)

    def test_incremental_skip_passed(self):
        """
        C is PASS. B is PENDING. A is PENDING.
        Should run B -> A. C should NOT be run, but B should depend on C's "completion" (conceptually).
        However, if C is not running, we can't wait on a job ID.
        So B effectively has NO running dependency on C.
        """
        self.state_manager.initialize.return_value = True # Incremental

        def get_status_side_effect(tid):
            if tid == "KitC::default": return TargetStatus.PASS
            return TargetStatus.PENDING

        self.state_manager.get_status.side_effect = get_status_side_effect

        self.engine.run(self.request)

        submitted = self.executor.submitted_jobs
        self.assertEqual(len(submitted), 2)

        job_b, deps_b = submitted[0]
        job_a, deps_a = submitted[1]

        self.assertEqual(job_b.id, "KitB::default")
        # Since C is PASS, it's filtered out of the execution graph.
        # B depends on C, but C isn't running. So B has no dependencies *in this run*.
        self.assertEqual(deps_b, [])

        self.assertEqual(job_a.id, "KitA::default")
        self.assertEqual(deps_a, ["KitB::default"])

    def test_incremental_partial_chain(self):
        """
        C is PENDING. B is PASS. A is PENDING.
        """
        self.state_manager.initialize.return_value = True

        def get_status_side_effect(tid):
            if tid == "KitC::default": return TargetStatus.PENDING
            if tid == "KitB::default": return TargetStatus.PASS
            if tid == "KitA::default": return TargetStatus.PENDING
            return TargetStatus.PENDING

        self.state_manager.get_status.side_effect = get_status_side_effect

        self.engine.run(self.request)

        submitted = self.executor.submitted_jobs
        # Expect C and A to run.
        job_ids = [j[0].id for j in submitted]
        self.assertIn("KitC::default", job_ids)
        self.assertIn("KitA::default", job_ids)
        self.assertNotIn("KitB::default", job_ids)

        # Check deps
        # C depends on nothing (in this run)
        # A depends on B. B is PASS (not running). So A depends on nothing (in this run).

        for job, deps in submitted:
            if job.id == "KitC::default":
                self.assertEqual(deps, [])
            if job.id == "KitA::default":
                self.assertEqual(deps, [])

if __name__ == '__main__':
    unittest.main()
