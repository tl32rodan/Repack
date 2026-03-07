"""Kit base class for the kitdag pipeline.

Each kit is a self-contained unit of work in the DAG. Kits declare their
dependencies, define the command to run, and specify expected outputs.

The kit decides its own targets by overriding get_targets(). By default,
a single target with pvt="ALL" is created.

False-negative prevention:
  - get_expected_outputs(): kits MUST declare expected output files
  - get_log_error_patterns(): optional extra error patterns for log scanning
  - clean_output(): called BEFORE every re-run to prevent stale artifacts
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from kitdag.core.target import KitTarget

logger = logging.getLogger(__name__)


class Kit(ABC):
    """Base class for all kits in a kitdag pipeline.

    Each kit defines:
    - What targets it produces (override get_targets())
    - How to build each target (construct_command())
    - What output files to expect (get_expected_outputs())

    Subclasses MUST implement construct_command() and get_expected_outputs().
    Override get_targets() to produce multiple targets (e.g., one per PVT).
    """

    def __init__(self, name: str, dependencies: Optional[List[str]] = None):
        self.name = name
        self.dependencies: List[str] = dependencies or []

    @abstractmethod
    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        """Return the shell command to execute for this target."""

    @abstractmethod
    def get_expected_outputs(self, target: KitTarget, config: Any) -> List[str]:
        """Return list of expected output file paths (relative to output_path).

        Every kit MUST declare what files it expects to produce.
        The engine will verify all listed files exist and are non-empty
        before marking the target as PASS.

        Returns:
            List of relative file paths. Empty list = skip file check
            (but log scanning still runs).
        """

    def get_targets(self, config: Any) -> List[KitTarget]:
        """Return targets for this kit.

        Default: single target with pvt="ALL".
        Override to produce per-PVT or other multi-target expansions.
        """
        return [KitTarget(kit_name=self.name, pvt="ALL")]

    def get_output_path(self, config: Any) -> str:
        """Return the output directory for this kit's products."""
        return os.path.join(config.output_root, self.name)

    def get_log_error_patterns(self) -> List[str]:
        """Return extra regex patterns to scan for in log files.

        Default patterns (ERROR, FATAL, FAILED, etc.) are always scanned.
        Override this to add kit-specific patterns.
        """
        return []

    def get_log_ignore_patterns(self) -> List[str]:
        """Return regex patterns to IGNORE during log scanning.

        Some kits produce lines like "ERROR_COUNT: 0" that are not actual
        errors. Override to whitelist such patterns.
        """
        return []

    def clean_output(self, target: KitTarget, config: Any) -> None:
        """Clean output directory before re-run.

        Default implementation removes the target's output directory.
        Override for more surgical cleanup if needed.
        """
        output_path = self.get_output_path(config)
        if target.pvt != "ALL":
            output_path = os.path.join(output_path, target.pvt)

        if os.path.exists(output_path):
            logger.info("Cleaning output for %s: %s", target.id, output_path)
            shutil.rmtree(output_path)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"
