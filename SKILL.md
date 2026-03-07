# SKILL: Migrating Legacy Repack Kits to Repack v2

You are helping migrate legacy standard cell library repack flows to the new
Repack v2 Python framework.  This document teaches you the patterns, pitfalls,
and step-by-step process.

---

## 1. Mental Model

**Legacy flow** (Perl-based):
```
ddi.sh  →  /path/to/repack.pl -arg_a val_a -arg_b val_b ...
```
- Monolithic script; all kits interleaved in one program
- No DAG — kits are run by manual sequencing in the script
- Status tracked ad-hoc (grepping logs, checking files manually)
- No incremental runs; full re-run every time

**New Repack v2** (Python):
```
YAML config  →  Kit classes (Python)  →  RepackEngine  →  DAG execution
```
- Each kit is a self-contained Python class
- Dependencies declared in constructor; engine builds DAG automatically
- Mandatory output validation + log scanning (false-negative prevention)
- Incremental runs with spec-hash change detection

**Your job**: For each legacy kit, create a Python class that implements the
new `Kit` or `CornerBasedKit` interface.

---

## 2. Kit Classification Decision Tree

When analysing a legacy kit, determine two things:

```
Q1: Does this kit produce per-PVT outputs?
    YES → CornerBasedKit
    NO  → Kit

Q2: Is the kit binary (requires running a generation utility)?
    YES → add BinaryKitMixin
    NO  → plain Kit / CornerBasedKit
```

### Examples

| Kit type | Base class | Reason |
|---|---|---|
| Liberty (.lib per corner) | `CornerBasedKit` | One .lib file per PVT |
| LEF (single .lef file) | `Kit` | PVT-independent |
| Verilog (single netlist) | `Kit` | PVT-independent |
| Timing DB (.db per corner) | `CornerBasedKit` | Compiled per PVT |
| PGV (binary, per corner) | `BinaryKitMixin, CornerBasedKit` | Binary + per PVT |
| APL (binary, single) | `BinaryKitMixin, Kit` | Binary + single target |

---

## 3. Migration Steps (Per Kit)

### Step 1: Identify the legacy command

Find the actual command the legacy flow runs for this kit.  It's usually in
the Perl script or in a generated shell wrapper.  Look for patterns like:

```perl
system("trim_liberty -ref $ref_path -cells $cell_list -output $out_path");
```

Extract:
- The executable name and arguments
- Which arguments vary per PVT corner (if corner-based)
- What output files the command produces
- What the input dependencies are (other kit outputs used as input)

### Step 2: Identify dependencies

Look for which kits' outputs are used as inputs.  Examples:
- timing_db reads from liberty output → `dependencies=["liberty"]`
- lef reads only from source_lib → `dependencies=[]`

### Step 3: Write the kit class

Use this template:

```python
import os
from repack.core.kit import Kit, CornerBasedKit  # pick one
from repack.core.target import KitTarget
from repack.config import RepackConfig

class MyKit(CornerBasedKit):  # or Kit for non-corner-based
    def __init__(self):
        super().__init__(
            name="my_kit",           # unique kit name
            dependencies=["other"],  # kit names this depends on, or []
        )

    def construct_command(self, target: KitTarget, config: RepackConfig):
        # For CornerBasedKit: target.pvt is the corner string
        # For Kit: target.pvt is "ALL"
        src = self.get_source_path(config)    # source_lib/my_kit/
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.ext")
        return [
            "my_tool",
            "--ref", os.path.join(src, target.pvt, f"{config.ref_lib}.ext"),
            "--cells", ",".join(config.cells),
            "--rename", f"{config.ref_lib}={config.library_name}",
            "--output", out_file,
        ]

    def get_expected_outputs(self, target: KitTarget, config: RepackConfig):
        # Paths RELATIVE to self.get_output_path(config)
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.ext")]
```

### Step 4: Add to register_kits()

```python
def register_kits(config):
    return [
        LibertyKit(),     # no deps
        TimingDbKit(),    # depends on liberty
        LefKit(),         # no deps
        MyKit(),          # whatever deps you identified
    ]
```

### Step 5: Test in debug mode

```bash
repack run config.yaml --script kits.py --max-retries 0
```

Check:
- Target shows `PASS`?  If not, read the log and error_message.
- Expected output files exist?
- No false ERROR lines in log?  If so, add `get_log_ignore_patterns()`.

---

## 4. Common Patterns

### Pattern A: Reading another kit's output as input

```python
def construct_command(self, target, config):
    # Reference the upstream kit's output directory
    lib_file = os.path.join(
        config.output_root, "liberty", target.pvt,
        f"{config.library_name}_{target.pvt}.lib",
    )
    return ["compile_lib", "--input", lib_file, "--output", ...]
```

The DAG ensures `liberty::ss_0p75v_125c` completes before
`timing_db::ss_0p75v_125c` starts (same-PVT matching).

### Pattern B: Renaming (old library → new library)

```python
# config.ref_lib = "{old_name}_{old_ver}" (reference/source library name)
# config.library_name = "{new_name}_{new_ver}" (target library name)
# Use in rename operations:
"--rename", f"{config.ref_lib}={config.library_name}",
```

### Pattern C: Per-kit options from kit_options

```python
flags = config.kit_options.get("my_kit", {}).get("compile_flags", "")
# Append to command
```

### Pattern D: Binary kit (BinaryKitMixin)

```python
class PgvKit(BinaryKitMixin, CornerBasedKit):
    def __init__(self):
        super().__init__(name="pgv", dependencies=["liberty"])

    def get_trimmed_spec(self, target, config):
        # Return the spec dict that will be written to JSON
        return {
            "pvt": target.pvt,
            "cells": config.cells,
            "lib_name": config.library_name,
        }

    def get_utility_command(self, target, config, spec_path):
        # spec_path is the JSON file the mixin wrote automatically
        return ["gen_pgv", "--spec", spec_path]

    def get_expected_outputs(self, target, config):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.pgv")]
```

**Note:** Do NOT override `construct_command()` — the mixin provides it.

### Pattern E: Non-corner kit with pvt="ALL"

```python
class LefKit(Kit):  # not CornerBasedKit
    def __init__(self):
        super().__init__(name="lef", dependencies=[])

    def construct_command(self, target, config):
        # target.pvt is "ALL" — don't use it in file paths
        out = os.path.join(self.get_output_path(config), f"{config.library_name}.lef")
        return ["trim_lef", "--output", out]

    def get_expected_outputs(self, target, config):
        return [f"{config.library_name}.lef"]
```

### Pattern F: Kit-specific log patterns

```python
def get_log_error_patterns(self):
    # Catch tool-specific errors not covered by defaults
    return [r"my_tool: assertion failed", r"VIOLATION:"]

def get_log_ignore_patterns(self):
    # Whitelist false positives
    return [r"ERROR_COUNT:\s*0", r"WARNING: no errors found"]
```

---

## 5. Common Mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Returning absolute paths from `get_expected_outputs()` | Validation always fails (path won't match relative check) | Return paths **relative** to `get_output_path(config)` |
| Forgetting `mkdir -p` in the command | Kit fails because output dir doesn't exist | The engine creates the top-level output dir, but **subdirs** (e.g., per-PVT) must be created by the command |
| Overriding `construct_command()` on a `BinaryKitMixin` class | Bypasses the spec-writing logic | Implement `get_utility_command()` instead |
| Using `Kit` for a per-PVT kit | Only one target created (pvt="ALL"), misses all corners | Use `CornerBasedKit` |
| Wrong dependency name string | DAG doesn't link properly; kit runs without waiting for upstream | Dependency names must exactly match the `name` in the upstream kit's constructor |
| Not declaring output validation | FN#1: output missing but status shows O | `get_expected_outputs()` is abstract — you MUST implement it |

---

## 6. Migration Checklist (copy & fill per kit)

```
Kit name: _______________
Legacy command: _______________

[ ] Q1: Corner-based? → Kit / CornerBasedKit
[ ] Q2: Binary kit?   → add BinaryKitMixin
[ ] Dependencies identified: _______________
[ ] construct_command() implemented
[ ] get_expected_outputs() implemented (relative paths!)
[ ] get_log_error_patterns() checked (any tool-specific errors?)
[ ] get_log_ignore_patterns() checked (any false-positive lines?)
[ ] Added to register_kits()
[ ] Tested (repack run config.yaml --script kits.py --max-retries 0)
[ ] All targets PASS
[ ] Output files verified correct
```

---

## 7. Using MCP Tools

This repo provides an MCP server (`mcp_server/server.py`) with tools to help you:

| Tool | What it does |
|---|---|
| `analyze_legacy_command` | Parse a legacy command string, identify args, suggest kit type |
| `scaffold_kit` | Generate a complete kit class from name, type, deps, command template, outputs |
| `validate_kit_file` | Check a kit definitions file for common mistakes |
| `explain_dag` | Show the DAG structure for a set of kits (stages, dependency links) |
| `check_migration_status` | Scan a kit file and report which kits are done vs TODO |

### Example MCP workflow

1. Paste the legacy command → `analyze_legacy_command`
2. Use the analysis to fill in → `scaffold_kit`
3. Add the scaffolded class to your kits.py
4. Check for mistakes → `validate_kit_file`
5. Review the DAG → `explain_dag`
6. Run the pipeline in debug mode
7. Track progress → `check_migration_status`

---

## 8. YAML Config Quick Reference

```yaml
# ── Library Identity ──
old_name: my_lib                   # reference library name
old_ver: "7nm"                     # reference library version
new_name: my_lib                   # target library name
new_ver: "7nm_trimmed"             # target library version
library_name: my_lib_7nm_trimmed   # auto-derived as {new_name}_{new_ver}

# ── Paths ──
source_lib: /path/to/source_lib    # pre-organized by upstream (by kit type)
output_root: /path/to/output       # all outputs go here
upload_dest: /path/to/release      # each kit has its own upload structure

# ── What to Repack ──
pvts:                              # PVT corners (for CornerBasedKit)
  - ss_0p75v_125c
  - tt_0p85v_25c
  - ff_0p99v_m40c

cells:                             # cells to include (empty = all)
  - INV_X1
  - NAND2_X1

# ── Execution ──
executor_type: local               # "local" or "lsf"
max_workers: 4                     # parallel threads

kit_options:                       # per-kit overrides (accessed via config.kit_options)
  timing_db:
    compile_flags: "-no_pg"

specs:                             # drives incremental change detection
  global:
    version: "1.0"
  kits:
    liberty:
      trim_mode: conservative
```
