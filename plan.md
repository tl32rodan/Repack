# KitDAG Universal Refactoring Plan

## Goal
Refactor KitDAG from a repack-specific tool into a universal DAG platform that can handle
both **repack** (one job → per-PVT output checking) and **AP/production** (step expansion
by lib/branch into separate jobs) use cases.

## Core Design: "Scope" Abstraction

**Scope** = `Dict[str, str]` of variant key-value pairs identifying what a job handles.

| Use Case | Scope Example | Meaning |
|----------|--------------|---------|
| Repack (no expansion) | `{}` | One global job |
| Repack (check_by pvt) | `{}` + check_by=["pvt"] | One job, output validated per pvt |
| AP (per lib) | `{lib: "lib_a"}` | One job per library |
| AP (per lib+branch) | `{lib: "lib_a", branch: "ss"}` | One job per (lib, branch) |

### Pipeline Config (new format)

```yaml
output_root: /data/output
executor: local
max_workers: 8

# Variant matrix — defines the execution space
matrix:
  - {lib: lib_a, branch: ss}
  - {lib: lib_a, branch: tt}
  - {lib: lib_a, branch: ff}
  - {lib: lib_b, branch: ss}
  - {lib: lib_b, branch: tt}

steps:
  setup:
    run: setup_kit
    expand_by: [lib]               # one job per unique lib value → 2 jobs
    in:
      ref_dir: /data/source
    out:
      output_dir: "{output_root}/{lib}/setup"
      log: "{output_root}/{lib}/setup/setup.log"
    dependencies: []

  char_sim:
    run: char_sim_kit
    expand_by: [lib, branch]       # one job per (lib, branch) → 5 jobs
    in:
      ref_dir: /data/source
    out:
      output_dir: "{output_root}/{lib}/{branch}/char_sim"
      log: "{output_root}/{lib}/{branch}/char_sim/char_sim.log"
    dependencies:
      - step: setup
        match_by: [lib]            # char_sim(lib_a, ss) depends on setup(lib_a)

  report:
    run: report_kit
    expand_by: [lib]               # one job per lib → 2 jobs
    in: {}
    out:
      output_dir: "{output_root}/{lib}/report"
      log: "{output_root}/{lib}/report/report.log"
    dependencies:
      - step: char_sim
        gather: [branch]           # report(lib_a) waits for ALL char_sim(lib_a, *)
```

### Repack Config (backward compatible)

```yaml
output_root: /tmp/output

steps:
  liberty:
    run: liberty
    check_by: [pvt]               # no expansion, output validated per pvt
    in:
      pvts: [ss_0p75v, tt_0p85v, ff_0p99v]
      library_name: demo_lib
    out:
      output_dir: "{output_root}/liberty"
      log: "{output_root}/liberty/liberty.log"
    dependencies: []
```

### Dependency Resolution Modes

1. **`match_by: [dim]`** — Fan-out/1:1 matching
   - B(lib=a, branch=ss) depends on A(lib=a) when match_by=[lib]
   - Matches on specified dimensions; unmatched dims in A are ignored

2. **`gather: [dim]`** — Fan-in/all-to-one
   - B(lib=a) depends on ALL A(lib=a, branch=*) when gather=[branch]
   - Waits for all jobs across the gathered dimension

3. **Default** (no annotation, just step name string) — match on all shared expand_by dims

---

## Implementation Phases

### Phase 1: Core Data Model (target.py, pipeline.py)

**target.py** changes:
- Rename `PvtStatus` → `VariantStatus` (field `pvt` → `variant`)
- Rename `KitTarget.pvt_details` → `variant_details`
- Rename `pvt_summary` → `variant_summary`
- Add `scope: Dict[str, str]` field to `KitTarget`
- Update `id` property: if scope is non-empty, encode as `step_name/k1=v1/k2=v2`

**pipeline.py** changes:
- Add `matrix: List[Dict[str, str]]` to `PipelineConfig`
- Add `expand_by: List[str]` and `check_by: List[str]` to `StepConfig`
- Change `dependencies` from `List[str]` to `List[Union[str, DependencySpec]]`
  where `DependencySpec = {step: str, match_by?: List[str], gather?: List[str]}`
- Template variable expansion: scope variables ({lib}, {branch}) expanded in `out` fields
- `load_pipeline()`: parse new fields, keep backward compat for simple string dependencies

### Phase 2: Kit Interface (kit.py, kit_loader.py)

**kit.py** changes:
- Rename `pvt_key` → `variant_key: Optional[str]` (backward compat alias)
- Rename `get_expected_pvt_outputs()` → `get_expected_variant_outputs()`
- Keep old names as deprecated aliases for backward compat

**kit_loader.py** changes:
- Update `YamlKit` to use new field names (support both old and new)

### Phase 3: DAG Expansion (dag.py)

**dag.py** changes:
- Add `expand_steps()` method that takes pipeline config + matrix and produces
  expanded targets (one per scope combination)
- For each step with `expand_by`:
  - Extract unique combinations from matrix for those dimensions
  - Create one target per combination with appropriate scope
- For steps without `expand_by` (and without `check_by`): one target, empty scope
- Edge building respects dependency modes:
  - `match_by`: match on specified dimensions
  - `gather`: connect all source variants to single target
  - Default string dep: match on all shared dimensions

### Phase 4: Engine Update (base.py, local.py, cwl.py)

**base.py** changes:
- `_create_targets()`: use DAG expansion to create scoped targets
- Template expansion: scope values injected into output_dir/log_path templates
- `_check_pvt_outputs()` → `_check_variant_outputs()`: use `check_by` + `variant_key`
- Input hash: include scope values in hash computation
- `_reconcile_state()` and `_cascade_invalidation()`: work with scoped target IDs
- Resolve step config per target: merge scope values into inputs

**local.py** / **cwl.py**: Minimal changes (just pass through scoped targets)

### Phase 5: State Manager (manager.py)

**manager.py** changes:
- Add `scope` column to CSV: serialized as `k1=v1;k2=v2`
- Rename `pvt_details` → `variant_details` in CSV header
- `load()`/`save()`: handle scope serialization/deserialization
- Backward compat: if loading old CSV without scope column, treat as empty scope

### Phase 6: GUI Generalization (gui/)

**summary_table.py** changes:
- Replace `_PvtKitTable` / `_OtherKitTable` with a single generic `MatrixTable`
- Matrix view: rows = scope combinations (lib+branch), columns = step names
- For repack check_by mode: rows = variant values, columns = step names
- Support configurable grouping and filtering by any dimension

**app.py** changes:
- Remove hardcoded `pvts` / `corner_kit_names` parameters
- Auto-detect dimensions from pipeline config and target scopes
- Pass matrix info and dimensions to table widget

**dag_view.py** changes:
- Handle expanded target IDs (show shorter labels)
- Support collapsing/expanding variant groups

### Phase 7: CLI Update (cli.py)

- Update `_launch_gui()` to pass new dimension/matrix info instead of pvts/corner_kit_names
- Update `cmd_status()` to display scoped targets properly

### Phase 8: Tests

- Update all existing tests to use new API names
- Add new tests:
  - `test_dag.py`: step expansion, dependency modes (match_by, gather)
  - `test_engine.py`: expanded pipeline execution, incremental runs with scopes
  - `test_state.py`: scope serialization/deserialization
  - `test_pipeline.py`: matrix parsing, dependency spec parsing

### Phase 9: Examples

- Update `three_kit_config.yaml` and `three_kit_flow.py` for new format
- Add new example: `ap_char_flow.py` + `ap_char_config.yaml` showing AP use case

---

## Backward Compatibility Strategy

1. `pvt_key` → alias for `variant_key` (deprecated but functional)
2. `get_expected_pvt_outputs()` → calls `get_expected_variant_outputs()` if overridden
3. Simple string dependencies still work (auto-converted to match-all-shared)
4. Old YAML configs without `matrix` / `expand_by` work unchanged
5. Old CSV state files loadable (missing scope = empty scope)

## File Change Summary

| File | Change Type |
|------|-------------|
| `kitdag/core/target.py` | Modify (rename PVT→Variant, add scope) |
| `kitdag/pipeline.py` | Modify (add matrix, expand_by, check_by, DependencySpec) |
| `kitdag/core/kit.py` | Modify (rename pvt_key→variant_key with alias) |
| `kitdag/core/kit_loader.py` | Modify (update field names) |
| `kitdag/core/dag.py` | Modify (add expansion logic, dependency resolution) |
| `kitdag/engine/base.py` | Modify (scoped targets, variant checking) |
| `kitdag/engine/local.py` | Minor modify |
| `kitdag/engine/cwl.py` | Minor modify |
| `kitdag/state/manager.py` | Modify (scope column, rename pvt→variant) |
| `kitdag/gui/summary_table.py` | Major rewrite (generic matrix table) |
| `kitdag/gui/app.py` | Modify (remove PVT-specific params) |
| `kitdag/gui/dag_view.py` | Minor modify (handle long scoped IDs) |
| `kitdag/cli.py` | Modify (pass new params to GUI) |
| `tests/*.py` | Update all tests |
| `examples/*` | Update + add AP example |
