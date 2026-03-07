# Repack v2

A DAG-based utility for **renaming and trimming** standard cell library kits.
Given a pre-organized `source_lib` (prepared by upstream), Repack orchestrates a set of user-defined *kits* — each responsible for producing one output artefact — by intersecting source files with specs (PVT corners, cell lists), with automatic dependency ordering, incremental re-runs, and strict false-negative prevention.

---

## Features

| Feature | Description |
|---|---|
| **Kit types** | `Kit` (single target), `CornerBasedKit` (per-PVT), `BinaryKitMixin` (binary kits needing utility re-run) |
| **DAG execution** | Kit-level dependencies auto-expanded to target-level with PVT matching; topological sort via Kahn's algorithm |
| **False-negative prevention** | 4 layered defences — see [False-Negative Prevention](#false-negative-prevention) |
| **Incremental runs** | CSV state file with SHA-256 spec-hash tracking; unchanged PASS targets are skipped |
| **Auto-retry** | Failed targets automatically re-attempted (default: 3 times) with cascade invalidation between attempts |
| **Executors** | `LocalExecutor` (ThreadPool) and `LSFExecutor` (IBM LSF, abstract — requires site-specific subclass) |
| **PySide2 GUI** | Summary tables, live log viewer, DAG visualisation, search/filter bar |
| **ddi.sh migration** | Converter from legacy `ddi.sh` invocations to YAML config |
| **CLI** | `run`, `gui`, `convert`, `status` subcommands |

---

## Architecture

```
repack/
├── cli.py                    # CLI entry point (argparse)
├── config.py                 # YAML loader & RepackConfig dataclass
├── core/
│   ├── kit.py                # Kit, CornerBasedKit, BinaryKitMixin
│   ├── target.py             # KitTarget + TargetStatus enum
│   ├── dag.py                # DAGBuilder + topological sort
│   ├── spec.py               # SpecCollection (per-kit specs + SHA-256 hashing)
│   └── validation.py         # LogScanner + OutputValidator
├── engine/
│   └── engine.py             # RepackEngine orchestrator
├── executor/
│   ├── base.py               # Executor ABC, Job dataclass
│   ├── local.py              # LocalExecutor (ThreadPool)
│   └── lsf.py                # LSFExecutor (bsub / bjobs)
├── state/
│   └── manager.py            # StateManager (CSV + spec-hash change detection)
├── upload/
│   └── uploader.py           # cp-based upload with stale artifact cleanup
├── gui/
│   ├── app.py                # MainWindow (QMainWindow)
│   ├── summary_table.py      # Corner / Non-corner tabs with O / X / - status
│   ├── log_viewer.py         # Log file viewer with syntax highlighting
│   ├── dag_view.py           # QGraphicsView DAG visualisation
│   └── filter_bar.py         # Search + status filter bar
└── compat/
    └── ddi_converter.py      # Template: ddi.sh args → RepackConfig
```

**Execution data flow:**

```
YAML config ──► Kit registration (Python script)
                        │
                        ▼
              Target collection (per kit)
                        │
                        ▼
              State reconciliation (incremental)
                        │
                        ▼
              Cascade invalidation (upstream→downstream)
                        │
                        ▼
              DAG build + topological sort
                        │
                ┌───────┴───────┐
                ▼               ▼
         Stage 1 jobs     Stage 2 jobs  ...  (parallel within each stage)
                │
                ▼
         Validation gate (output files + log scan)
                │
                ▼
         Auto-retry loop (up to N times)
                │
                ▼
         Upload (cp) + state save
```

---

## Quick Start

### 1. Create a config file

```yaml
# config.yaml
old_name: my_lib
old_ver: "7nm"
new_name: my_lib
new_ver: "7nm_trimmed"
library_name: my_lib_7nm_trimmed     # auto-derived as {new_name}_{new_ver}

source_lib: /data/source_libs/my_lib_7nm   # pre-organized by upstream
output_root: /data/repack_output/my_lib_7nm
upload_dest: /release/my_lib_7nm_trimmed

pvts:
  - ss_0p75v_125c
  - tt_0p85v_25c
  - ff_0p99v_m40c

cells:
  - INV_X1
  - NAND2_X1

executor_type: local
max_workers: 4
```

### 2. Write kit definitions

```python
# kits.py
import os
from repack.core.kit import CornerBasedKit, Kit
from repack.core.target import KitTarget

class LibertyKit(CornerBasedKit):
    def __init__(self):
        super().__init__(name="liberty", dependencies=[])

    def construct_command(self, target: KitTarget, config):
        src = self.get_source_path(config)    # source_lib/liberty/
        out = os.path.join(self.get_output_path(config), target.pvt,
                           f"{config.library_name}_{target.pvt}.lib")
        return [
            "trim_liberty",
            "--ref", os.path.join(src, target.pvt, f"{config.ref_lib}_{target.pvt}.lib"),
            "--cells", ",".join(config.cells),
            "--rename", f"{config.ref_lib}={config.library_name}",
            "--output", out,
        ]

    def get_expected_outputs(self, target: KitTarget, config):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.lib")]

def register_kits(config):
    return [LibertyKit()]
```

### 3. Run

```bash
# Execute the pipeline
repack run config.yaml --script kits.py

# Launch GUI after execution
repack run config.yaml --script kits.py --gui
```

### 4. Check status

```bash
repack status /data/repack_output/my_lib_7nm
```

---

## Configuration Reference

All fields in `RepackConfig` can be set in the YAML file.

| Field | Type | Default | Description |
|---|---|---|---|
| `old_name` | `str` | `""` | Reference library name (e.g., "my_lib") |
| `old_ver` | `str` | `""` | Reference library version (e.g., "7nm") |
| `new_name` | `str` | `""` | Target library name (e.g., "my_lib") |
| `new_ver` | `str` | `""` | Target library version (e.g., "7nm_trimmed") |
| `library_name` | `str` | `""` | Target library full name (`{new_name}_{new_ver}`); auto-derived if not set |
| `source_lib` | `str` | `""` | Path to pre-organized source folder (by kit type: `source_lib/liberty/`, `source_lib/lef/`, etc.) |
| `output_root` | `str` | `""` | Root directory for all kit outputs and state file |
| `upload_dest` | `str` | `""` | Upload root path; each kit has its own upload structure |
| `pvts` | `List[str]` | `[]` | PVT corner strings (used by `CornerBasedKit`) |
| `cells` | `List[str]` | `[]` | Cells to include; empty = all cells |
| `kit_options` | `Dict[str,Dict]` | `{}` | Per-kit configuration overrides |
| `max_workers` | `int` | `4` | Max parallel workers (local executor) |
| `executor_type` | `str` | `"local"` | `"local"` or `"lsf"` |
| `specs` | YAML section | — | Per-kit spec data for incremental change detection |
| `extra` | `Dict` | `{}` | Catch-all for additional options |

Derived property: `config.ref_lib` = `{old_name}_{old_ver}` (reference library full name).

**Full YAML example with all fields:**

```yaml
old_name: my_lib
old_ver: "7nm"
new_name: my_lib
new_ver: "7nm_trimmed"
library_name: my_lib_7nm_trimmed     # auto-derived as {new_name}_{new_ver}

source_lib: /data/source_libs/my_lib_7nm   # pre-organized by upstream
output_root: /data/repack_output/my_lib_7nm
upload_dest: /release/my_lib_7nm_trimmed

pvts:
  - ss_0p75v_125c
  - tt_0p85v_25c
  - ff_0p99v_m40c

cells:
  - INV_X1
  - NAND2_X1

kit_options:
  timing_db:
    compile_flags: "-no_pg"

executor_type: local
max_workers: 8

# Spec data drives incremental change detection.
# When a kit's effective spec changes (global + kit-specific merged),
# its SHA-256 hash changes and the kit is re-run on the next invocation.
specs:
  global:
    cells_version: "2.1"
  kits:
    liberty:
      trim_mode: conservative
    timing_db:
      db_format: "2017.06"
```

---

## Writing Kits

### `Kit` — non-corner-based

`Kit` produces **one target per library** (`pvt="ALL"`).  Use it for artefacts
that are PVT-independent (e.g. LEF, GDS, Verilog netlist).

```python
from repack.core.kit import Kit
from repack.core.target import KitTarget
import os

class LefKit(Kit):
    def __init__(self):
        super().__init__(name="lef", dependencies=[])   # list kit names you depend on

    def construct_command(self, target: KitTarget, config) -> list:
        """Return the shell command that produces this kit's output."""
        src = self.get_source_path(config)    # source_lib/lef/
        out = os.path.join(self.get_output_path(config), f"{config.library_name}.lef")
        return ["trim_lef", "--ref", os.path.join(src, f"{config.ref_lib}.lef"), "--output", out]

    def get_expected_outputs(self, target: KitTarget, config) -> list:
        """Paths RELATIVE to get_output_path(config) that must exist after execution."""
        return [f"{config.library_name}.lef"]

    # --- optional overrides ---

    def get_output_path(self, config) -> str:
        """Default: {output_root}/{kit_name}. Override if you need a different layout."""
        return os.path.join(config.output_root, self.name)

    def get_log_error_patterns(self) -> list:
        """Extra regex patterns for log scanning (in addition to built-in ones)."""
        return [r"trim_lef: assertion failed"]

    def get_log_ignore_patterns(self) -> list:
        """Regex patterns to EXCLUDE from error detection (whitelist)."""
        return [r"ERROR_COUNT:\s*0"]

    def clean_output(self, target: KitTarget, config) -> None:
        """Called before every re-run. Default: rmtree the output directory."""
        super().clean_output(target, config)   # or implement custom cleanup
```

### `CornerBasedKit` — per-PVT

`CornerBasedKit` automatically expands `get_targets()` across `config.pvts`.
Each `KitTarget` carries `target.pvt` set to the corner string.

```python
from repack.core.kit import CornerBasedKit
from repack.core.target import KitTarget
import os

class LibertyKit(CornerBasedKit):
    def __init__(self):
        super().__init__(name="liberty", dependencies=[])

    def construct_command(self, target: KitTarget, config) -> list:
        # target.pvt is e.g. "ss_0p75v_125c" — use it to select the right files.
        src = self.get_source_path(config)    # source_lib/liberty/
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.lib")
        return [
            "trim_liberty",
            "--ref", os.path.join(src, target.pvt, f"{config.ref_lib}_{target.pvt}.lib"),
            "--cells", ",".join(config.cells),
            "--rename", f"{config.ref_lib}={config.library_name}",
            "--output", out_file,
        ]

    def get_expected_outputs(self, target: KitTarget, config) -> list:
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.lib")]
```

### `BinaryKitMixin` — binary kits (pgv, apl, …)

Binary kits cannot be directly text-edited.  Instead:
1. The mixin calls `get_trimmed_spec()` to build the reduced spec dict.
2. It writes the spec to a JSON file in `.specs/`.
3. It calls `get_utility_command(target, config, spec_path)` with the spec path.

Combine the mixin with `Kit` or `CornerBasedKit` via multiple inheritance:

```python
from repack.core.kit import CornerBasedKit, BinaryKitMixin
from repack.core.target import KitTarget
from typing import Dict, Any

class PgvKit(BinaryKitMixin, CornerBasedKit):
    def __init__(self):
        super().__init__(name="pgv", dependencies=["liberty"])

    def get_trimmed_spec(self, target: KitTarget, config) -> Dict[str, Any]:
        """Return the reduced spec dict for this corner."""
        return {
            "pvt": target.pvt,
            "cells": config.cells,
            "lib_name": config.library_name,
        }

    def get_utility_command(self, target: KitTarget, config, spec_path: str) -> list:
        """Return the command to re-run the generation utility with the trimmed spec."""
        return ["gen_pgv", "--spec", spec_path, "--output", self.get_output_path(config)]

    def get_expected_outputs(self, target: KitTarget, config) -> list:
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.pgv")]
```

> **Note:** `construct_command()` is provided by `BinaryKitMixin` and must **not** be overridden.

---

## Kit Registration

Create a Python file that defines `register_kits(config)` and pass it to the CLI
via `--script`:

```python
# kits.py

def register_kits(config):
    """Return the list of kits for this repack flow.

    The engine discovers this function automatically.
    Dependencies are declared per-kit in __init__().
    """
    return [
        LibertyKit(),               # no deps — root node
        TimingDbKit(),              # depends on "liberty"
        LefKit(),                   # no deps — independent
    ]
```

The engine calls `register_kits(config)` at startup and builds the DAG from the
`dependencies` declared in each kit's constructor.

---

## DAG & Dependency Model

Dependencies are declared at the **kit level** (`dependencies=["liberty"]`).
The engine automatically expands them to **target level** using the following
PVT-matching rules:

| Upstream kit | Downstream kit | Link |
|---|---|---|
| `CornerBasedKit` | `CornerBasedKit` | Same-PVT targets are linked |
| `Kit` (ALL) | `CornerBasedKit` | ALL target → every downstream PVT target |
| `CornerBasedKit` | `Kit` (ALL) | Every upstream PVT target → ALL target |

**Example DAG** (liberty → timing_db, lef independent):

```
Stage 1                                    Stage 2
─────────────────────────────────────────  ───────────────────────────────
liberty::ss_0p75v_125c  ───────────────►  timing_db::ss_0p75v_125c
liberty::tt_0p85v_25c   ───────────────►  timing_db::tt_0p85v_25c
liberty::ff_0p99v_m40c  ───────────────►  timing_db::ff_0p99v_m40c
lef::ALL                                   (no dependents)
```

All stage-1 targets run in parallel.  Each stage-2 target starts only after its
corresponding stage-1 dependency has completed and **passed validation**.

Cycle detection raises `repack.core.dag.CyclicDependencyError` at startup.

---

## False-Negative Prevention

Repack applies four layered defences to prevent incorrect `PASS` status.

### Defence 1 — Output validation (`get_expected_outputs`)

Every kit **must** implement `get_expected_outputs()`.  After a job exits with
code 0, the engine checks that every listed file:

- exists under `get_output_path(config)`, and
- is non-empty.

Any missing or empty file marks the target as `FAIL`.

```python
def get_expected_outputs(self, target, config):
    return [f"{target.pvt}/{config.library_name}_{target.pvt}.lib"]
```

### Defence 2 — Log scanning (`LogScanner`)

Even when the exit code is 0, the log is scanned for error patterns.
Built-in patterns (always active):

```
ERROR  FATAL  FAILED  Aborted  Segmentation fault  core dump
```

Kit-level extensions:

```python
def get_log_error_patterns(self):    # add patterns
    return [r"tool: assertion failed", r"Internal error"]

def get_log_ignore_patterns(self):   # whitelist false positives
    return [r"ERROR_COUNT:\s*0"]
```

### Defence 3 — Cascade invalidation

When an upstream target is re-run (becomes `PENDING` or `FAIL`), the engine
transitively marks **all downstream** `PASS` targets as `PENDING` via BFS
through the DAG.  This happens both at startup (during state reconciliation)
and between retry attempts.

### Defence 4 — Stale artifact cleanup

Before every re-run, `clean_output()` is called (default: `shutil.rmtree` the
output directory).  Before upload, the destination directory is also `rmtree`'d.
Internal directories (`.specs/`, `logs/`) are excluded from upload.

---

## CLI Reference

```
repack [-v] <command> [options]
```

### `repack run`

Execute the full repack pipeline.

```
repack run CONFIG --script KITS [--gui]
              [--executor {local,lsf}] [--max-workers N]
              [--max-retries N]

  CONFIG          Path to YAML config file
  --script KITS   Python file defining register_kits(config)
  --gui           Launch GUI after execution
  --executor      Override executor type (default from config)
  --max-workers   Override parallel worker count
  --max-retries   Auto-retry attempts for failed targets (default: 3)
```

### `repack gui`

Launch the summary GUI for an existing run (no re-execution).

```
repack gui CONFIG [--script KITS]
```

### `repack convert`

Convert a legacy `ddi.sh` invocation to a YAML config file.

```
repack convert DDI_SH [-o OUTPUT]

  DDI_SH          Path to the ddi.sh script
  -o OUTPUT       Output YAML path (default: repack_config.yaml)
```

### `repack status`

Print a summary of the current run status from the CSV state file.

```
repack status WORK_DIR

  WORK_DIR        Directory containing repack_status.csv (= output_root)
```

### Global flag

```
-v / --verbose    Enable DEBUG-level logging
```

---

## State Management

Each run persists state to `{output_root}/repack_status.csv`:

```
id,status,spec_hash,error_message
liberty::ss_0p75v_125c,PASS,a1b2c3d4e5f6g7h8,
timing_db::ss_0p75v_125c,PASS,9i8h7g6f5e4d3c2b,
lef::ALL,FAIL,deadbeef01234567,Missing files: demo_lib_7nm.lef
```

**Incremental run logic:**

| Previous status | Spec changed? | Next run action |
|---|---|---|
| `PASS` | No | Skip (reuse previous output) |
| `PASS` | Yes | Re-run (mark `PENDING`) |
| `FAIL` | — | Re-run (mark `PENDING`) |
| `SKIP` | — | Skip (not needed per spec) |
| Not in file | — | Run as new target |

The `spec_hash` is the SHA-256 (first 16 hex chars) of the merged spec for
that kit (`global` spec + kit-specific spec from `specs.kits.<name>`).

---

## GUI

Launch with `--gui` flag or `repack gui`:

```
┌─────────────────────────────────────────────────────────────────┐
│ [Search: _____________]  Show: [✓PASS] [✓FAIL] [✓PENDING] [✓SKIP]│
├──────────────────────────────────┬──────────────────────────────┤
│ Corner-Based │ Non-Corner-Based  │                              │
│─────────────────────────────────│        Log Viewer            │
│         ss    tt    ff          │                              │
│ liberty  O     O     O          │  # Job: liberty::ss_0p75v... │
│ timing_db O    O     O          │  # Command: trim_liberty ...  │
│                                 │  INFO: trimming 1243 cells   │
├──────────────────────────────────┤  Done.                       │
│ Non-corner-based:               │                              │
│         Status                  │                              │
│ lef        O                    │                              │
├─────────────────────────────────┴──────────────────────────────┤
│                         DAG View                                │
│  [liberty::ss]──►[timing_db::ss]                               │
│  [liberty::tt]──►[timing_db::tt]    [lef::ALL]                 │
│  [liberty::ff]──►[timing_db::ff]                               │
└─────────────────────────────────────────────────────────────────┘
```

- **O** = PASS (green), **X** = FAIL (red), **-** = SKIP (gray), **?** = PENDING (amber)
- **Double-click** a cell to toggle PASS → FAIL (queues it for re-run)
- **Right-click** for batch Mark FAIL / Mark SKIP
- **Click** a cell or DAG node to display its log on the right

**Dependency:** `PySide2` must be installed (`pip install PySide2`).

---

## ddi.sh Migration

If you have an existing `ddi.sh` wrapper that calls the legacy Perl program:

```bash
# ddi.sh (generated by upstream flow)
/path/to/old/repack.pl -lib_name my_lib -pvt_list ss,tt,ff -out_dir /data/out ...
```

Convert it to a YAML config:

```bash
repack convert /path/to/ddi.sh -o config.yaml
```

Then fill in the `ARG_MAP` in `repack/compat/ddi_converter.py` to map your
site-specific legacy flags to `RepackConfig` fields.  The converter template is
at `repack/compat/ddi_converter.py` — it handles argument extraction and
type coercion; you only need to add the flag-to-field mapping.

---

## Example

A complete working example with three kits is in `examples/`:

```
examples/
├── three_kit_config.yaml   # YAML config (local executor)
└── three_kit_flow.py       # Kit definitions + register_kits()
```

Run it:

```bash
# Via CLI
repack run examples/three_kit_config.yaml --script examples/three_kit_flow.py

# Or directly (uses in-memory config fallback)
python examples/three_kit_flow.py
```

See `examples/three_kit_flow.py` for the full annotated source.

---

## MCP Server (AI-Assisted Migration)

An MCP server at `mcp_server/server.py` provides 5 tools for AI coding agents
(e.g. qwen3\_235B) to assist with migrating legacy kits to Repack v2.

| Tool | Description |
|---|---|
| `analyze_legacy_command` | Parse a legacy shell command; suggest Kit vs CornerBasedKit vs BinaryKitMixin |
| `scaffold_kit` | Generate a complete kit class from name, type, deps, command template, outputs |
| `validate_kit_file` | Check a kit file for missing methods, wrong base class, absolute paths |
| `explain_dag` | Show execution stages, dependency edges, PVT matching type |
| `check_migration_status` | Report which kits in a file are DONE vs TODO |

**Usage:**

```bash
# MCP mode (requires `pip install mcp`)
python mcp_server/server.py

# Standalone mode (no dependencies)
python mcp_server/server.py --tool analyze_legacy_command \
    --args '{"command": "trim_liberty -pvt ss -ref /path -output /out"}'

python mcp_server/server.py --tool validate_kit_file \
    --args '{"file_path": "my_kits.py"}'
```

See `SKILL.md` for the full migration guide aimed at AI agents — it covers
the classification decision tree, step-by-step migration process, common
patterns, common mistakes, and a per-kit migration checklist.

---

## Running Tests

```bash
python3 -m unittest discover tests/ -v
```

41 tests covering: DAG (PVT matching, cycle detection, stages), output validation,
log scanning, state reconciliation, spec-hash change detection, engine execution,
false-negative prevention, and corner-based kit expansion.
