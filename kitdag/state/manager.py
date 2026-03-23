"""StateManager — persistent state tracking for scoped tasks."""

import csv
import logging
import os
from typing import Dict, List

from kitdag.core.task import Task, TaskStatus, VariantDetail

logger = logging.getLogger(__name__)


class StateManager:
    """Manages persistent CSV state for incremental runs.

    State file format (CSV):
        id,step_name,scope,status,input_hash,error_message,variant_details
        extract/lib=lib_a/branch=ss,extract,lib=lib_a;branch=ss,PASS,a1b2c3d4,,
        compile/lib=lib_a/branch=ss,compile,lib=lib_a;branch=ss,FAIL,9i8h7g6f,Variant check,ss_0p75v/.lib:OK;ss_0p75v/.db:FAIL
    """

    STATE_FILE = "kitdag_status.csv"
    FIELDS = ["id", "step_name", "scope", "status", "input_hash",
              "error_message", "variant_details"]

    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        self._state_path = os.path.join(work_dir, self.STATE_FILE)
        self._tasks: Dict[str, Task] = {}

    @property
    def state_path(self) -> str:
        return self._state_path

    def load(self) -> Dict[str, Task]:
        """Load state from CSV file. Returns empty dict if no file exists."""
        if not os.path.exists(self._state_path):
            logger.info("No existing state file found, starting fresh run")
            return {}

        loaded: Dict[str, Task] = {}
        with open(self._state_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tid = row["id"]
                scope = _parse_scope(row.get("scope", ""))
                variant_details = _parse_variant_details(
                    row.get("variant_details", "")
                )
                task = Task(
                    step_name=row.get("step_name", tid),
                    scope=scope,
                    status=TaskStatus(row.get("status", "PENDING")),
                    input_hash=row.get("input_hash", ""),
                    error_message=row.get("error_message", ""),
                    variant_details=variant_details,
                )
                loaded[tid] = task

        logger.info("Loaded %d tasks from state file", len(loaded))
        return loaded

    def set_tasks(self, tasks: List[Task]) -> None:
        """Set tasks directly."""
        self._tasks = {t.id: t for t in tasks}

    def get_tasks(self) -> Dict[str, Task]:
        return dict(self._tasks)

    def save(self) -> None:
        """Persist current state to CSV."""
        os.makedirs(self.work_dir, exist_ok=True)
        with open(self._state_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS)
            writer.writeheader()
            for tid in sorted(self._tasks):
                t = self._tasks[tid]
                writer.writerow({
                    "id": t.id,
                    "step_name": t.step_name,
                    "scope": _serialize_scope(t.scope),
                    "status": t.status.value,
                    "input_hash": t.input_hash,
                    "error_message": t.error_message,
                    "variant_details": _serialize_variant_details(
                        t.variant_details
                    ),
                })

    def summary(self) -> Dict[str, int]:
        """Return count of tasks by status."""
        counts: Dict[str, int] = {}
        for t in self._tasks.values():
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts


def _serialize_scope(scope: Dict[str, str]) -> str:
    if not scope:
        return ""
    return ";".join(f"{k}={v}" for k, v in sorted(scope.items()))


def _parse_scope(raw: str) -> Dict[str, str]:
    if not raw:
        return {}
    scope = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        scope[k] = v
    return scope


def _serialize_variant_details(details: List[VariantDetail]) -> str:
    if not details:
        return ""
    parts = []
    for d in details:
        status = "OK" if d.ok else "FAIL"
        parts.append(f"{d.variant}/{d.product}:{status}")
    return ";".join(parts)


def _parse_variant_details(raw: str) -> List[VariantDetail]:
    if not raw:
        return []
    details = []
    for part in raw.split(";"):
        if ":" not in part:
            continue
        key, status = part.rsplit(":", 1)
        if "/" in key:
            variant, product = key.split("/", 1)
        else:
            variant = key
            product = ""
        details.append(VariantDetail(
            variant=variant,
            product=product,
            ok=(status == "OK"),
        ))
    return details
