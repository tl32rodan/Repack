"""StateManager — persistent state tracking with input-hash change detection."""

import csv
import logging
import os
from typing import Dict, List

from kitdag.core.target import KitTarget, PvtStatus, TargetStatus

logger = logging.getLogger(__name__)


class StateManager:
    """Manages persistent CSV state for incremental runs.

    State file format (CSV):
        id,status,input_hash,error_message,pvt_details
        liberty,PASS,a1b2c3d4,,ss_0p75v_125c:OK;tt_0p85v_25c:OK
        timing_db,FAIL,9i8h7g6f,PVT check: 2/3,ss:OK;tt:MISSING;ff:OK
        lef,PASS,e5f6g7h8,,

    Incremental logic (handled by BaseEngine._reconcile_state):
        - PASS targets with unchanged input_hash: skip
        - PASS targets with changed input_hash: re-run
        - FAIL targets: re-run
        - PENDING targets: run
    """

    STATE_FILE = "kitdag_status.csv"
    FIELDS = ["id", "status", "input_hash", "error_message", "pvt_details"]

    def __init__(self, work_dir: str):
        self.work_dir = work_dir
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
                pvt_details = _parse_pvt_details(row.get("pvt_details", ""))
                target = KitTarget(
                    kit_name=tid,
                    status=TargetStatus(row.get("status", "PENDING")),
                    input_hash=row.get("input_hash", ""),
                    error_message=row.get("error_message", ""),
                    pvt_details=pvt_details,
                )
                loaded[tid] = target

        logger.info("Loaded %d targets from state file", len(loaded))
        return loaded

    def set_targets(self, targets: List[KitTarget]) -> None:
        """Set targets directly."""
        self._targets = {t.id: t for t in targets}

    def get_targets(self) -> Dict[str, KitTarget]:
        return dict(self._targets)

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
                    "input_hash": t.input_hash,
                    "error_message": t.error_message,
                    "pvt_details": _serialize_pvt_details(t.pvt_details),
                })

    def summary(self) -> Dict[str, int]:
        """Return count of targets by status."""
        counts: Dict[str, int] = {}
        for t in self._targets.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts


def _serialize_pvt_details(details: List[PvtStatus]) -> str:
    """Serialize PvtStatus list to string: 'ss:OK;tt:MISSING'."""
    if not details:
        return ""
    parts = []
    for p in details:
        status = "OK" if p.ok else "MISSING"
        parts.append(f"{p.pvt}:{status}")
    return ";".join(parts)


def _parse_pvt_details(raw: str) -> List[PvtStatus]:
    """Parse 'ss:OK;tt:MISSING' back into PvtStatus list."""
    if not raw:
        return []
    details = []
    for part in raw.split(";"):
        if ":" not in part:
            continue
        pvt, status = part.rsplit(":", 1)
        details.append(PvtStatus(pvt=pvt, ok=(status == "OK")))
    return details
