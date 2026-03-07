"""Three-kit kitdag flow example.

Demonstrates:
  1. Per-PVT kits vs single-target kits (Kit with custom get_targets())
  2. Dependency chains vs independent kits
  3. Domain data accessed via config.extra

Kit layout
----------

    Stage 1 (all run in parallel)          Stage 2
    ────────────────────────────────────   ──────────────────────────────────
    liberty::ss_0p75v_125c          ──────► timing_db::ss_0p75v_125c
    liberty::tt_0p85v_25c           ──────► timing_db::tt_0p85v_25c
    liberty::ff_0p99v_m40c          ──────► timing_db::ff_0p99v_m40c
    lef::ALL                               (no dependents)

  - liberty   per-PVT timing library (.lib)   no dependencies
  - timing_db per-PVT timing database (.db)   depends on liberty
  - lef       single layout file (.lef)        no dependencies

Usage
-----
Run the full pipeline:

    kitdag run examples/three_kit_config.yaml --script examples/three_kit_flow.py

Enable the GUI after execution:

    kitdag run examples/three_kit_config.yaml --script examples/three_kit_flow.py --gui

Inspect status without re-running:

    kitdag status /tmp/kitdag_demo_output

Notes
-----
The commands in construct_command() use plain ``sh -c`` calls to create
placeholder output files.  In a real flow you would replace those with your
site-specific tools (e.g. ``trim_liberty``, ``compile_lib``, ``trim_lef``).
The commented-out "real-world" command is shown next to each mock for clarity.
"""

import os
import sys

# Allow running this file directly from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitdag.config import Config, load_config
from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget
from kitdag.engine.engine import Engine
from kitdag.executor.local import LocalExecutor


# ---------------------------------------------------------------------------
# Kit A – LibertyKit
# Per-PVT kit, no dependencies.
# Produces one .lib file per PVT corner.
# ---------------------------------------------------------------------------

class LibertyKit(Kit):
    """Per-PVT timing liberty (.lib) file generator.

    Overrides ``get_targets()`` to produce one KitTarget per PVT corner
    from ``config.extra["pvts"]``.
    """

    def __init__(self):
        super().__init__(name="liberty", dependencies=[])

    def get_targets(self, config: Config):
        return [KitTarget(kit_name=self.name, pvt=pvt)
                for pvt in config.extra["pvts"]]

    def construct_command(self, target: KitTarget, config: Config):
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.lib")

        # --- real-world command (site-specific tool) ---
        # source_lib = config.extra["source_lib"]
        # cells = config.extra["cells"]
        # return [
        #     "trim_liberty",
        #     "--ref", os.path.join(source_lib, self.name, target.pvt, "ref.lib"),
        #     "--cells", ",".join(cells),
        #     "--output", out_file,
        # ]

        # --- mock command: create the expected output file ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'liberty mock' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: Config):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.lib")]

    def get_log_ignore_patterns(self):
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit B – TimingDbKit
# Per-PVT kit, depends on LibertyKit.
# Compiles the .lib produced by LibertyKit into a binary .db file.
# ---------------------------------------------------------------------------

class TimingDbKit(Kit):
    """Per-PVT timing database (.db) compiler.

    Depends on ``liberty``. The DAG engine links targets of the same PVT corner.
    """

    def __init__(self):
        super().__init__(name="timing_db", dependencies=["liberty"])

    def get_targets(self, config: Config):
        return [KitTarget(kit_name=self.name, pvt=pvt)
                for pvt in config.extra["pvts"]]

    def construct_command(self, target: KitTarget, config: Config):
        lib_file = os.path.join(
            config.output_root, "liberty", target.pvt,
            f"{config.library_name}_{target.pvt}.lib",
        )
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.db")

        kit_options = config.extra.get("kit_options", {})
        flags = kit_options.get("timing_db", {}).get("compile_flags", "")

        # --- mock command ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'db mock {flags}' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: Config):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.db")]

    def get_log_error_patterns(self):
        return [r"compile_lib: assertion failed", r"Internal compiler error"]


# ---------------------------------------------------------------------------
# Kit C – LefKit
# Single-target kit, no dependencies.
# Produces a single .lef file regardless of PVT corners.
# ---------------------------------------------------------------------------

class LefKit(Kit):
    """Single-target layout exchange format (.lef) file generator.

    Uses the default ``get_targets()`` which returns one target with pvt="ALL".
    """

    def __init__(self):
        super().__init__(name="lef", dependencies=[])

    def construct_command(self, target: KitTarget, config: Config):
        out_dir = self.get_output_path(config)
        out_file = os.path.join(out_dir, f"{config.library_name}.lef")

        # --- mock command ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'lef mock' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: Config):
        return [f"{config.library_name}.lef"]

    def get_log_ignore_patterns(self):
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit registration — entry point called by the engine
# ---------------------------------------------------------------------------

def register_kits(config: Config):
    """Return all kits for this kitdag flow."""
    return [
        LibertyKit(),
        TimingDbKit(),
        LefKit(),
    ]


# ---------------------------------------------------------------------------
# Standalone entry point — run directly with: python examples/three_kit_flow.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    cfg_path = os.path.join(os.path.dirname(__file__), "three_kit_config.yaml")

    if os.path.exists(cfg_path):
        config = load_config(cfg_path)
    else:
        from kitdag.core.spec import SpecCollection
        specs = SpecCollection(global_spec={"cells_version": "2.1"})
        specs.set_kit_spec("liberty",  {"trim_mode": "conservative"})
        specs.set_kit_spec("timing_db",{"db_format": "2017.06"})
        specs.set_kit_spec("lef",      {"layer_version": "8.5"})

        config = Config(
            library_name="demo_lib_7nm_trimmed",
            output_root=tempfile.mkdtemp(prefix="kitdag_demo_"),
            max_workers=4,
            specs=specs,
            extra={
                "pvts": ["ss_0p75v_125c", "tt_0p85v_25c", "ff_0p99v_m40c"],
                "cells": ["INV_X1", "NAND2_X1", "BUF_X2"],
                "source_lib": "/data/source_libs/demo_lib_7nm",
                "kit_options": {"timing_db": {"compile_flags": "-no_pg"}},
            },
        )

    kits = register_kits(config)
    executor = LocalExecutor(max_workers=config.max_workers)
    engine = Engine(config=config, kits=kits, executor=executor, max_retries=3)

    print(f"Output root : {config.output_root}")
    print(f"Kits        : {[k.name for k in kits]}")
    print(f"PVTs        : {config.extra.get('pvts', [])}")
    print()

    success = engine.run()

    print()
    print("Summary:", engine.state.summary())
    print("Result :", "PASS" if success else "FAIL")
