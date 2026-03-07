"""Kit base class — CWL CommandLineTool-like template.

Each kit is a declarative template that defines:
- inputs: what parameters it needs (KitInput)
- outputs: what it produces (KitOutput) — standardized as output_dir + log
- base_command + get_arguments(): how to build the shell command
- pvt_key: which input is the PVT array (for dashboard per-PVT expansion)
- get_expected_pvt_outputs(): per-PVT output files for validation

Kit runs ONCE with full inputs (including pvts as an array).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import yaml


@dataclass
class KitInput:
    """Declares a kit input parameter (mirrors CWL input)."""

    id: str
    type: str = "string"  # string, int, File, Directory, string[]
    doc: str = ""


@dataclass
class KitOutput:
    """Declares a kit output (mirrors CWL output)."""

    id: str
    type: str = "Directory"  # Directory, File
    doc: str = ""


class Kit(ABC):
    """Base class for all kits in a kitdag pipeline.

    Subclasses MUST implement ``get_arguments()``.
    Override ``get_expected_pvt_outputs()`` for per-PVT output validation.
    """

    name: str = ""
    inputs: List[KitInput] = []
    outputs: List[KitOutput] = []
    base_command: Union[str, List[str]] = ""
    pvt_key: Optional[str] = None  # which input holds the PVT array

    @abstractmethod
    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        """Build command-line arguments from resolved inputs dict.

        Args:
            inputs: Merged dict of step inputs + output_dir from step config.

        Returns:
            List of command-line argument strings.
        """

    def get_command(self, inputs: Dict[str, Any]) -> List[str]:
        """Full command = base_command + arguments."""
        if isinstance(self.base_command, str):
            cmd = [self.base_command] if self.base_command else []
        else:
            cmd = list(self.base_command)
        cmd.extend(str(a) for a in self.get_arguments(inputs))
        return cmd

    def get_expected_pvt_outputs(self, pvt: str, inputs: Dict[str, Any]) -> List[str]:
        """Expected output files for one PVT (relative to output_dir).

        Used by the dashboard for per-PVT status checking (layer 2).
        Return [] if this kit has no per-PVT outputs.
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

        Returns:
            List of error messages (empty = valid).
        """
        errors = []
        for inp in self.inputs:
            if inp.id not in inputs:
                errors.append(
                    f"Missing required input '{inp.id}' for kit '{self.name}'"
                )
        return errors

    def to_cwl(self) -> str:
        """Export this kit as a CWL v1.0 CommandLineTool YAML document."""
        cwl: Dict[str, Any] = {
            "cwlVersion": "v1.0",
            "class": "CommandLineTool",
            "baseCommand": self.base_command,
            "inputs": {},
            "outputs": {},
        }

        type_map = {
            "string": "string",
            "int": "int",
            "File": "File",
            "Directory": "Directory",
            "string[]": {"type": "array", "items": "string"},
        }

        for inp in self.inputs:
            cwl["inputs"][inp.id] = {
                "type": type_map.get(inp.type, "string"),
            }
            if inp.doc:
                cwl["inputs"][inp.id]["doc"] = inp.doc

        for out in self.outputs:
            cwl["outputs"][out.id] = {
                "type": type_map.get(out.type, "Directory"),
            }

        return yaml.dump(cwl, default_flow_style=False, sort_keys=False)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"
