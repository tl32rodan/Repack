"""StateManager - persistent state tracking with spec-hash change detection."""

import csv
import logging
import os
from typing import Callable, Dict, List, Optional

from repack.core.target import KitTarget, TargetStatus
from repack.core.spec import SpecCollection

logger = logging.getLogger(__name__)


class StateManager:
    """Manages persistent CSV state for incremental runs.

    State file format (CSV):
        id,status,spec_hash,error_message
        KitA::ss_100c,PASS,a1b2c3d4e5f6g7h8,
        KitB::ALL,FAIL,9i8h7g6f5e4d3c2b,Error in step 3

    Incremental logic:
        - PASS targets with unchanged spec_hash: skip
        - PASS targets with changed spec_hash: re-run (mark PENDING)
        - FAIL targets: re-run
        - PENDING targets: run
        - SKIP targets: skip (not needed per spec)
    """

    STATE_FILE = "repack_status.csv"
    FIELDS = ["id", "status", "spec_hash", "error_message"]

    def __init__(self, work_dir: str, specs: Optional[SpecCollection] = None):
        self.work_dir = work_dir
        self.specs = specs
        self._state_path = os.path.join(work_dir, self.STATE_FILE)
        self._targets: Dict[str, KitTarget] = {}

    @property
    def state_path(self) -> str:
        return self._state_path

    def load(self) -> Dict[str, KitTarget]:
        """Load state from CSV file. Returns empty dict if no file exists."""
        if not os.path.exists(self._state_path):
            logger.info("No existing state file found, starting fresh run")
            return {}

        loaded: Dict[str, KitTarget] = {}
        with open(self._state_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tid = row["id"]
                parts = tid.split("::", 1)
                kit_name = parts[0]
                pvt = parts[1] if len(parts) > 1 else "ALL"
                target = KitTarget(
                    kit_name=kit_name,
                    pvt=pvt,
                    status=TargetStatus(row.get("status", "PENDING")),
                    spec_hash=row.get("spec_hash", ""),
                    error_message=row.get("error_message", ""),
                )
                loaded[tid] = target

        logger.info("Loaded %d targets from state file", len(loaded))
        return loaded

    def reconcile(self, new_targets: List[KitTarget]) -> List[KitTarget]:
        """Reconcile new targets with existing state for incremental runs.

        Returns the list of targets with updated statuses:
        - New targets: PENDING
        - Previously PASS + spec unchanged: keep PASS (will be skipped)
        - Previously PASS + spec changed: mark PENDING (will re-run)
        - Previously FAIL: mark PENDING (will re-run)
        - Previously SKIP: keep SKIP
        """
        existing = self.load()

        reconciled: List[KitTarget] = []
        for target in new_targets:
            old = existing.get(target.id)
            if old is None:
                target.status = TargetStatus.PENDING
                logger.debug("New target %s -> PENDING", target.id)
            elif old.status == TargetStatus.SKIP:
                target.status = TargetStatus.SKIP
            elif old.status == TargetStatus.PASS:
                if self.specs and self.specs.has_changed(target.kit_name, old.spec_hash):
                    target.status = TargetStatus.PENDING
                    logger.info(
                        "Spec changed for %s (hash %s -> %s), marking PENDING",
                        target.id, old.spec_hash,
                        self.specs.compute_hash(target.kit_name),
                    )
                else:
                    target.status = TargetStatus.PASS
                    target.spec_hash = old.spec_hash
                    logger.debug("Target %s unchanged, keeping PASS", target.id)
            elif old.status == TargetStatus.FAIL:
                target.status = TargetStatus.PENDING
                logger.info("Previously failed target %s -> PENDING", target.id)
            else:
                target.status = TargetStatus.PENDING

            reconciled.append(target)

        self._targets = {t.id: t for t in reconciled}
        return reconciled

    def update_status(self, target_id: str, status: TargetStatus,
                      error_message: str = "") -> None:
        """Update status of a single target and persist."""
        if target_id in self._targets:
            self._targets[target_id].status = status
            self._targets[target_id].error_message = error_message
            if status == TargetStatus.PASS and self.specs:
                kit_name = target_id.split("::")[0]
                self._targets[target_id].spec_hash = self.specs.compute_hash(kit_name)
            self.save()

    def mark_running(self, target_id: str) -> None:
        self.update_status(target_id, TargetStatus.RUNNING)

    def mark_pass(self, target_id: str) -> None:
        self.update_status(target_id, TargetStatus.PASS)

    def mark_fail(self, target_id: str, error: str = "") -> None:
        self.update_status(target_id, TargetStatus.FAIL, error)

    def set_targets(self, targets: List[KitTarget]) -> None:
        """Set targets directly (for fresh runs without reconciliation)."""
        self._targets = {t.id: t for t in targets}

    def get_targets(self) -> Dict[str, KitTarget]:
        return dict(self._targets)

    def get_pending_targets(self) -> List[str]:
        """Return IDs of targets that need to run."""
        return [
            tid for tid, t in self._targets.items()
            if t.status in (TargetStatus.PENDING, TargetStatus.FAIL)
        ]

    def save(self) -> None:
        """Persist current state to CSV."""
        os.makedirs(self.work_dir, exist_ok=True)
        with open(self._state_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS)
            writer.writeheader()
            for tid in sorted(self._targets):
                t = self._targets[tid]
                writer.writerow({
                    "id": t.id,
                    "status": t.status.value,
                    "spec_hash": t.spec_hash,
                    "error_message": t.error_message,
                })

    def summary(self) -> Dict[str, int]:
        """Return count of targets by status."""
        counts: Dict[str, int] = {}
        for t in self._targets.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts
