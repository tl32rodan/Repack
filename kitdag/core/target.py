"""KitTarget - atomic unit of work in the kitdag pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TargetStatus(Enum):
    """Status of a kitdag target."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # kit/pvt not needed per current spec ("-" in summary)


@dataclass
class KitTarget:
    """Atomic unit of work: one kit at one PVT (or ALL for non-corner-based)."""

    kit_name: str
    pvt: str = "ALL"
    status: TargetStatus = TargetStatus.PENDING
    log_path: Optional[str] = None
    spec_hash: str = ""
    error_message: str = ""

    @property
    def id(self) -> str:
        return f"{self.kit_name}::{self.pvt}"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KitTarget):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        return f"KitTarget({self.id}, {self.status.value})"
