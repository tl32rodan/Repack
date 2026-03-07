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
        old_name: Reference library name (e.g., "my_lib").
        old_ver: Reference library version (e.g., "1.0").
        new_name: Target library name (e.g., "my_lib").
        new_ver: Target library version (e.g., "2.0").
        library_name: Target library full name ({new_name}_{new_ver}).
            Used for renaming, uploading, output naming, and spec collection.
        source_lib: Path to pre-organized source folder (by kit type).
            Upstream copies reference library outputs here before repack runs.
            Structure: source_lib/{kit_name}/...
        output_root: Root directory for repack outputs.
        upload_dest: Upload root path. Each kit has its own upload structure.
        pvts: List of PVT corner strings (e.g., ["ss_0p75v_125c", "ff_0p99v_m40c"]).
        cells: List of cell names to include (empty = all cells).
        kit_options: Per-kit configuration overrides.
        max_workers: Max parallel jobs for local executor.
        executor_type: "local" or "lsf".
        specs: SpecCollection holding per-kit specs.
        extra: Catch-all for additional options.
    """

    # ── Library Identity ──
    old_name: str = ""
    old_ver: str = ""
    new_name: str = ""
    new_ver: str = ""
    library_name: str = ""

    # ── Paths ──
    source_lib: str = ""
    output_root: str = ""
    upload_dest: str = ""

    # ── What to Repack ──
    pvts: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)

    # ── Per-kit Control ──
    kit_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ── Execution ──
    max_workers: int = 4
    executor_type: str = "local"

    # ── Internals ──
    specs: SpecCollection = field(default_factory=SpecCollection)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def ref_lib(self) -> str:
        """Full reference library name: '{old_name}_{old_ver}'."""
        return f"{self.old_name}_{self.old_ver}" if self.old_ver else self.old_name


def load_config(path: str) -> RepackConfig:
    """Load RepackConfig from a YAML file.

    Example YAML:
        old_name: my_lib
        old_ver: "1.0"
        new_name: my_lib
        new_ver: "2.0"
        library_name: my_lib_2.0   # optional, auto-derived as {new_name}_{new_ver}
        source_lib: /data/source_libs/my_lib_1.0
        output_root: /path/to/output
        upload_dest: /release/my_lib_2.0
        pvts:
          - ss_0p75v_125c
          - tt_0p85v_25c
          - ff_0p99v_m40c
        cells:
          - INV
          - NAND2
        executor_type: lsf
        max_workers: 8
        kit_options:
          liberty:
            trim_mode: fast
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

    # Auto-derive library_name from new_name + new_ver if not provided
    new_name = raw.get("new_name", "")
    new_ver = raw.get("new_ver", "")
    library_name = raw.get("library_name", "")
    if not library_name and new_name:
        library_name = f"{new_name}_{new_ver}" if new_ver else new_name

    config = RepackConfig(
        old_name=raw.get("old_name", ""),
        old_ver=str(raw.get("old_ver", "")),
        new_name=new_name,
        new_ver=str(new_ver),
        library_name=library_name,
        source_lib=raw.get("source_lib", ""),
        output_root=raw.get("output_root", ""),
        upload_dest=raw.get("upload_dest", ""),
        pvts=raw.get("pvts", []),
        cells=raw.get("cells", []),
        kit_options=raw.get("kit_options", {}),
        max_workers=raw.get("max_workers", 4),
        executor_type=raw.get("executor_type", "local"),
        specs=specs,
        extra=raw.get("extra", {}),
    )

    return config
