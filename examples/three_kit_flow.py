"""Three-kit repack flow example.

Demonstrates the two key dimensions of kit classification:
  1. corner-based vs non-corner-based
  2. dependency chain vs independent

Kit layout
----------

    Stage 1 (all run in parallel)          Stage 2
    ────────────────────────────────────   ──────────────────────────────────
    liberty::ss_0p75v_125c          ──────► timing_db::ss_0p75v_125c
    liberty::tt_0p85v_25c           ──────► timing_db::tt_0p85v_25c
    liberty::ff_0p99v_m40c          ──────► timing_db::ff_0p99v_m40c
    lef::ALL                               (no dependents)

  - liberty   CornerBasedKit  per-PVT timing library (.lib)   no dependencies
  - timing_db CornerBasedKit  per-PVT timing database (.db)   depends on liberty
  - lef       Kit             single layout file (.lef)        no dependencies

Usage
-----
Run the full pipeline:

    repack run examples/three_kit_config.yaml --script examples/three_kit_flow.py

Enable the GUI after execution:

    repack run examples/three_kit_config.yaml --script examples/three_kit_flow.py --gui

Inspect status without re-running:

    repack status /tmp/repack_demo_output

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

from repack.config import RepackConfig, load_config
from repack.core.kit import CornerBasedKit, Kit
from repack.core.target import KitTarget
from repack.engine.engine import RepackEngine
from repack.executor.local import LocalExecutor


# ---------------------------------------------------------------------------
# Kit A – LibertyKit
# Corner-based, no dependencies.
# Produces one .lib file per PVT corner.
# ---------------------------------------------------------------------------

class LibertyKit(CornerBasedKit):
    """Per-PVT timing liberty (.lib) file generator.

    Because this inherits from CornerBasedKit, ``get_targets()`` is
    implemented automatically: the engine will create one KitTarget per
    entry in ``config.pvts``, each with ``target.pvt`` set to that corner
    string (e.g. ``"ss_0p75v_125c"``).
    """

    def __init__(self):
        # No dependencies — this is a root node in the DAG.
        super().__init__(name="liberty", dependencies=[])

    def construct_command(self, target: KitTarget, config: RepackConfig):
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.lib")

        # --- real-world command (site-specific tool) ---
        # src = self.get_source_path(config)  # source_lib/liberty/
        # ref_file = os.path.join(src, target.pvt, f"{config.ref_lib}_{target.pvt}.lib")
        # return [
        #     "trim_liberty",
        #     "--ref", ref_file,
        #     "--cells", ",".join(config.cells),
        #     "--rename", f"{config.ref_lib}={config.library_name}",
        #     "--output", out_file,
        # ]

        # --- mock command: create the expected output file ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'liberty mock' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: RepackConfig):
        # Paths are relative to get_output_path(config).
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.lib")]

    def get_log_ignore_patterns(self):
        # Some liberty tools emit lines like "ERROR_COUNT: 0" that are not
        # real errors — whitelist them so log scanning doesn't flag them.
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit B – TimingDbKit
# Corner-based, depends on LibertyKit.
# Compiles the .lib produced by LibertyKit into a binary .db file.
# ---------------------------------------------------------------------------

class TimingDbKit(CornerBasedKit):
    """Per-PVT timing database (.db) compiler.

    Depends on ``liberty``.  Because both kits are corner-based, the DAG
    engine links targets of the **same PVT corner**:

        liberty::ss_0p75v_125c  ──►  timing_db::ss_0p75v_125c
        liberty::tt_0p85v_25c   ──►  timing_db::tt_0p85v_25c
        liberty::ff_0p99v_m40c  ──►  timing_db::ff_0p99v_m40c

    Each timing_db target waits only for its own corner's liberty file.
    """

    def __init__(self):
        super().__init__(name="timing_db", dependencies=["liberty"])

    def construct_command(self, target: KitTarget, config: RepackConfig):
        # Input: liberty output from the previous stage.
        lib_file = os.path.join(
            config.output_root, "liberty", target.pvt,
            f"{config.library_name}_{target.pvt}.lib",
        )
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.db")

        # Per-kit option from config.kit_options (optional override).
        flags = config.kit_options.get("timing_db", {}).get("compile_flags", "")

        # --- real-world command ---
        # return ["compile_lib", "--input", lib_file, "--output", out_file] + flags.split()

        # --- mock command ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'db mock {flags}' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: RepackConfig):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.db")]

    def get_log_error_patterns(self):
        # Flag tool-specific assertion failures that might not say "ERROR".
        return [r"compile_lib: assertion failed", r"Internal compiler error"]


# ---------------------------------------------------------------------------
# Kit C – LefKit
# Non-corner-based, no dependencies.
# Produces a single .lef file regardless of PVT corners.
# ---------------------------------------------------------------------------

class LefKit(Kit):
    """Single-target layout exchange format (.lef) file generator.

    Inherits from plain ``Kit`` (not ``CornerBasedKit``), so ``get_targets()``
    returns exactly one target with ``pvt="ALL"``.  This kit runs in parallel
    with LibertyKit during stage 1 — it has no dependencies and produces a
    corner-independent artefact.
    """

    def __init__(self):
        # No dependencies — independent of the liberty → timing_db chain.
        super().__init__(name="lef", dependencies=[])

    def construct_command(self, target: KitTarget, config: RepackConfig):
        out_dir = self.get_output_path(config)
        out_file = os.path.join(out_dir, f"{config.library_name}.lef")

        # --- real-world command ---
        # src = self.get_source_path(config)  # source_lib/lef/
        # ref_file = os.path.join(src, f"{config.ref_lib}.lef")
        # return [
        #     "trim_lef",
        #     "--ref", ref_file,
        #     "--cells", ",".join(config.cells),
        #     "--rename", f"{config.ref_lib}={config.library_name}",
        #     "--output", out_file,
        # ]

        # --- mock command ---
        return ["sh", "-c", f"mkdir -p {out_dir} && echo 'lef mock' > {out_file}"]

    def get_expected_outputs(self, target: KitTarget, config: RepackConfig):
        return [f"{config.library_name}.lef"]

    def get_log_ignore_patterns(self):
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit registration — entry point called by the engine
# ---------------------------------------------------------------------------

def register_kits(config: RepackConfig):
    """Return all kits for this repack flow.

    The engine discovers this function via ``importlib`` when invoked with
    ``--script examples/three_kit_flow.py``.  The returned list fully defines
    the DAG; dependencies are declared inside each kit's ``__init__``.
    """
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
        # Fallback: build config in-memory (no YAML needed).
        from repack.core.spec import SpecCollection
        specs = SpecCollection(global_spec={"cells_version": "2.1"})
        specs.set_kit_spec("liberty",  {"trim_mode": "conservative"})
        specs.set_kit_spec("timing_db",{"db_format": "2017.06"})
        specs.set_kit_spec("lef",      {"layer_version": "8.5"})

        config = RepackConfig(
            old_name="demo_lib",
            old_ver="7nm",
            new_name="demo_lib",
            new_ver="7nm_trimmed",
            library_name="demo_lib_7nm_trimmed",
            source_lib="/data/source_libs/demo_lib_7nm",
            output_root=tempfile.mkdtemp(prefix="repack_demo_"),
            pvts=["ss_0p75v_125c", "tt_0p85v_25c", "ff_0p99v_m40c"],
            cells=["INV_X1", "NAND2_X1", "BUF_X2"],
            kit_options={"timing_db": {"compile_flags": "-no_pg"}},
            max_workers=4,
            specs=specs,
        )

    kits = register_kits(config)
    executor = LocalExecutor(max_workers=config.max_workers)
    engine = RepackEngine(config=config, kits=kits, executor=executor, max_retries=3)

    print(f"Output root : {config.output_root}")
    print(f"Kits        : {[k.name for k in kits]}")
    print(f"PVTs        : {config.pvts}")
    print()

    success = engine.run()

    print()
    print("Summary:", engine.state.summary())
    print("Result :", "PASS" if success else "FAIL")
