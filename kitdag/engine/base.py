"""BaseEngine — shared execution orchestration for all engine backends.

Handles:
- Input hashing for incremental detection
- State reconciliation (skip unchanged PASS tasks)
- Cascade invalidation (upstream re-run → downstream PENDING)
- Per-variant output checking (layer 2)
- Auto-retry on failure
"""

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set

from kitdag.core.dag import DAGBuilder
from kitdag.core.flow import Flow, Pipeline
from kitdag.core.step import Step
from kitdag.core.task import Task, TaskStatus, VariantDetail
from kitdag.core.validation import LogScanner, OutputValidator, ValidationResult
from kitdag.state.manager import StateManager

logger = logging.getLogger(__name__)

DEFAULT_AUTO_RETRIES = 3


class InputHasher:
    """Compute deterministic hash of a task's resolved inputs."""

    @staticmethod
    def compute(inputs: Dict[str, Any]) -> str:
        canonical = json.dumps(inputs, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class BaseEngine(ABC):
    """Shared engine logic. Subclasses implement _execute_task()."""

    def __init__(
        self,
        pipeline: Pipeline,
        get_inputs,
        max_retries: int = DEFAULT_AUTO_RETRIES,
    ):
        self.pipeline = pipeline
        self.get_inputs = get_inputs
        self.max_retries = max_retries
        self.state = StateManager(work_dir=pipeline.output_root)
        self._tasks = pipeline.tasks

    @abstractmethod
    def _execute_task(self, task: Task, step: Step, inputs: Dict[str, Any]) -> bool:
        """Execute a single task. Return True if command succeeded (exit 0)."""

    def run(self) -> bool:
        """Execute the full pipeline."""
        logger.info("=" * 60)
        logger.info("KitDAG Engine starting: %s", self.pipeline.name)
        logger.info("  Tasks: %d", len(self._tasks))
        logger.info("=" * 60)

        # 1. Compute input hashes
        self._compute_hashes()

        # 2. Reconcile with saved state (incremental)
        self._reconcile_state()

        # 3. Cascade invalidation
        self._cascade_invalidation()

        # 4. Save initial state
        self.state.set_tasks(list(self._tasks.values()))
        self.state.save()

        # 5. Execute with auto-retry
        for attempt in range(self.max_retries + 1):
            pending = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.PENDING, TaskStatus.FAIL)
            ]
            if not pending:
                logger.info("No pending tasks, all done")
                break

            if attempt > 0:
                logger.info(
                    "Auto retry attempt %d/%d (%d tasks)",
                    attempt, self.max_retries, len(pending),
                )
                self._cascade_invalidation()
                pending = [
                    tid for tid, t in self._tasks.items()
                    if t.status in (TaskStatus.PENDING, TaskStatus.FAIL)
                ]
                if not pending:
                    break

            self._run_pending(pending)

            failed = [tid for tid, t in self._tasks.items()
                      if t.status == TaskStatus.FAIL]
            if not failed:
                break
            logger.info("Attempt %d: %d tasks failed", attempt + 1, len(failed))

        # 6. Summary
        summary = self._summary()
        logger.info("Final summary: %s", summary)

        all_passed = summary.get("FAIL", 0) == 0 and summary.get("PENDING", 0) == 0

        # 7. Save final state
        self.state.save()

        return all_passed

    def _compute_hashes(self) -> None:
        """Compute input hash for each task."""
        for task in self._tasks.values():
            lib = task.scope.get("lib", "")
            branch = task.scope.get("branch", "")
            inputs = self.get_inputs(lib, branch, task.step_name)
            # Include scope in hash so different scopes produce different hashes
            hash_input = {**inputs, "__scope__": task.scope}
            task.input_hash = InputHasher.compute(hash_input)

    def _reconcile_state(self) -> None:
        """Reconcile with saved state for incremental runs."""
        existing = self.state.load()
        if not existing:
            return

        for tid, task in self._tasks.items():
            old = existing.get(tid)
            if old is None:
                continue
            if old.status == TaskStatus.SKIP:
                task.status = TaskStatus.SKIP
            elif old.status == TaskStatus.PASS:
                if old.input_hash == task.input_hash:
                    task.status = TaskStatus.PASS
                    task.variant_details = old.variant_details
                    logger.debug("Task %s unchanged, keeping PASS", tid)
                else:
                    task.status = TaskStatus.PENDING
                    logger.info("Input changed for %s, marking PENDING", tid)
            elif old.status == TaskStatus.FAIL:
                task.status = TaskStatus.PENDING

    def _cascade_invalidation(self) -> None:
        """If upstream will re-run, mark downstream tasks PENDING."""
        dag = self.pipeline.dag
        invalidated = {
            tid for tid, t in self._tasks.items()
            if t.status in (TaskStatus.PENDING, TaskStatus.FAIL)
        }
        if not invalidated:
            return

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
                    dep_task = self._tasks.get(dependent)
                    if dep_task and dep_task.status == TaskStatus.PASS:
                        newly_invalidated.add(dependent)
                        logger.info("Cascade invalidation: %s → %s", tid, dependent)
                queue.append(dependent)

        for tid in newly_invalidated:
            self._tasks[tid].status = TaskStatus.PENDING

    def _run_pending(self, pending_ids: List[str]) -> None:
        """Execute pending tasks in topological order."""
        order = self.pipeline.dag.topological_sort()
        to_run = set(pending_ids)

        for tid in order:
            if tid not in to_run:
                continue

            task = self._tasks[tid]
            step = self.pipeline.flow.get_step(task.step_name)

            lib = task.scope.get("lib", "")
            branch = task.scope.get("branch", "")
            inputs = self.get_inputs(lib, branch, task.step_name)
            inputs["output_dir"] = task.output_dir

            # Check if upstream deps all passed
            deps = self.pipeline.dag.get_dependencies(tid)
            dep_failed = any(
                self._tasks.get(d, Task(step_name="")).status == TaskStatus.FAIL
                for d in deps
            )
            if dep_failed:
                task.status = TaskStatus.FAIL
                task.error_message = "Upstream dependency failed"
                self.state.set_tasks(list(self._tasks.values()))
                self.state.save()
                continue

            # Ensure output dir exists
            if task.output_dir:
                os.makedirs(task.output_dir, exist_ok=True)
            if task.log_path:
                os.makedirs(os.path.dirname(task.log_path), exist_ok=True)

            task.status = TaskStatus.RUNNING
            self.state.set_tasks(list(self._tasks.values()))
            self.state.save()

            # Execute
            success = self._execute_task(task, step, inputs)

            if not success:
                task.status = TaskStatus.FAIL
                task.error_message = "Execution failed (non-zero exit code)"
                self.state.set_tasks(list(self._tasks.values()))
                self.state.save()
                continue

            # Validate: scan log for errors
            validation = self._validate_task(task, step)
            if validation.passed:
                task.status = TaskStatus.PASS
                logger.info("Task %s: PASS", tid)

                # Layer 2: check per-variant outputs
                self._check_variant_outputs(task, step, inputs)
            else:
                task.status = TaskStatus.FAIL
                task.error_message = validation.summary()
                logger.warning("Task %s: FAIL - %s", tid, task.error_message)

            self.state.set_tasks(list(self._tasks.values()))
            self.state.save()

    def _validate_task(self, task: Task, step: Step) -> ValidationResult:
        """Validate a completed task: check log for errors."""
        scanner = LogScanner(
            extra_patterns=step.get_log_error_patterns(),
            ignore_patterns=step.get_log_ignore_patterns(),
        )
        validator = OutputValidator(log_scanner=scanner)
        return validator.validate(
            output_path=task.output_dir,
            expected_files=[],
            log_path=task.log_path,
        )

    def _check_variant_outputs(
        self, task: Task, step: Step, inputs: Dict[str, Any]
    ) -> None:
        """Layer 2: check per-variant expected outputs after task passes."""
        if not step.variant_key:
            return

        variants = inputs.get(step.variant_key, [])
        if not isinstance(variants, list):
            return

        products = step.get_variant_products()
        merged_inputs = dict(inputs)
        merged_inputs["output_dir"] = task.output_dir

        variant_details = []
        for variant in variants:
            expected = step.get_expected_variant_outputs(variant, merged_inputs)
            for i, rel_path in enumerate(expected):
                product = products[i] if i < len(products) else rel_path
                full_path = os.path.join(task.output_dir, rel_path)
                ok = (
                    os.path.exists(full_path)
                    and os.path.getsize(full_path) > 0
                )
                msg = "" if ok else "missing or empty"
                variant_details.append(VariantDetail(
                    variant=variant,
                    product=product,
                    ok=ok,
                    message=msg,
                ))

        task.variant_details = variant_details

        # If any variant output is missing, downgrade task to FAIL
        if any(not d.ok for d in variant_details):
            task.status = TaskStatus.FAIL
            task.error_message = f"Variant output check: {task.variant_summary}"

    def get_tasks(self) -> Dict[str, Task]:
        return dict(self._tasks)

    def get_dag(self) -> DAGBuilder:
        return self.pipeline.dag

    def _summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self._tasks.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts
