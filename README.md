# KitDAG

A DAG-based execution platform for **kit generation pipelines**. KitDAG orchestrates user-defined *kits* — each responsible for producing one output artefact — with automatic dependency ordering, incremental re-runs, and strict false-negative prevention.

---

## Features

| Feature | Description |
|---|---|
| DAG execution | Kits declare dependencies; engine builds and executes in topological order |
| Kit decides targets | Each kit defines its own targets (single, per-PVT, or custom) |
| Incremental runs | Spec-hash (SHA-256) change detection — only re-run what changed |
| False-negative prevention | Output validation, log scanning, cascade invalidation, stale cleanup |
| Auto-retry | Failed targets retry up to N times automatically |
| GUI | PySide2 dashboard with per-kit tabs, DAG view, and log viewer |
| Minimal config | Only `library_name` and `output_root` are first-class; everything else in `extra` |

---

## Quick Start

### 1. Define your kits

```python
# kits.py
from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget
from kitdag.config import Config

class LibertyKit(Kit):
    def __init__(self):
        super().__init__(name="liberty", dependencies=[])

    def get_targets(self, config):
        # Kit decides its own targets
        return [KitTarget(kit_name=self.name, pvt=pvt)
                for pvt in config.extra["pvts"]]

    def construct_command(self, target, config):
        out_dir = os.path.join(self.get_output_path(config), target.pvt)
        out_file = os.path.join(out_dir, f"{config.library_name}_{target.pvt}.lib")
        return ["trim_liberty", "--output", out_file]

    def get_expected_outputs(self, target, config):
        return [os.path.join(target.pvt, f"{config.library_name}_{target.pvt}.lib")]

class LefKit(Kit):
    """Single-target kit (default get_targets returns pvt="ALL")."""
    def __init__(self):
        super().__init__(name="lef", dependencies=[])

    def construct_command(self, target, config):
        out = os.path.join(self.get_output_path(config), f"{config.library_name}.lef")
        return ["trim_lef", "--output", out]

    def get_expected_outputs(self, target, config):
        return [f"{config.library_name}.lef"]

def register_kits(config):
    return [LibertyKit(), LefKit()]
```

### 2. Write a config

```yaml
# config.yaml
library_name: my_lib_7nm_trimmed
output_root: /data/output
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
  pvts: [ss_0p75v_125c, tt_0p85v_25c, ff_0p99v_m40c]
  cells: [INV_X1, NAND2_X1]
  source_lib: /data/source_libs/my_lib_7nm
```

### 3. Run

```bash
kitdag run config.yaml --script kits.py
```

---

## Config

The `Config` dataclass has minimal first-class fields:

| Field | Description |
|---|---|
| `library_name` | Library identifier for output naming and uploads |
| `output_root` | Root directory for all kit outputs |
| `upload_dest` | Upload destination root |
| `max_workers` | Max parallel jobs (default: 4) |
| `executor_type` | `"local"` or `"lsf"` |
| `specs` | SpecCollection for incremental change detection |
| `extra` | Dict for domain-specific data (pvts, cells, etc.) |

Unrecognised top-level YAML keys are automatically collected into `extra`.

---

## Kit Interface

Every kit must implement:

| Method | Description |
|---|---|
| `construct_command(target, config)` | Returns shell command as `List[str]` |
| `get_expected_outputs(target, config)` | Returns expected output paths (relative to output dir) |

Optional overrides:

| Method | Default | Description |
|---|---|---|
| `get_targets(config)` | Single target with `pvt="ALL"` | Override for multi-target kits |
| `get_output_path(config)` | `{output_root}/{kit_name}` | Output directory |
| `get_log_error_patterns()` | `[]` | Extra regex patterns for log scanning |
| `get_log_ignore_patterns()` | `[]` | Regex patterns to whitelist |
| `clean_output(target, config)` | Remove output dir | Pre-run cleanup |

---

## False-Negative Prevention

KitDAG guards against four false-negative scenarios:

1. **Missing output**: Expected files verified to exist and be non-empty
2. **Log errors**: Logs scanned for ERROR/FATAL even when exit code is 0
3. **Cascade invalidation**: When upstream re-runs, all downstream targets are invalidated
4. **Stale artifacts**: Output directory cleaned before every re-run

---

## CLI Commands

```bash
kitdag run CONFIG --script KITS.py    # Run pipeline
kitdag run CONFIG --script KITS.py --gui  # Run + launch GUI
kitdag gui CONFIG --script KITS.py    # Launch GUI from saved state
kitdag status WORK_DIR                # Show status summary
```

---

## Running Tests

```bash
python3 -m unittest discover tests/ -v
```

---

## Example

See `examples/three_kit_flow.py` for a complete working example with 3 kits
(liberty, timing_db, lef) demonstrating per-PVT targets, dependency chains,
and kit options from `config.extra`.

```bash
python3 examples/three_kit_flow.py
```
