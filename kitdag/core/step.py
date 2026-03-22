"""Step — a reusable command template (was Kit).

Each step defines:
- base_command + get_arguments(): how to build the shell command
- inputs/outputs declarations
- variant_key: which input holds the variant array (for per-PVT checking)
- get_expected_variant_outputs(): per-variant expected output products
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


@dataclass
class StepInput:
    """Declares a step input parameter."""

    id: str
    type: str = "string"  # string, int, File, Directory, string[]
    doc: str = ""


@dataclass
class StepOutput:
    """Declares a step output."""

    id: str
    type: str = "Directory"  # Directory, File
    doc: str = ""


class Step(ABC):
    """Base class for all steps in a kitdag pipeline.

    Subclasses MUST implement ``get_arguments()``.
    Override ``get_expected_variant_outputs()`` for per-variant output checking.
    """

    name: str = ""
    inputs: List[StepInput] = []
    outputs: List[StepOutput] = []
    base_command: Union[str, List[str]] = ""
    variant_key: Optional[str] = None  # which input holds variant array (e.g., "pvts")

    @abstractmethod
    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        """Build command-line arguments from resolved inputs dict."""

    def get_command(self, inputs: Dict[str, Any]) -> List[str]:
        """Full command = base_command + arguments."""
        if isinstance(self.base_command, str):
            cmd = [self.base_command] if self.base_command else []
        else:
            cmd = list(self.base_command)
        cmd.extend(str(a) for a in self.get_arguments(inputs))
        return cmd

    def get_expected_variant_outputs(
        self, variant: str, inputs: Dict[str, Any]
    ) -> List[str]:
        """Expected output files for one variant (relative to output_dir).

        Returns list of (product_name, relative_path) or just relative_paths.
        Used for per-variant output checking (layer 2 detail).
        Return [] if this step has no per-variant outputs.
        """
        return []

    def get_variant_products(self) -> List[str]:
        """Names of output products per variant (e.g., ['.lib', '.db', '.sdf']).

        Used by the GUI to create sub-table column headers.
        """
        return []

    def get_log_error_patterns(self) -> List[str]:
        """Extra regex patterns to scan for in log files."""
        return []

    def get_log_ignore_patterns(self) -> List[str]:
        """Regex patterns to ignore during log scanning."""
        return []

    def validate_inputs(self, inputs: Dict[str, Any]) -> List[str]:
        """Validate that all required inputs are provided.

        Returns list of error messages (empty = valid).
        """
        errors = []
        for inp in self.inputs:
            if inp.id not in inputs:
                errors.append(
                    f"Missing required input '{inp.id}' for step '{self.name}'"
                )
        return errors

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"
