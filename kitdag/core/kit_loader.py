"""Kit loader — load kit definitions from Python scripts or YAML files."""

import importlib.util
import logging
from typing import Any, Dict, List, Optional

import yaml

from kitdag.core.kit import Kit, KitInput, KitOutput

logger = logging.getLogger(__name__)


class YamlKit(Kit):
    """Kit loaded from a YAML definition file.

    The YAML arguments section is used to build the command line.
    """

    def __init__(
        self,
        name: str,
        inputs: List[KitInput],
        outputs: List[KitOutput],
        base_command,
        arguments: List[Dict[str, Any]],
        pvt_key: Optional[str] = None,
        expected_pvt_outputs: Optional[Dict[str, str]] = None,
        log_error_patterns: Optional[List[str]] = None,
        log_ignore_patterns: Optional[List[str]] = None,
    ):
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        self.base_command = base_command
        self.pvt_key = pvt_key
        self._arguments = arguments
        self._expected_pvt_pattern = (expected_pvt_outputs or {}).get("pattern", "")
        self._log_error_patterns = log_error_patterns or []
        self._log_ignore_patterns = log_ignore_patterns or []

    def get_arguments(self, inputs: Dict[str, Any]) -> List[str]:
        args = []
        for arg_def in self._arguments:
            prefix = arg_def.get("prefix", "")
            value_from = arg_def.get("valueFrom", "")
            separator = arg_def.get("itemSeparator", None)

            # Resolve valueFrom: "inputs.ref_dir" → inputs["ref_dir"]
            value = value_from
            if value_from.startswith("inputs."):
                key = value_from[len("inputs."):]
                value = inputs.get(key, "")
            elif value_from.startswith("outputs."):
                key = value_from[len("outputs."):]
                value = inputs.get(key, "")

            # Handle array values with separator
            if isinstance(value, list) and separator:
                value = separator.join(str(v) for v in value)
            elif isinstance(value, list):
                value = " ".join(str(v) for v in value)

            if prefix:
                args.extend([prefix, str(value)])
            else:
                args.append(str(value))

        return args

    def get_expected_pvt_outputs(self, pvt: str, inputs: Dict[str, Any]) -> List[str]:
        if not self._expected_pvt_pattern:
            return []
        # Simple substitution: {pvt} and any {input_key}
        pattern = self._expected_pvt_pattern.replace("{pvt}", pvt)
        for key, val in inputs.items():
            if isinstance(val, str):
                pattern = pattern.replace(f"{{{key}}}", val)
        return [pattern]

    def get_log_error_patterns(self) -> List[str]:
        return self._log_error_patterns

    def get_log_ignore_patterns(self) -> List[str]:
        return self._log_ignore_patterns


def load_kit_yaml(path: str) -> Kit:
    """Load a kit definition from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or raw.get("class") != "Kit":
        raise ValueError(f"Invalid kit YAML: {path}")

    inputs = []
    for inp_id, inp_def in raw.get("inputs", {}).items():
        if isinstance(inp_def, dict):
            inputs.append(KitInput(
                id=inp_id,
                type=inp_def.get("type", "string"),
                doc=inp_def.get("doc", ""),
            ))
        else:
            inputs.append(KitInput(id=inp_id, type=str(inp_def)))

    outputs = []
    for out_id, out_def in raw.get("outputs", {}).items():
        if isinstance(out_def, dict):
            outputs.append(KitOutput(
                id=out_id,
                type=out_def.get("type", "Directory"),
                doc=out_def.get("doc", ""),
            ))
        else:
            outputs.append(KitOutput(id=out_id))

    return YamlKit(
        name=raw.get("name", ""),
        inputs=inputs,
        outputs=outputs,
        base_command=raw.get("baseCommand", ""),
        arguments=raw.get("arguments", []),
        pvt_key=raw.get("pvtKey"),
        expected_pvt_outputs=raw.get("expectedPvtOutputs"),
        log_error_patterns=raw.get("logErrorPatterns"),
        log_ignore_patterns=raw.get("logIgnorePatterns"),
    )


def load_kits_from_script(script_path: str, pipeline_config=None) -> List[Kit]:
    """Load kit definitions from a Python script.

    The script should define a ``register_kits(config)`` function
    that returns a list of Kit instances.
    """
    if not script_path:
        return []

    spec = importlib.util.spec_from_file_location("kit_defs", script_path)
    if spec is None or spec.loader is None:
        logger.error("Cannot load kit script: %s", script_path)
        return []

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "register_kits"):
        return module.register_kits(pipeline_config)
    else:
        logger.warning("%s has no register_kits() function", script_path)
        return []
