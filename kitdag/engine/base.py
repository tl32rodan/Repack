"""BaseEngine — shared logic for all engine implementations.

Handles:
- Target creation (one per step, kit-level)
- Input validation against kit schemas
- DAG construction from step dependencies
- Incremental detection via input hash
- Cascade invalidation
- Per-PVT output checking (layer 2)
"""

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set

from kitdag.core.dag import DAGBuilder
from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget, PvtStatus, TargetStatus
from kitdag.core.validation import LogScanner, OutputValidator, ValidationResult
from kitdag.pipeline import PipelineConfig, StepConfig
from kitdag.state.manager import StateManager

logger = logging.getLogger(__name__)

DEFAULT_AUTO_RETRIES = 3


class InputHasher:
    """Compute deterministic hash of a target's resolved inputs."""

    @staticmethod
    def compute(inputs: Dict[str, Any]) -> str:
        canonical = json.dumps(inputs, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class BaseEngine(ABC):
    """Shared engine logic. Subclasses implement _execute_step()."""

    def __init__(
        self,
        pipeline: PipelineConfig,
        kits: Dict[str, Kit],
        max_retries: int = DEFAULT_AUTO_RETRIES,
    ):
        self.pipeline = pipeline
        self.kits = kits
        self.max_retries = max_retries
        self.state = StateManager(work_dir=pipeline.output_root)
        self.dag = DAGBuilder()
        self._targets: Dict[str, KitTarget] = {}

    @abstractmethod
    def _execute_step(self, target: KitTarget, kit: Kit, step: StepConfig) -> bool:
        """Execute a single step. Return True if command succeeded (exit 0)."""

    def run(self) -> bool:
        """Execute the full pipeline."""
        logger.info("=" * 60)
        logger.info("KitDAG Engine starting")
        logger.info("=" * 60)

        # 1. Validate all inputs
        errors = self._validate_all_inputs()
        if errors:
            for e in errors:
                logger.error("Validation: %s", e)
            return False

        # 2. Create targets (one per step)
        self._create_targets()

        # 3. Reconcile with existing state (incremental)
        self._reconcile_state()

        # 4. Cascade invalidation
        self._cascade_invalidation()

        # 5. Build DAG
        self._build_dag()

        # 6. Execute with auto-retry
        for attempt in range(self.max_retries + 1):
            pending = [
                tid for tid, t in self._targets.items()
                if t.status in (TargetStatus.PENDING, TargetStatus.FAIL)
            ]
            if not pending:
                logger.info("No pending targets, all done")
                break

            if attempt > 0:
                logger.info(
                    "Auto retry attempt %d/%d (%d targets)",
                    attempt, self.max_retries, len(pending),
                )
                self._cascade_invalidation()
                pending = [
                    tid for tid, t in self._targets.items()
                    if t.status in (TargetStatus.PENDING, TargetStatus.FAIL)
                ]
                if not pending:
                    break

            self._run_pending(pending)

            failed = [tid for tid, t in self._targets.items()
                      if t.status == TargetStatus.FAIL]
            if not failed:
                break
            logger.info("Attempt %d: %d targets failed", attempt + 1, len(failed))

        # 7. Summary
        summary = self._summary()
        logger.info("Final summary: %s", summary)

        all_passed = summary.get("FAIL", 0) == 0 and summary.get("PENDING", 0) == 0

        # 8. Save state
        self.state.save()

        return all_passed

    def _validate_all_inputs(self) -> List[str]:
        """Validate step inputs against kit schemas."""
        errors = []
        for step_name, step in self.pipeline.steps.items():
            kit = self.kits.get(step.run)
            if kit is None:
                errors.append(f"Step '{step_name}' references unknown kit '{step.run}'")
                continue
            kit_errors = kit.validate_inputs(step.inputs)
            errors.extend(kit_errors)
        return errors

    def _create_targets(self) -> None:
        """Create one KitTarget per step."""
        for step_name, step in self.pipeline.steps.items():
            input_hash = InputHasher.compute(step.inputs)
            target = KitTarget(
                kit_name=step_name,
                output_dir=step.output_dir,
                log_path=step.log_path,
                input_hash=input_hash,
            )
            self._targets[target.id] = target

        self.state.set_targets(list(self._targets.values()))
        logger.info("Created %d targets from %d steps",
                     len(self._targets), len(self.pipeline.steps))

    def _reconcile_state(self) -> None:
        """Reconcile with saved state for incremental runs."""
        existing = self.state.load()
        if not existing:
            return

        for tid, target in self._targets.items():
            old = existing.get(tid)
            if old is None:
                continue
            if old.status == TargetStatus.SKIP:
                target.status = TargetStatus.SKIP
            elif old.status == TargetStatus.PASS:
                if old.input_hash == target.input_hash:
                    target.status = TargetStatus.PASS
                    logger.debug("Target %s unchanged, keeping PASS", tid)
                else:
                    target.status = TargetStatus.PENDING
                    logger.info("Input changed for %s, marking PENDING", tid)
            elif old.status == TargetStatus.FAIL:
                target.status = TargetStatus.PENDING

        self.state.set_targets(list(self._targets.values()))

    def _build_dag(self) -> None:
        """Build DAG from step dependencies."""
        self.dag = DAGBuilder()
        self.dag.add_targets(list(self._targets.values()))
        kit_deps = {
            step_name: step.dependencies
            for step_name, step in self.pipeline.steps.items()
        }
        self.dag.build_edges(kit_deps)

    def _cascade_invalidation(self) -> None:
        """If upstream will re-run, mark downstream targets PENDING."""
        invalidated = {
            tid for tid, t in self._targets.items()
            if t.status in (TargetStatus.PENDING, TargetStatus.FAIL)
        }
        if not invalidated:
            return

        # Build temporary DAG
        dag = DAGBuilder()
        dag.add_targets(list(self._targets.values()))
        kit_deps = {
            step_name: step.dependencies
            for step_name, step in self.pipeline.steps.items()
        }
        dag.build_edges(kit_deps)

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
                    dep_target = self._targets.get(dependent)
                    if dep_target and dep_target.status == TargetStatus.PASS:
                        newly_invalidated.add(dependent)
                        logger.info("Cascade invalidation: %s → %s", tid, dependent)
                queue.append(dependent)

        for tid in newly_invalidated:
            self._targets[tid].status = TargetStatus.PENDING

        if newly_invalidated:
            self.state.set_targets(list(self._targets.values()))

    def _run_pending(self, pending_ids: List[str]) -> None:
        """Execute pending targets in topological order."""
        order = self.dag.topological_sort()
        to_run = set(pending_ids)

        for tid in order:
            if tid not in to_run:
                continue

            target = self._targets[tid]
            step = self.pipeline.steps.get(tid)
            kit = self.kits.get(step.run) if step else None
            if not step or not kit:
                target.status = TargetStatus.FAIL
                target.error_message = f"Kit '{step.run if step else tid}' not found"
                self.state.save()
                continue

            # Ensure output dir exists
            if target.output_dir:
                os.makedirs(target.output_dir, exist_ok=True)

            # Ensure log dir exists
            if target.log_path:
                os.makedirs(os.path.dirname(target.log_path), exist_ok=True)

            target.status = TargetStatus.RUNNING
            self.state.save()

            # Execute
            success = self._execute_step(target, kit, step)

            if not success:
                target.status = TargetStatus.FAIL
                target.error_message = "Execution failed (non-zero exit code)"
                self.state.save()
                continue

            # Validate: scan log for errors
            validation = self._validate_target(target, kit, step)
            if validation.passed:
                target.status = TargetStatus.PASS
                logger.info("Target %s: PASS", tid)

                # Layer 2: check per-PVT outputs
                self._check_pvt_outputs(target, kit, step)
            else:
                target.status = TargetStatus.FAIL
                target.error_message = validation.summary()
                logger.warning("Target %s: FAIL - %s", tid, target.error_message)

            self.state.save()

    def _validate_target(self, target: KitTarget, kit: Kit,
                         step: StepConfig) -> ValidationResult:
        """Validate a completed target: check log for errors."""
        scanner = LogScanner(
            extra_patterns=kit.get_log_error_patterns(),
            ignore_patterns=kit.get_log_ignore_patterns(),
        )
        validator = OutputValidator(log_scanner=scanner)

        # For the new model, we check output_dir is non-empty + log is clean
        expected_files = []  # Per-PVT check is in layer 2
        return validator.validate(
            output_path=target.output_dir,
            expected_files=expected_files,
            log_path=target.log_path,
        )

    def _check_pvt_outputs(self, target: KitTarget, kit: Kit,
                           step: StepConfig) -> None:
        """Layer 2: check per-PVT expected outputs after kit passes."""
        if not kit.pvt_key:
            return

        pvts = step.inputs.get(kit.pvt_key, [])
        if not isinstance(pvts, list):
            return

        # Merge inputs with output_dir for get_expected_pvt_outputs
        merged_inputs = dict(step.inputs)
        merged_inputs["output_dir"] = target.output_dir

        pvt_details = []
        for pvt in pvts:
            expected = kit.get_expected_pvt_outputs(pvt, merged_inputs)
            missing = []
            for f in expected:
                full_path = os.path.join(target.output_dir, f)
                if not os.path.exists(full_path) or os.path.getsize(full_path) == 0:
                    missing.append(f)

            pvt_details.append(PvtStatus(
                pvt=pvt,
                ok=len(missing) == 0,
                missing_files=missing,
            ))

        target.pvt_details = pvt_details

        # If any PVT output is missing, downgrade kit status to FAIL
        if any(not p.ok for p in pvt_details):
            target.status = TargetStatus.FAIL
            target.error_message = f"PVT output check: {target.pvt_summary}"

    def get_targets(self) -> Dict[str, KitTarget]:
        return dict(self._targets)

    def get_dag(self) -> DAGBuilder:
        return self.dag

    def _summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self._targets.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts
