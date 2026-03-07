"""Pipeline configuration — parsed from input.yaml.

kitdag does NO input computation. This module simply loads the YAML
and structures it into typed dataclasses.

Template variables: string values in ``out`` fields may use ``{key}``
placeholders that reference any top-level YAML key (e.g. ``{output_root}``).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml


@dataclass
class StepConfig:
    """One step in the pipeline (parsed from input.yaml steps section)."""

    name: str
    run: str                            # kit template name
    inputs: Dict[str, Any] = field(default_factory=dict)
    output_dir: str = ""
    log_path: str = ""
    dependencies: List[str] = field(default_factory=list)


@dataclass
class PipelineConfig:
    """Parsed input.yaml — kitdag does no computation, just loads."""

    steps: Dict[str, StepConfig] = field(default_factory=dict)
    output_root: str = ""
    executor: str = "local"
    max_workers: int = 4


def _expand_vars(value: str, variables: Dict[str, str]) -> str:
    """Expand ``{key}`` placeholders in a string using variables dict."""
    def _replace(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return re.sub(r"\{(\w+)\}", _replace, value)


def load_pipeline(path: str) -> PipelineConfig:
    """Parse input.yaml into PipelineConfig.

    Template variables in ``out`` fields are expanded using top-level keys.

    Expected YAML structure::

        output_root: /data/output
        executor: local
        max_workers: 4

        steps:
          liberty:
            run: liberty
            in:
              ref_dir: /data/source/liberty
              pvts: [ss_0p75v_125c, tt_0p85v_25c]
              ...
            out:
              output_dir: "{output_root}/liberty"
              log: "{output_root}/liberty/liberty.log"
            dependencies: []
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"input.yaml must be a YAML mapping, got {type(raw)}")

    # Collect top-level string keys as template variables
    variables: Dict[str, str] = {}
    for key, val in raw.items():
        if isinstance(val, str):
            variables[key] = val
        elif isinstance(val, (int, float)):
            variables[key] = str(val)

    # Parse steps
    steps: Dict[str, StepConfig] = {}
    raw_steps = raw.get("steps", {})
    if isinstance(raw_steps, dict):
        for step_name, step_data in raw_steps.items():
            if not isinstance(step_data, dict):
                raise ValueError(f"Step '{step_name}' must be a mapping")

            out_section = step_data.get("out", {})
            output_dir = out_section.get("output_dir", "")
            log_path = out_section.get("log", "")

            # Expand template variables in out fields
            if isinstance(output_dir, str):
                output_dir = _expand_vars(output_dir, variables)
            if isinstance(log_path, str):
                log_path = _expand_vars(log_path, variables)

            # Expand template variables in input values (string only)
            raw_inputs = step_data.get("in", {})
            inputs = {}
            for k, v in raw_inputs.items():
                if isinstance(v, str):
                    inputs[k] = _expand_vars(v, variables)
                else:
                    inputs[k] = v

            steps[step_name] = StepConfig(
                name=step_name,
                run=step_data.get("run", step_name),
                inputs=inputs,
                output_dir=output_dir,
                log_path=log_path,
                dependencies=step_data.get("dependencies", []),
            )

    return PipelineConfig(
        steps=steps,
        output_root=raw.get("output_root", ""),
        executor=raw.get("executor", "local"),
        max_workers=raw.get("max_workers", 4),
    )
