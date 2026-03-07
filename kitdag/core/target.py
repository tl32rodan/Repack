"""KitTarget — execution unit in the kitdag pipeline.

Each KitTarget represents one kit execution (runs once, not per-PVT).
Per-PVT output detail is tracked in PvtStatus for the dashboard.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class TargetStatus(Enum):
    """Status of a kit execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class PvtStatus:
    """Per-PVT output check result (dashboard layer 2)."""

    pvt: str
    ok: bool = False
    missing_files: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        status = "OK" if self.ok else f"MISSING({self.missing_files})"
        return f"PvtStatus({self.pvt}, {status})"


@dataclass
class KitTarget:
    """One kit execution (runs once with full inputs).

    Layer 1: kit-level status (PASS/FAIL/PENDING/RUNNING)
    Layer 2: per-PVT output detail in pvt_details (for dashboard expansion)
    """

    kit_name: str
    status: TargetStatus = TargetStatus.PENDING
    log_path: str = ""
    output_dir: str = ""
    input_hash: str = ""
    error_message: str = ""
    pvt_details: List[PvtStatus] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.kit_name

    @property
    def pvt_summary(self) -> str:
        """e.g. '3/3 PVTs OK' or '2/3 PVTs OK'."""
        if not self.pvt_details:
            return ""
        ok = sum(1 for p in self.pvt_details if p.ok)
        return f"{ok}/{len(self.pvt_details)} PVTs OK"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KitTarget):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        detail = f", {self.pvt_summary}" if self.pvt_details else ""
        return f"KitTarget({self.id}, {self.status.value}{detail})"
