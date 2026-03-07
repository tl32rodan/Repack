"""Engine - main orchestrator for the kitdag pipeline.

Flow: config -> spec collection -> build DAG -> execute -> validate -> check status
     -> cascade invalidation -> auto incremental re-run (up to 3 times) -> upload

False-negative prevention:
  1. Output validation: check expected files exist and are non-empty (per kit)
  2. Log scanning: detect ERROR/FATAL in logs even when return code is 0
  3. Cascade invalidation: when upstream re-runs, downstream targets are invalidated
  4. Stale artifact cleanup: clean_output() called BEFORE every re-run;
     upload destination is cleaned before copy
"""

import logging
import os
import shutil
from typing import Dict, List, Optional, Set

from kitdag.config import Config
from kitdag.core.dag import DAGBuilder
from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget, TargetStatus
from kitdag.core.validation import LogScanner, OutputValidator, ValidationResult
from kitdag.executor.base import Executor, Job
from kitdag.state.manager import StateManager
from kitdag.upload.uploader import Uploader

logger = logging.getLogger(__name__)

DEFAULT_AUTO_RETRIES = 3


class Engine:
    """Orchestrates the full kitdag pipeline with false-negative prevention."""

    def __init__(
        self,
        config: Config,
        kits: List[Kit],
        executor: Executor,
        max_retries: int = DEFAULT_AUTO_RETRIES,
    ):
        self.config = config
        self.kits = {kit.name: kit for kit in kits}
        self.executor = executor
        self.max_retries = max_retries

        self.state = StateManager(
            work_dir=config.output_root,
            specs=config.specs,
        )
        self.dag = DAGBuilder()
        self.uploader = Uploader(config)
        self.validator = OutputValidator()

        self._all_targets: List[KitTarget] = []

    def run(self) -> bool:
        """Execute the full kitdag pipeline.

        Returns:
            True if all targets passed and upload succeeded.
        """
        logger.info("=" * 60)
        logger.info("KitDAG Engine starting: %s", self.config.library_name)
        logger.info("=" * 60)

        # 1. Collect targets from all kits
        self._collect_targets()

        # 2. Reconcile with existing state (incremental support + spec change detection)
        self._all_targets = self.state.reconcile(self._all_targets)

        # 3. Cascade invalidation: if upstream target will re-run,
        #    all downstream targets must also re-run
        self._cascade_invalidation()

        # 4. Build DAG
        self._build_dag()

        # 5. Execute with auto-retry loop (up to max_retries)
        for attempt in range(self.max_retries + 1):
            pending = self.state.get_pending_targets()
            if not pending:
                logger.info("No pending targets, all done")
                break

            if attempt > 0:
                logger.info(
                    "Auto incremental re-run attempt %d/%d (%d targets)",
                    attempt, self.max_retries, len(pending),
                )
                # Cascade: if any upstream just failed, mark downstream pending
                self._cascade_invalidation()
                pending = self.state.get_pending_targets()
                if not pending:
                    break

            self._execute(pending)

            # Check if all passed
            failed = [
                tid for tid, t in self.state.get_targets().items()
                if t.status == TargetStatus.FAIL
            ]
            if not failed:
                break
            logger.info("Attempt %d: %d targets failed, will retry: %s",
                        attempt + 1, len(failed), failed)

        # 6. Summary
        summary = self.state.summary()
        logger.info("Final summary: %s", summary)

        all_passed = summary.get("FAIL", 0) == 0 and summary.get("PENDING", 0) == 0

        # 7. Upload (if all passed)
        if all_passed:
            upload_ok = self.uploader.upload_all(list(self.kits.values()))
            if not upload_ok:
                logger.error("Upload failed")
                return False
        else:
            logger.warning("Not all targets passed, skipping upload")

        # 8. Save final state
        self.state.save()

        return all_passed

    def _collect_targets(self) -> None:
        """Collect targets from all registered kits."""
        for kit in self.kits.values():
            targets = kit.get_targets(self.config)
            for t in targets:
                t.spec_hash = self.config.specs.compute_hash(t.kit_name)
            self._all_targets.extend(targets)

        logger.info("Collected %d targets from %d kits",
                     len(self._all_targets), len(self.kits))

    def _build_dag(self) -> None:
        """Build target-level DAG from kit-level dependencies."""
        self.dag.add_targets(self._all_targets)

        kit_deps = {
            kit.name: kit.dependencies
            for kit in self.kits.values()
        }
        self.dag.build_edges(kit_deps)

        order = self.dag.topological_sort()
        logger.info("DAG built: %d targets in %d stages",
                     len(order), len(self.dag.get_execution_stages()))

    def _cascade_invalidation(self) -> None:
        """Cascade invalidation: if an upstream target will re-run,
        mark all downstream targets as PENDING too.

        This prevents false-negative #3: downstream target keeps old PASS
        status even though its upstream dependency has been re-run with
        new data.
        """
        targets = self.state.get_targets()
        pending_ids = set(self.state.get_pending_targets())

        # Also treat FAIL as needing cascade
        fail_ids = {
            tid for tid, t in targets.items()
            if t.status == TargetStatus.FAIL
        }
        invalidated = pending_ids | fail_ids

        if not invalidated:
            return

        # Build temporary DAG for cascade computation
        dag = DAGBuilder()
        dag.add_targets(list(targets.values()))
        kit_deps = {
            kit.name: kit.dependencies
            for kit in self.kits.values()
        }
        dag.build_edges(kit_deps)

        # BFS from invalidated targets to find all downstream
        newly_invalidated: Set[str] = set()
        queue = list(invalidated)
        visited: Set[str] = set()

        while queue:
            tid = queue.pop(0)
            if tid in visited:
                continue
            visited.add(tid)

            for dependent in dag.get_dependents(tid):
                if dependent not in invalidated and dependent not in newly_invalidated:
                    dep_target = targets.get(dependent)
                    if dep_target and dep_target.status == TargetStatus.PASS:
                        newly_invalidated.add(dependent)
                        logger.info(
                            "Cascade invalidation: %s -> %s (downstream of re-running target)",
                            tid, dependent,
                        )
                queue.append(dependent)

        # Mark newly invalidated targets as PENDING
        for tid in newly_invalidated:
            self.state.update_status(tid, TargetStatus.PENDING)

        if newly_invalidated:
            logger.info("Cascade invalidated %d downstream targets", len(newly_invalidated))

    def _execute(self, target_ids: List[str]) -> None:
        """Execute pending targets with full validation."""
        targets = self.dag.get_all_targets()
        to_run = set(target_ids)

        def on_complete(job_id: str, success: bool) -> None:
            target = targets.get(job_id)
            if not target:
                self.state.mark_fail(job_id, "Target not found in DAG")
                return

            kit = self.kits.get(target.kit_name)
            if not kit:
                self.state.mark_fail(job_id, f"Kit {target.kit_name} not found")
                return

            if not success:
                self.state.mark_fail(job_id, "Execution failed (non-zero exit code)")
                return

            # === VALIDATION GATE ===
            # Defense #1: Check expected output files exist and are non-empty
            # Defense #2: Scan log for ERROR patterns
            validation = self._validate_target(target, kit)
            if validation.passed:
                self.state.mark_pass(job_id)
                logger.info("Target %s: PASS (validated)", job_id)
            else:
                error_msg = validation.summary()
                self.state.mark_fail(job_id, error_msg)
                logger.warning("Target %s: FAIL (validation) - %s", job_id, error_msg)

        self.executor.set_callback(on_complete)

        # Submit jobs in topological order
        order = self.dag.topological_sort()
        for tid in order:
            if tid not in to_run:
                continue

            target = targets[tid]
            kit = self.kits.get(target.kit_name)
            if not kit:
                logger.error("Kit %s not found for target %s", target.kit_name, tid)
                continue

            # Defense #4: Clean output BEFORE re-run to prevent stale artifacts
            kit.clean_output(target, self.config)

            # Ensure output directory exists after cleaning
            output_path = kit.get_output_path(self.config)
            os.makedirs(output_path, exist_ok=True)

            # Build log path
            log_dir = os.path.join(self.config.output_root, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"{tid.replace('::', '_')}.log")
            target.log_path = log_path

            # Build job
            command = kit.construct_command(target, self.config)
            deps = self.dag.get_dependencies(tid) & to_run

            job = Job(
                id=tid,
                command=command,
                cwd=output_path,
                log_path=log_path,
                dependencies=deps,
            )

            self.state.mark_running(tid)
            self.executor.submit(job)

        # Wait for all jobs
        results = self.executor.wait_all()
        logger.info("Execution complete: %d jobs, %d passed",
                     len(results), sum(1 for v in results.values() if v))

    def _validate_target(self, target: KitTarget, kit: Kit) -> ValidationResult:
        """Run full validation on a completed target.

        1. Check expected output files (Defense #1)
        2. Scan log for error patterns (Defense #2)
        """
        output_path = kit.get_output_path(self.config)
        expected = kit.get_expected_outputs(target, self.config)

        # Build scanner with kit-specific patterns
        scanner = LogScanner(
            extra_patterns=kit.get_log_error_patterns(),
            ignore_patterns=kit.get_log_ignore_patterns(),
        )
        validator = OutputValidator(log_scanner=scanner)

        return validator.validate(
            output_path=output_path,
            expected_files=expected,
            log_path=target.log_path,
        )

    def get_targets(self) -> Dict[str, KitTarget]:
        """Return all targets (for GUI consumption)."""
        return self.state.get_targets()

    def get_dag(self) -> DAGBuilder:
        """Return the DAG (for GUI visualization)."""
        return self.dag

    def get_kits(self) -> Dict[str, Kit]:
        """Return registered kits."""
        return dict(self.kits)
