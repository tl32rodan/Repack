"""AP Characterization flow example.

Demonstrates:
  - Multi-lib, multi-branch pipeline
  - Cross-branch dependencies (step6/corner depends on step5/{corner,em,lvl,lvf})
  - Intra-step branch deps (step6/em,lvl,lvf depend on step6/corner)
  - Fan-in (merge waits for all branches)
  - Per-PVT variant output checking
  - Mermaid DAG visualization

Flow:
  extract → char → compile → merge → upload
                 ↘ (step6 intra-step: corner → em/lvl/lvf)

Usage:
  # Visualize abstract DAG
  kitdag viz examples/ap_char_flow.py

  # Visualize concrete DAG for one lib
  kitdag viz examples/ap_char_flow.py --lib lib_7nm_hd

  # Run the pipeline
  kitdag run examples/ap_char_flow.py

  # Run + launch GUI
  kitdag run examples/ap_char_flow.py --gui
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitdag.core.flow import Flow
from kitdag.core.step import Step, StepInput, StepOutput


# ─── Step definitions ────────────────────────────────────────────────

class ExtractStep(Step):
    """Extract source library data per branch."""

    name = "extract"
    base_command = "sh"
    inputs = [StepInput("library_name"), StepInput("branch")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        branch = inputs.get("branch", "")
        out = os.path.join(out_dir, f"{lib}_{branch}.dat")
        return ["-c", f"mkdir -p {out_dir} && echo 'extracted {lib}/{branch}' > {out}"]


class CharStep(Step):
    """Run characterization per branch."""

    name = "char"
    base_command = "sh"
    inputs = [StepInput("library_name"), StepInput("branch")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        branch = inputs.get("branch", "")
        out = os.path.join(out_dir, f"{lib}_{branch}_char.dat")
        return ["-c", f"mkdir -p {out_dir} && echo 'char {lib}/{branch}' > {out}"]


class CompileStep(Step):
    """Compile outputs per branch with per-PVT output checking."""

    name = "compile"
    base_command = "sh"
    variant_key = "pvts"
    inputs = [
        StepInput("library_name"),
        StepInput("branch"),
        StepInput("pvts", type="string[]"),
    ]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        pvts = inputs.get("pvts", [])
        cmds = []
        for pvt in pvts:
            pvt_dir = os.path.join(out_dir, pvt)
            cmds.append(
                f"mkdir -p {pvt_dir} "
                f"&& echo 'lib {lib}' > {pvt_dir}/{lib}_{pvt}.lib "
                f"&& echo 'db {lib}' > {pvt_dir}/{lib}_{pvt}.db"
            )
        return ["-c", " && ".join(cmds)] if cmds else ["-c", "true"]

    def get_expected_variant_outputs(self, variant, inputs):
        lib = inputs.get("library_name", "")
        return [
            f"{variant}/{lib}_{variant}.lib",
            f"{variant}/{lib}_{variant}.db",
        ]

    def get_variant_products(self):
        return [".lib", ".db"]


class MergeStep(Step):
    """Merge all branch results per lib."""

    name = "merge"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        out = os.path.join(out_dir, f"{lib}_merged.dat")
        return ["-c", f"mkdir -p {out_dir} && echo 'merged {lib}' > {out}"]


class UploadStep(Step):
    """Upload merged results."""

    name = "upload"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        out = os.path.join(out_dir, f"{lib}_uploaded.flag")
        return ["-c", f"mkdir -p {out_dir} && echo 'uploaded {lib}' > {out}"]


# ─── Flow definition (fixed per domain) ─────────────────────────────

flow = Flow("ap_char")

flow.add_step("extract", kit=ExtractStep())
flow.add_step("char",    kit=CharStep())
flow.add_step("compile", kit=CompileStep())
flow.add_step("merge",   kit=MergeStep())
flow.add_step("upload",  kit=UploadStep())

# Same-branch dependencies
flow.add_dep("char",    on="extract")
flow.add_dep("compile", on="char")

# Cross-branch: compile/corner needs char/{corner, em, lvl, lvf}
flow.add_dep("compile", on="char", branch_map={
    "corner": ["corner", "em", "lvl", "lvf"],
})

# Intra-step: compile/em,lvl,lvf must wait for compile/corner
flow.add_dep("compile", on="compile", branch_map={
    "em":  ["corner"],
    "lvl": ["corner"],
    "lvf": ["corner"],
})

# Fan-in: merge waits for all branches
flow.add_dep("merge", on="compile")

# merge → upload
flow.add_dep("upload", on="merge")


# ─── User-provided expansion functions ───────────────────────────────

# Libraries to process
libs = ["lib_7nm_hd", "lib_7nm_hc"]

# Output root
output_root = "/tmp/kitdag_ap_output"


def get_branches(lib: str, step_name: str) -> list:
    """Which branches to run for each (lib, step).

    Different libs may have different branch sets.
    Per-lib steps (merge, upload) return [].
    """
    if step_name in ("merge", "upload"):
        return []  # per-lib only

    if lib == "lib_7nm_hd":
        return ["corner", "em", "lvl", "lvf"]
    elif lib == "lib_7nm_hc":
        return ["corner", "lvl"]  # smaller lib, fewer branches
    return ["corner"]


def get_inputs(lib: str, branch: str, step_name: str) -> dict:
    """Inputs for each concrete task."""
    inputs = {
        "library_name": lib,
        "branch": branch,
    }
    if step_name == "compile":
        # Per-PVT outputs: different PVTs per branch type
        if branch == "corner":
            inputs["pvts"] = ["ss_0p75v_125c", "tt_0p85v_25c", "ff_0p99v_m40c"]
        elif branch == "lvl":
            inputs["pvts"] = ["low_0p72v", "nom_0p85v", "high_0p99v"]
        else:
            inputs["pvts"] = [f"{branch}_typical"]
    return inputs


# ─── Standalone entry point ──────────────────────────────────────────

if __name__ == "__main__":
    # Show mermaid visualization
    print("=== Abstract DAG ===")
    print(flow.to_mermaid())
    print()

    print("=== Concrete DAG for lib_7nm_hd ===")
    print(flow.to_mermaid(lib="lib_7nm_hd", get_branches=get_branches))
    print()

    print("=== Concrete DAG for lib_7nm_hc ===")
    print(flow.to_mermaid(lib="lib_7nm_hc", get_branches=get_branches))
    print()

    # Build and run
    pipeline = flow.build(
        libs=libs,
        get_branches=get_branches,
        get_inputs=get_inputs,
        output_root=output_root,
    )

    print(f"Total tasks: {len(pipeline.tasks)}")
    print(f"Libs: {pipeline.libs}")
    print()

    from kitdag.engine.local import LocalEngine

    engine = LocalEngine(pipeline=pipeline, get_inputs=get_inputs, max_retries=1)
    success = engine.run()

    print()
    print("Result:", "PASS" if success else "FAIL")
