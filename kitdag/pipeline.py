"""Pipeline configuration — parsed from input.yaml.

kitdag does NO input computation. This module simply loads the YAML
and structures it into typed dataclasses.
"""

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


def load_pipeline(path: str) -> PipelineConfig:
    """Parse input.yaml into PipelineConfig.

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
              output_dir: /data/output/liberty
              log: /data/output/liberty/liberty.log
            dependencies: []
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"input.yaml must be a YAML mapping, got {type(raw)}")

    # Parse steps
    steps: Dict[str, StepConfig] = {}
    raw_steps = raw.get("steps", {})
    if isinstance(raw_steps, dict):
        for step_name, step_data in raw_steps.items():
            if not isinstance(step_data, dict):
                raise ValueError(f"Step '{step_name}' must be a mapping")

            out_section = step_data.get("out", {})
            steps[step_name] = StepConfig(
                name=step_name,
                run=step_data.get("run", step_name),
                inputs=step_data.get("in", {}),
                output_dir=out_section.get("output_dir", ""),
                log_path=out_section.get("log", ""),
                dependencies=step_data.get("dependencies", []),
            )

    return PipelineConfig(
        steps=steps,
        output_root=raw.get("output_root", ""),
        executor=raw.get("executor", "local"),
        max_workers=raw.get("max_workers", 4),
    )
