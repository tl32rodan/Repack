"""Three-kit kitdag flow example.

Demonstrates:
  1. Per-PVT output kits vs single-output kits
  2. Dependency chains (timing_db depends on liberty)
  3. CWL-aligned kit definitions: get_arguments() + pvt_key + get_expected_pvt_outputs()

Kit layout (kit-level DAG)
--------------------------

    Stage 1 (parallel)       Stage 2
    ──────────────────      ──────────────────
    liberty ──────────────► timing_db
    lef                     (no dependents)

  - liberty    Per-PVT timing library (.lib)   no dependencies
  - timing_db  Per-PVT timing database (.db)   depends on liberty
  - lef        Single layout file (.lef)        no dependencies

Each kit runs ONCE with full pvts array. Per-PVT outputs are
checked after execution for the two-layer status model.

Usage
-----
Run the full pipeline:

    kitdag run examples/three_kit_config.yaml --kits examples/three_kit_flow.py

Enable the GUI after execution:

    kitdag run examples/three_kit_config.yaml --kits examples/three_kit_flow.py --gui

Inspect status without re-running:

    kitdag status /tmp/kitdag_demo_output

Notes
-----
The commands use plain ``sh -c`` calls to create placeholder output files.
In a real flow you would replace those with site-specific tools.
"""

import os
import sys

# Allow running this file directly from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitdag.core.kit import Kit, KitInput, KitOutput
from kitdag.core.target import KitTarget


# ---------------------------------------------------------------------------
# Kit A – LibertyKit
# Per-PVT output kit, no dependencies.
# Runs once, produces one .lib file per PVT corner.
# ---------------------------------------------------------------------------

class LibertyKit(Kit):
    """Per-PVT timing liberty (.lib) file generator."""

    name = "liberty"
    pvt_key = "pvts"

    inputs = [
        KitInput("ref_dir", type="Directory"),
        KitInput("old_name", type="string"),
        KitInput("library_name", type="string"),
        KitInput("pvts", type="string[]"),
        KitInput("cells", type="string[]"),
    ]

    outputs = [
        KitOutput("output_dir", type="Directory"),
        KitOutput("log", type="File"),
    ]

    base_command = "sh"

    def get_arguments(self, inputs):
        """Mock command: create per-PVT output files."""
        out_dir = inputs.get("output_dir", "")
        lib_name = inputs.get("library_name", "")
        pvts = inputs.get("pvts", [])

        cmds = []
        for pvt in pvts:
            pvt_dir = os.path.join(out_dir, pvt)
            out_file = os.path.join(pvt_dir, f"{lib_name}_{pvt}.lib")
            cmds.append(f"mkdir -p {pvt_dir} && echo 'liberty mock {pvt}' > {out_file}")

        return ["-c", " && ".join(cmds)]

    def get_expected_pvt_outputs(self, pvt, inputs):
        lib_name = inputs.get("library_name", "")
        return [f"{pvt}/{lib_name}_{pvt}.lib"]

    def get_log_ignore_patterns(self):
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit B – TimingDbKit
# Per-PVT output kit, depends on LibertyKit.
# Compiles .lib files into .db files.
# ---------------------------------------------------------------------------

class TimingDbKit(Kit):
    """Per-PVT timing database (.db) compiler."""

    name = "timing_db"
    pvt_key = "pvts"

    inputs = [
        KitInput("lib_dir", type="Directory"),
        KitInput("library_name", type="string"),
        KitInput("pvts", type="string[]"),
        KitInput("compile_flags", type="string"),
    ]

    outputs = [
        KitOutput("output_dir", type="Directory"),
        KitOutput("log", type="File"),
    ]

    base_command = "sh"

    def get_arguments(self, inputs):
        """Mock command: create per-PVT .db files."""
        out_dir = inputs.get("output_dir", "")
        lib_name = inputs.get("library_name", "")
        pvts = inputs.get("pvts", [])
        flags = inputs.get("compile_flags", "")

        cmds = []
        for pvt in pvts:
            pvt_dir = os.path.join(out_dir, pvt)
            out_file = os.path.join(pvt_dir, f"{lib_name}_{pvt}.db")
            cmds.append(f"mkdir -p {pvt_dir} && echo 'db mock {flags} {pvt}' > {out_file}")

        return ["-c", " && ".join(cmds)]

    def get_expected_pvt_outputs(self, pvt, inputs):
        lib_name = inputs.get("library_name", "")
        return [f"{pvt}/{lib_name}_{pvt}.db"]

    def get_log_error_patterns(self):
        return [r"compile_lib: assertion failed", r"Internal compiler error"]


# ---------------------------------------------------------------------------
# Kit C – LefKit
# Single-output kit, no dependencies, no PVT expansion.
# ---------------------------------------------------------------------------

class LefKit(Kit):
    """Single-target layout exchange format (.lef) file generator."""

    name = "lef"

    inputs = [
        KitInput("ref_dir", type="Directory"),
        KitInput("old_name", type="string"),
        KitInput("library_name", type="string"),
        KitInput("cells", type="string[]"),
    ]

    outputs = [
        KitOutput("output_dir", type="Directory"),
        KitOutput("log", type="File"),
    ]

    base_command = "sh"

    def get_arguments(self, inputs):
        """Mock command: create a single .lef file."""
        out_dir = inputs.get("output_dir", "")
        lib_name = inputs.get("library_name", "")
        out_file = os.path.join(out_dir, f"{lib_name}.lef")
        return ["-c", f"mkdir -p {out_dir} && echo 'lef mock' > {out_file}"]

    def get_log_ignore_patterns(self):
        return [r"ERROR_COUNT:\s*0"]


# ---------------------------------------------------------------------------
# Kit registration — entry point called by kit_loader
# ---------------------------------------------------------------------------

def register_kits(pipeline_config=None):
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
    from kitdag.pipeline import load_pipeline
    from kitdag.engine.local import LocalEngine

    cfg_path = os.path.join(os.path.dirname(__file__), "three_kit_config.yaml")
    pipeline = load_pipeline(cfg_path)

    kits_list = register_kits(pipeline)
    kits = {k.name: k for k in kits_list}

    print(f"Output root : {pipeline.output_root}")
    print(f"Kits        : {list(kits.keys())}")
    print(f"Steps       : {list(pipeline.steps.keys())}")
    print()

    engine = LocalEngine(pipeline=pipeline, kits=kits, max_retries=3)
    success = engine.run()

    print()
    print("Summary:", engine._summary())
    print("Result :", "PASS" if success else "FAIL")
