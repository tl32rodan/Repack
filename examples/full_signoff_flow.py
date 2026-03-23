"""Full chip signoff flow — comprehensive example.

Demonstrates ALL KitDAG features:
  - 6 pipeline steps with realistic EDA naming
  - 4 libraries with different branch configurations
  - Cross-branch dependencies (compile/corner needs char/{corner,em,lvl,lvf})
  - Intra-step branch deps (compile/em,lvl,lvf wait for compile/corner)
  - Fan-in (merge waits for all branches)
  - Per-PVT variant output checking (layer 2 detail)
  - Deliberate failures (to show mixed status dashboard)
  - Log error detection (false-negative prevention)
  - Mermaid DAG visualization
  - Incremental re-run (skip unchanged PASS tasks)

Pipeline:
  extract → char → compile → signoff → merge → release
                      ↘ (intra: corner → em/lvl/lvf)

Libraries:
  lib_7nm_hvt  - corner, em, lvl, lvf (full set)
  lib_7nm_svt  - corner, em, lvl      (no lvf)
  lib_7nm_lvt  - corner, lvl          (minimal)
  lib_5nm_hvt  - corner, em, lvl, lvf (full set, but compile will FAIL)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitdag.core.flow import Flow
from kitdag.core.step import Step, StepInput, StepOutput


# ═══════════════════════════════════════════════════════════════════════
# Step definitions — each step is a reusable command template
# ═══════════════════════════════════════════════════════════════════════

class ExtractStep(Step):
    """Extract source netlists per branch."""

    name = "extract"
    base_command = "sh"
    inputs = [StepInput("library_name"), StepInput("branch")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        branch = inputs.get("branch", "")
        out = os.path.join(out_dir, f"{lib}_{branch}_netlist.v")
        return ["-c", f"mkdir -p {out_dir} && echo '// netlist for {lib}/{branch}' > {out}"]


class CharStep(Step):
    """Run SPICE characterization per branch."""

    name = "char"
    base_command = "sh"
    inputs = [StepInput("library_name"), StepInput("branch")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        branch = inputs.get("branch", "")
        out = os.path.join(out_dir, f"{lib}_{branch}_char.dat")
        return ["-c", f"mkdir -p {out_dir} && echo 'characterized {lib}/{branch}' > {out}"]


class CompileStep(Step):
    """Compile .lib/.db per branch with per-PVT output checking.

    This step demonstrates:
    - variant_key: "pvts" means per-PVT output checking
    - get_expected_variant_outputs: defines expected output products
    - get_variant_products: column headers for PVT sub-table
    - Deliberate failure for lib_5nm_hvt (to show mixed results)
    """

    name = "compile"
    base_command = "sh"
    variant_key = "pvts"
    inputs = [
        StepInput("library_name"),
        StepInput("branch"),
        StepInput("pvts", type="string[]"),
        StepInput("should_fail", type="string"),
    ]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        pvts = inputs.get("pvts", [])
        should_fail = inputs.get("should_fail", "false")

        cmds = []
        for i, pvt in enumerate(pvts):
            pvt_dir = os.path.join(out_dir, pvt)
            cmds.append(f"mkdir -p {pvt_dir}")
            cmds.append(f"echo 'timing {lib} {pvt}' > {pvt_dir}/{lib}_{pvt}.lib")
            cmds.append(f"echo 'db {lib} {pvt}' > {pvt_dir}/{lib}_{pvt}.db")

            # For some PVTs, also generate .sdf
            if "corner" in pvt or "ff_" in pvt:
                cmds.append(f"echo 'sdf {lib} {pvt}' > {pvt_dir}/{lib}_{pvt}.sdf")

        # Deliberate failure: inject ERROR into log
        if should_fail == "true":
            cmds.append("echo 'ERROR: Liberty compile failed for cell INV_X1'")
            cmds.append("echo 'ERROR: Missing NLDM data for setup arc'")

        # Deliberate partial failure: one PVT missing output
        if should_fail == "partial" and pvts:
            last_pvt = pvts[-1]
            bad = os.path.join(out_dir, last_pvt, f"{lib}_{last_pvt}.lib")
            cmds.append(f"rm -f {bad}")  # remove one .lib to trigger variant fail

        return ["-c", " && ".join(cmds)] if cmds else ["-c", "true"]

    def get_expected_variant_outputs(self, variant, inputs):
        lib = inputs.get("library_name", "")
        return [
            f"{variant}/{lib}_{variant}.lib",
            f"{variant}/{lib}_{variant}.db",
        ]

    def get_variant_products(self):
        return [".lib", ".db"]

    def get_log_error_patterns(self):
        return [r"\bLiberty compile failed\b"]


class SignoffStep(Step):
    """Run timing signoff checks per branch."""

    name = "signoff"
    base_command = "sh"
    inputs = [StepInput("library_name"), StepInput("branch")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        branch = inputs.get("branch", "")
        out = os.path.join(out_dir, f"{lib}_{branch}_signoff.rpt")
        return ["-c", f"mkdir -p {out_dir} && echo 'signoff PASS {lib}/{branch}' > {out}"]


class MergeStep(Step):
    """Merge all branch results into a single lib release."""

    name = "merge"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        out = os.path.join(out_dir, f"{lib}_merged_kit.tar.gz")
        return ["-c", f"mkdir -p {out_dir} && echo 'merged {lib}' > {out}"]


class ReleaseStep(Step):
    """Upload released kit to artifact store."""

    name = "release"
    base_command = "sh"
    inputs = [StepInput("library_name")]

    def get_arguments(self, inputs):
        out_dir = inputs.get("output_dir", "")
        lib = inputs.get("library_name", "")
        out = os.path.join(out_dir, f"{lib}_release.manifest")
        return ["-c", f"mkdir -p {out_dir} && echo 'released {lib} v1.0' > {out}"]


# ═══════════════════════════════════════════════════════════════════════
# Flow definition — the fixed step graph (same for all projects)
# ═══════════════════════════════════════════════════════════════════════

flow = Flow("full_signoff")

flow.add_step("extract", kit=ExtractStep())
flow.add_step("char",    kit=CharStep())
flow.add_step("compile", kit=CompileStep())
flow.add_step("signoff", kit=SignoffStep())
flow.add_step("merge",   kit=MergeStep())
flow.add_step("release", kit=ReleaseStep())

# ── Linear same-branch chain ──
flow.add_dep("char",    on="extract")           # char(ss) ← extract(ss)
flow.add_dep("compile", on="char")              # compile(ss) ← char(ss)
flow.add_dep("signoff", on="compile")           # signoff(ss) ← compile(ss)

# ── Cross-branch: compile/corner needs char from ALL branches ──
flow.add_dep("compile", on="char", branch_map={
    "corner": ["corner", "em", "lvl", "lvf"],
})

# ── Intra-step: compile/em,lvl,lvf wait for compile/corner ──
flow.add_dep("compile", on="compile", branch_map={
    "em":  ["corner"],
    "lvl": ["corner"],
    "lvf": ["corner"],
})

# ── Fan-in: merge waits for ALL signoff branches ──
flow.add_dep("merge", on="signoff")

# ── merge → release ──
flow.add_dep("release", on="merge")


# ═══════════════════════════════════════════════════════════════════════
# User-provided expansion functions
# ═══════════════════════════════════════════════════════════════════════

libs = ["lib_7nm_hvt", "lib_7nm_svt", "lib_7nm_lvt", "lib_5nm_hvt"]

output_root = "/tmp/kitdag_signoff_demo"

# Per-lib branch configuration
LIB_BRANCHES = {
    "lib_7nm_hvt": ["corner", "em", "lvl", "lvf"],
    "lib_7nm_svt": ["corner", "em", "lvl"],
    "lib_7nm_lvt": ["corner", "lvl"],
    "lib_5nm_hvt": ["corner", "em", "lvl", "lvf"],
}

# Per-branch PVT corners
BRANCH_PVTS = {
    "corner": ["ss_0p75v_125c", "tt_0p85v_25c", "ff_0p99v_m40c"],
    "em":     ["em_0p80v_105c", "em_0p90v_85c"],
    "lvl":    ["low_0p72v_125c", "nom_0p85v_25c", "high_0p99v_m40c"],
    "lvf":    ["lvf_0p75v_125c", "lvf_0p85v_25c"],
}


def get_branches(lib: str, step_name: str) -> list:
    """Which branches to run for each (lib, step).

    Per-lib steps (merge, release) return [] for no branch expansion.
    Branch list auto-intersects with declared deps (e.g., if lib_7nm_lvt
    has no 'em' branch, cross-branch deps to em are skipped).
    """
    if step_name in ("merge", "release"):
        return []
    return LIB_BRANCHES.get(lib, ["corner"])


def get_inputs(lib: str, branch: str, step_name: str) -> dict:
    """Build inputs for each concrete task.

    This is where failures are injected:
    - lib_5nm_hvt / compile: log error (detected by log scanner)
    - lib_7nm_svt / compile / em: partial failure (one PVT output missing)
    """
    inputs = {
        "library_name": lib,
        "branch": branch,
    }

    if step_name == "compile":
        inputs["pvts"] = BRANCH_PVTS.get(branch, [])

        # Inject failures
        if lib == "lib_5nm_hvt":
            inputs["should_fail"] = "true"   # log error → FAIL
        elif lib == "lib_7nm_svt" and branch == "em":
            inputs["should_fail"] = "partial"  # missing PVT output
        else:
            inputs["should_fail"] = "false"

    return inputs


# ═══════════════════════════════════════════════════════════════════════
# Standalone entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Full signoff demo")
    parser.add_argument("--viz-only", action="store_true",
                        help="Only show DAG visualization, don't run")
    parser.add_argument("--lib", default=None,
                        help="Show concrete DAG for one lib")
    args = parser.parse_args()

    if args.viz_only:
        if args.lib:
            print(flow.to_mermaid(lib=args.lib, get_branches=get_branches))
        else:
            print(flow.to_mermaid())
        sys.exit(0)

    # Build and run
    pipeline = flow.build(
        libs=libs,
        get_branches=get_branches,
        get_inputs=get_inputs,
        output_root=output_root,
    )

    print(f"Total tasks: {len(pipeline.tasks)}")
    for lib in pipeline.libs:
        lib_tasks = pipeline.tasks_for_lib(lib)
        branches = set(t.branch for t in lib_tasks.values() if t.branch)
        print(f"  {lib}: {len(lib_tasks)} tasks, branches={sorted(branches)}")

    from kitdag.engine.local import LocalEngine
    engine = LocalEngine(pipeline=pipeline, get_inputs=get_inputs, max_retries=1)
    success = engine.run()

    print()
    print("Overall:", "PASS" if success else "FAIL")
