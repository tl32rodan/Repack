"""Configuration loader and RepackConfig dataclass."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from repack.core.spec import SpecCollection


@dataclass
class RepackConfig:
    """Global configuration for a repack run.

    Attributes:
        library_name: Name of the reference library being repacked.
        ref_library_path: Path to the reference library.
        output_root: Root directory for repack outputs.
        pvts: List of PVT corner strings (e.g., ["ss_0p75v_125c", "ff_0p99v_m40c"]).
        cells: List of cell names to include (empty = all cells).
        rename_map: Mapping of old names to new names for renaming.
        kit_options: Per-kit configuration overrides.
        debug: If True, skip upload step.
        max_workers: Max parallel jobs for local executor.
        executor_type: "local" or "lsf".
        upload_dest: Destination path for upload (cp).
        specs: SpecCollection holding per-kit specs.
        extra: Catch-all for additional options.
    """

    library_name: str = ""
    ref_library_path: str = ""
    output_root: str = ""
    pvts: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)
    rename_map: Dict[str, str] = field(default_factory=dict)
    kit_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    debug: bool = False
    max_workers: int = 4
    executor_type: str = "local"
    upload_dest: str = ""
    specs: SpecCollection = field(default_factory=SpecCollection)
    extra: Dict[str, Any] = field(default_factory=dict)


def load_config(path: str) -> RepackConfig:
    """Load RepackConfig from a YAML file.

    Example YAML:
        library_name: my_lib_7nm
        ref_library_path: /path/to/ref
        output_root: /path/to/output
        pvts:
          - ss_0p75v_125c
          - tt_0p85v_25c
          - ff_0p99v_m40c
        cells:
          - INV
          - NAND2
        rename_map:
          old_lib_name: new_lib_name
        debug: false
        executor_type: lsf
        max_workers: 8
        upload_dest: /release/path
        kit_options:
          liberty:
            extra_flag: value
        specs:
          global:
            some_global_param: value
          kits:
            liberty:
              trim_param: true
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping, got {type(raw)}")

    # Build SpecCollection from specs section
    specs = SpecCollection()
    specs_raw = raw.pop("specs", {})
    if isinstance(specs_raw, dict):
        global_spec = specs_raw.get("global", {})
        if global_spec:
            specs = SpecCollection(global_spec=global_spec)
        kit_specs = specs_raw.get("kits", {})
        if isinstance(kit_specs, dict):
            for kit_name, kit_spec in kit_specs.items():
                specs.set_kit_spec(kit_name, kit_spec)

    config = RepackConfig(
        library_name=raw.get("library_name", ""),
        ref_library_path=raw.get("ref_library_path", ""),
        output_root=raw.get("output_root", ""),
        pvts=raw.get("pvts", []),
        cells=raw.get("cells", []),
        rename_map=raw.get("rename_map", {}),
        kit_options=raw.get("kit_options", {}),
        debug=raw.get("debug", False),
        max_workers=raw.get("max_workers", 4),
        executor_type=raw.get("executor_type", "local"),
        upload_dest=raw.get("upload_dest", ""),
        specs=specs,
        extra=raw.get("extra", {}),
    )

    return config
