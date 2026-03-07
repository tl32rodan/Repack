"""Configuration loader and Config dataclass."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from kitdag.core.spec import SpecCollection


# Fields that map directly to Config attributes (not sent to extra).
_KNOWN_FIELDS = {
    "library_name", "output_root", "upload_dest",
    "max_workers", "executor_type", "specs",
}


@dataclass
class Config:
    """Global configuration for a kitdag run.

    Only two domain fields are first-class: library_name and output_root.
    Everything else (pvts, cells, kit_options, source_lib, etc.) belongs
    in the ``extra`` catch-all dict and is accessed by individual kits.

    Attributes:
        library_name: Library identifier used for output naming and uploads.
        output_root: Root directory for all kit outputs.
        upload_dest: Upload root path. Each kit defines its own sub-structure.
        max_workers: Max parallel jobs for local executor.
        executor_type: "local" or "lsf".
        specs: SpecCollection holding per-kit specs for incremental detection.
        extra: Catch-all for domain-specific options (pvts, cells, etc.).
    """

    library_name: str = ""
    output_root: str = ""
    upload_dest: str = ""
    max_workers: int = 4
    executor_type: str = "local"
    specs: SpecCollection = field(default_factory=SpecCollection)
    extra: Dict[str, Any] = field(default_factory=dict)


def load_config(path: str) -> Config:
    """Load Config from a YAML file.

    Known fields (library_name, output_root, upload_dest, max_workers,
    executor_type) are mapped to Config attributes. The ``specs`` section
    is parsed into a SpecCollection. All other top-level keys are collected
    into ``config.extra``.

    Example YAML::

        library_name: my_lib_7nm_trimmed
        output_root: /path/to/output
        upload_dest: /release/my_lib_7nm_trimmed
        executor_type: local
        max_workers: 4
        specs:
          global:
            version: "1.0"
          kits:
            liberty:
              trim_mode: conservative
        extra:
          pvts: [ss_0p75v_125c, tt_0p85v_25c]
          cells: [INV_X1, NAND2_X1]
          source_lib: /data/source_libs/my_lib_7nm
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

    # Separate known fields from extra
    extra = raw.pop("extra", {})
    if not isinstance(extra, dict):
        extra = {}

    # Any unrecognised top-level keys also go into extra
    for key in list(raw.keys()):
        if key not in _KNOWN_FIELDS:
            extra[key] = raw.pop(key)

    config = Config(
        library_name=raw.get("library_name", ""),
        output_root=raw.get("output_root", ""),
        upload_dest=raw.get("upload_dest", ""),
        max_workers=raw.get("max_workers", 4),
        executor_type=raw.get("executor_type", "local"),
        specs=specs,
        extra=extra,
    )

    return config
