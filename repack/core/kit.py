"""Kit base classes for repack pipeline.

Two dimensions:
  1. CornerBasedKit (per-PVT targets) vs Kit (single ALL target)
  2. BinaryKitMixin (needs spec modification + utility re-run) vs plain text kits

False-negative prevention:
  - get_expected_outputs(): kits MUST declare expected output files
  - get_log_error_patterns(): optional extra error patterns for log scanning
  - clean_output(): called BEFORE every re-run to prevent stale artifacts
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from repack.core.target import KitTarget

logger = logging.getLogger(__name__)


class Kit(ABC):
    """Base class for non-corner-based kits (one target per library).

    Subclass this for kits that produce a single set of outputs
    regardless of PVT corners.

    IMPORTANT: Subclasses MUST implement get_expected_outputs() to enable
    output completeness validation. Returning [] disables file-level
    validation but log scanning still runs.
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

        This is the primary defense against false-negative problem #1:
        "output is incomplete but status shows O".

        Every kit MUST declare what files it expects to produce.
        The engine will verify all listed files exist and are non-empty
        before marking the target as PASS.

        Returns:
            List of relative file paths. Empty list = skip file check
            (but log scanning still runs).
        """

    def get_targets(self, config: Any) -> List[KitTarget]:
        """Return targets for this kit. Default: single ALL target."""
        return [KitTarget(kit_name=self.name, pvt="ALL")]

    def get_source_path(self, config: Any) -> str:
        """Return the source directory for this kit's inputs.

        Default: {source_lib}/{kit_name}
        Override for kits with non-standard source layout.
        """
        return os.path.join(config.source_lib, self.name)

    def get_output_path(self, config: Any) -> str:
        """Return the output directory for this kit's products."""
        return os.path.join(config.output_root, self.name)

    def get_log_error_patterns(self) -> List[str]:
        """Return extra regex patterns to scan for in log files.

        Defense against false-negative problem #2:
        "log has ERROR but status shows O".

        Default patterns (ERROR, FATAL, FAILED, etc.) are always scanned.
        Override this to add kit-specific patterns.

        Returns:
            List of regex pattern strings.
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

        Defense against false-negative problem #4:
        "stale artifacts from previous run remain in output".

        Default implementation removes the entire output directory.
        Override for more surgical cleanup if needed.
        """
        output_path = self.get_output_path(config)
        if target.pvt != "ALL":
            # Corner-based: only clean the PVT subdirectory
            output_path = os.path.join(output_path, target.pvt)

        if os.path.exists(output_path):
            logger.info("Cleaning output for %s: %s", target.id, output_path)
            shutil.rmtree(output_path)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"


class CornerBasedKit(Kit):
    """Kit that produces per-PVT outputs.

    Each PVT corner generates a separate target. The flow may run
    these sequentially or in parallel.
    """

    def get_targets(self, config: Any) -> List[KitTarget]:
        """Expand targets across all PVT corners from config."""
        return [
            KitTarget(kit_name=self.name, pvt=pvt)
            for pvt in config.pvts
        ]


class BinaryKitMixin:
    """Mixin for binary kits (pgv, apl, etc.) that need spec modification.

    Binary kits cannot be directly text-edited. Instead:
    1. Modify the config/spec to trim content
    2. Re-run the kit's generation utility

    Subclass should also inherit from Kit or CornerBasedKit.
    """

    @abstractmethod
    def get_trimmed_spec(self, target: KitTarget, config: Any) -> Dict[str, Any]:
        """Return the modified spec for this binary kit."""

    @abstractmethod
    def get_utility_command(self, target: KitTarget, config: Any,
                            spec_path: str) -> List[str]:
        """Return the command to re-run the generation utility."""

    def construct_command(self, target: KitTarget, config: Any) -> List[str]:
        """For binary kits, construct_command delegates to the utility flow."""
        import json

        spec = self.get_trimmed_spec(target, config)
        spec_dir = os.path.join(config.output_root, self.name, ".specs")  # type: ignore
        os.makedirs(spec_dir, exist_ok=True)
        spec_path = os.path.join(spec_dir, f"{target.id.replace('::', '_')}_spec.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        return self.get_utility_command(target, config, spec_path)
