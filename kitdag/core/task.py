"""Task — a concrete execution unit in the DAG.

Each Task represents one job: a (step, scope) combination.
Scope is a dict like {lib: "lib_a", branch: "ss"} identifying the variant.

Status model:
  Layer 1: task-level status (PASS/FAIL/PENDING/RUNNING/SKIP)
  Layer 2: per-variant output detail (e.g., per-PVT output products)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List


class TaskStatus(Enum):
    """Status of a task execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class VariantDetail:
    """Per-variant output check result (layer 2).

    For example, one PVT corner's output product status.
    """

    variant: str  # e.g., "ss_0p75v_125c"
    product: str  # e.g., ".lib", ".db"
    ok: bool = False
    message: str = ""

    def __repr__(self) -> str:
        status = "OK" if self.ok else f"FAIL({self.message})"
        return f"VariantDetail({self.variant}/{self.product}, {status})"


@dataclass
class Task:
    """One concrete execution unit: step + scope.

    Layer 1: task-level status (PASS/FAIL/PENDING/RUNNING)
    Layer 2: per-variant output detail in variant_details
    """

    step_name: str
    scope: Dict[str, str] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    log_path: str = ""
    output_dir: str = ""
    input_hash: str = ""
    error_message: str = ""
    variant_details: List[VariantDetail] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Unique ID: step_name or step_name/k1=v1/k2=v2."""
        if not self.scope:
            return self.step_name
        scope_str = "/".join(
            f"{k}={v}" for k, v in sorted(self.scope.items())
        )
        return f"{self.step_name}/{scope_str}"

    @property
    def lib(self) -> str:
        """Shortcut to scope['lib'], or '' if absent."""
        return self.scope.get("lib", "")

    @property
    def branch(self) -> str:
        """Shortcut to scope['branch'], or '' if absent."""
        return self.scope.get("branch", "")

    @property
    def variant_summary(self) -> str:
        """e.g. '8/9 OK' or ''."""
        if not self.variant_details:
            return ""
        ok = sum(1 for d in self.variant_details if d.ok)
        return f"{ok}/{len(self.variant_details)} OK"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        detail = f", {self.variant_summary}" if self.variant_details else ""
        return f"Task({self.id}, {self.status.value}{detail})"
