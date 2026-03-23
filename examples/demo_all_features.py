#!/usr/bin/env python3
"""Comprehensive demo of ALL KitDAG features.

Runs the full_signoff_flow and then demonstrates:
  1. Mermaid DAG visualization (abstract + per-lib concrete)
  2. Pipeline execution with mixed results
  3. Text-based dashboard (matrix table like the GUI)
  4. Per-PVT variant detail sub-tables (layer 2)
  5. State persistence & status summary
  6. Incremental re-run (skip unchanged PASS tasks)
  7. Cascade invalidation
"""

import logging
import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitdag.core.task import TaskStatus

# Import the flow definition
from full_signoff_flow import (
    flow, libs, output_root, get_branches, get_inputs,
    LIB_BRANCHES, BRANCH_PVTS,
)

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
GRAY = "\033[90m"
RESET = "\033[0m"

STATUS_SYMBOL = {
    TaskStatus.PASS: f"{GREEN}O{RESET}",
    TaskStatus.FAIL: f"{RED}X{RESET}",
    TaskStatus.SKIP: f"{GRAY}-{RESET}",
    TaskStatus.PENDING: f"{YELLOW}?{RESET}",
    TaskStatus.RUNNING: f"{BLUE}~{RESET}",
}


def banner(text):
    width = 70
    print()
    print(f"{BOLD}{CYAN}{'=' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * width}{RESET}")
    print()


def section(text):
    print(f"\n{BOLD}{BLUE}--- {text} ---{RESET}\n")


def print_mermaid(title, mermaid_text):
    """Print mermaid diagram with syntax highlighting."""
    section(title)
    for line in mermaid_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("graph") or stripped.startswith("subgraph"):
            print(f"  {CYAN}{line}{RESET}")
        elif "-->" in stripped:
            print(f"  {DIM}{line}{RESET}")
        elif stripped == "end":
            print(f"  {CYAN}{line}{RESET}")
        else:
            print(f"  {line}")


def print_matrix_table(tasks, step_order, lib):
    """Print a text-based matrix table (like the GUI MatrixSummaryWidget)."""
    lib_tasks = {tid: t for tid, t in tasks.items() if t.scope.get("lib") == lib}
    branches = sorted(set(t.branch for t in lib_tasks.values() if t.branch))
    if not branches:
        branches = [""]

    # Filter step_order to steps that have tasks for this lib
    active_steps = set(t.step_name for t in lib_tasks.values())
    steps = [s for s in step_order if s in active_steps]

    # Build lookup
    lookup = {}
    for t in lib_tasks.values():
        lookup[(t.branch, t.step_name)] = t

    # Column widths
    branch_w = max(len(b) for b in branches) if branches and branches != [""] else 7
    branch_w = max(branch_w, 7)
    col_w = max(max(len(s) for s in steps), 8)

    # Header
    header = f"  {'branch':<{branch_w}}"
    for s in steps:
        header += f" | {s:^{col_w}}"
    print(f"  {BOLD}{header}{RESET}")
    print(f"  {'-' * len(header)}")

    # Rows
    for branch in branches:
        br_label = branch if branch else "(all)"
        row = f"  {br_label:<{branch_w}}"
        for step in steps:
            task = lookup.get((branch, step))
            if task is None:
                cell = f"{GRAY}  -  {RESET}"
            else:
                sym = STATUS_SYMBOL.get(task.status, "?")
                has_detail = bool(task.variant_details)
                if has_detail and task.status == TaskStatus.PASS:
                    cell = f" {sym}{DIM}[+]{RESET}"
                elif has_detail and task.status == TaskStatus.FAIL:
                    cell = f" {sym}{RED}[!]{RESET}"
                else:
                    cell = f"  {sym}  "
            row += f" | {cell:^{col_w + 9}}"  # +9 for ANSI codes
        print(row)

    print()


def print_variant_detail(task):
    """Print per-PVT sub-table for a task (layer 2 detail)."""
    if not task.variant_details:
        return

    # Group by variant
    variants = []
    products = []
    grid = {}
    seen_variants = []
    seen_products = set()

    for d in task.variant_details:
        if d.variant not in grid:
            grid[d.variant] = {}
            seen_variants.append(d.variant)
        grid[d.variant][d.product] = d
        if d.product not in seen_products:
            products.append(d.product)
            seen_products.add(d.product)

    variants = seen_variants
    pvt_w = max(len(v) for v in variants)
    prod_w = max(len(p) for p in products)

    print(f"    {BOLD}PVT Detail: {task.id} ({task.variant_summary}){RESET}")

    # Header
    hdr = f"    {'PVT':<{pvt_w}}"
    for p in products:
        hdr += f"  {p:^{prod_w + 2}}"
    print(f"    {hdr}")
    print(f"    {'-' * len(hdr)}")

    for variant in variants:
        row = f"    {variant:<{pvt_w}}"
        for product in products:
            d = grid.get(variant, {}).get(product)
            if d:
                sym = f"{GREEN}O{RESET}" if d.ok else f"{RED}X{RESET}"
            else:
                sym = f"{GRAY}-{RESET}"
            row += f"    {sym}    "
        print(row)
    print()


def print_log_errors(tasks):
    """Show log errors for failed tasks."""
    failed = [t for t in tasks.values() if t.status == TaskStatus.FAIL]
    if not failed:
        return

    section("Failed Task Details")
    for t in failed:
        print(f"  {RED}X{RESET} {BOLD}{t.id}{RESET}")
        if t.error_message:
            # Wrap long error messages
            for line in t.error_message.split(" | "):
                print(f"    {DIM}{line}{RESET}")
        if t.log_path and os.path.exists(t.log_path):
            with open(t.log_path) as f:
                lines = f.readlines()
            error_lines = [l.rstrip() for l in lines if "ERROR" in l.upper() or "FATAL" in l.upper()]
            if error_lines:
                print(f"    {DIM}Log errors:{RESET}")
                for el in error_lines[:5]:
                    print(f"      {RED}{el}{RESET}")
        print()


def print_execution_stages(dag, tasks):
    """Show parallelizable execution stages."""
    stages = dag.get_execution_stages()
    section(f"Execution Stages ({len(stages)} stages)")
    for i, stage in enumerate(stages):
        statuses = []
        for tid in stage:
            t = tasks.get(tid)
            sym = STATUS_SYMBOL.get(t.status, "?") if t else "?"
            # Short label
            parts = tid.split("/")
            if len(parts) >= 2:
                label = f"{parts[0]}/{parts[-1].split('=')[-1]}"
            else:
                label = tid
            statuses.append(f"{sym} {label}")
        print(f"  Stage {i}: [{', '.join(statuses)}]")
    print()


def print_state_file(output_root):
    """Show the persisted state CSV."""
    from kitdag.state.manager import StateManager
    state = StateManager(output_root)
    state_tasks = state.load()
    if state_tasks:
        summary = {}
        for t in state_tasks.values():
            summary[t.status.value] = summary.get(t.status.value, 0) + 1
        print(f"  State file: {state.state_path}")
        print(f"  Persisted: {len(state_tasks)} tasks")
        print(f"  Summary: {summary}")
    else:
        print(f"  {DIM}No state file found{RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Main demo
# ═══════════════════════════════════════════════════════════════════════

def main():
    banner("KitDAG Full Feature Demo")

    # ── 1. Show flow structure ──
    section("Flow Structure")
    print(f"  Flow name: {flow.name}")
    print(f"  Steps: {list(flow.steps.keys())}")
    print(f"  Dependencies: {len(flow.deps)}")
    for dep in flow.deps:
        bm = f" branch_map={dep.branch_map}" if dep.branch_map else ""
        print(f"    {dep.upstream} → {dep.downstream}{bm}")

    # ── 2. Library configuration ──
    section("Library Configuration")
    for lib in libs:
        branches = LIB_BRANCHES.get(lib, [])
        total_pvts = sum(len(BRANCH_PVTS.get(b, [])) for b in branches)
        print(f"  {lib}: branches={branches}, total PVTs={total_pvts}")

    # ── 3. Mermaid DAG visualization ──
    print_mermaid("Abstract DAG (step-level)", flow.to_mermaid())

    print_mermaid(
        "Concrete DAG for lib_7nm_hvt (full 4-branch)",
        flow.to_mermaid(lib="lib_7nm_hvt", get_branches=get_branches),
    )

    print_mermaid(
        "Concrete DAG for lib_7nm_lvt (minimal 2-branch)",
        flow.to_mermaid(lib="lib_7nm_lvt", get_branches=get_branches),
    )

    # ── 4. Build pipeline ──
    section("Building Pipeline")
    pipeline = flow.build(
        libs=libs,
        get_branches=get_branches,
        get_inputs=get_inputs,
        output_root=output_root,
    )
    print(f"  Total tasks: {len(pipeline.tasks)}")
    for lib in pipeline.libs:
        lib_tasks = pipeline.tasks_for_lib(lib)
        branches = sorted(set(t.branch for t in lib_tasks.values() if t.branch))
        print(f"  {lib}: {len(lib_tasks)} tasks, branches={branches}")

    # ── 5. Show execution stages ──
    print_execution_stages(pipeline.dag, pipeline.tasks)

    # ── 6. Execute ──
    banner("Execution (Run 1 — Full)")
    print(f"  Output root: {output_root}")
    print(f"  Expected: lib_5nm_hvt will FAIL (log errors)")
    print(f"  Expected: lib_7nm_svt/em/compile will FAIL (missing PVT output)")
    print(f"  Expected: all others PASS")
    print()

    from kitdag.engine.local import LocalEngine
    engine = LocalEngine(pipeline=pipeline, get_inputs=get_inputs, max_retries=1)
    success = engine.run()
    tasks = engine.get_tasks()

    print(f"\n  {BOLD}Overall: {'PASS' if success else 'FAIL'}{RESET}")

    # ── 7. Text dashboard (matrix tables) ──
    banner("Dashboard — Matrix Summary Tables")
    step_order = list(flow.steps.keys())

    for lib in pipeline.libs:
        lib_tasks = {tid: t for tid, t in tasks.items() if t.scope.get("lib") == lib}
        passed = sum(1 for t in lib_tasks.values() if t.status == TaskStatus.PASS)
        failed = sum(1 for t in lib_tasks.values() if t.status == TaskStatus.FAIL)
        total = len(lib_tasks)
        status_line = f"{GREEN}{passed}O{RESET}" if passed else ""
        if failed:
            status_line += f" {RED}{failed}X{RESET}"

        print(f"  {BOLD}▼ {lib}{RESET}  ({total} tasks: {status_line})")
        print_matrix_table(tasks, step_order, lib)

    # ── 8. Per-PVT variant detail sub-tables ──
    banner("Layer 2 — Per-PVT Variant Detail")
    for tid, task in sorted(tasks.items()):
        if task.variant_details:
            print_variant_detail(task)

    # ── 9. Failed task details + log errors ──
    print_log_errors(tasks)

    # ── 10. State persistence ──
    section("State Persistence")
    print_state_file(output_root)

    # ── 11. Incremental re-run ──
    banner("Execution (Run 2 — Incremental)")
    print(f"  Re-running with same inputs...")
    print(f"  Expected: all PASS tasks SKIPPED (unchanged)")
    print(f"  Expected: FAIL tasks re-attempted")
    print()

    pipeline2 = flow.build(
        libs=libs,
        get_branches=get_branches,
        get_inputs=get_inputs,
        output_root=output_root,
    )
    engine2 = LocalEngine(pipeline=pipeline2, get_inputs=get_inputs, max_retries=0)
    success2 = engine2.run()
    tasks2 = engine2.get_tasks()

    print(f"\n  {BOLD}Overall: {'PASS' if success2 else 'FAIL'}{RESET}")

    # Show which tasks were skipped vs re-run
    section("Incremental Run Summary")
    print(f"  {'Task':<50} {'Status':<10} {'Note'}")
    print(f"  {'-'*50} {'-'*10} {'-'*20}")
    for tid in sorted(tasks2.keys()):
        t = tasks2[tid]
        old = tasks.get(tid)
        sym = STATUS_SYMBOL.get(t.status, "?")
        if old and old.status == TaskStatus.PASS and t.status == TaskStatus.PASS:
            note = f"{DIM}(skipped — unchanged){RESET}"
        elif old and old.status == TaskStatus.FAIL:
            note = f"{YELLOW}(re-attempted){RESET}"
        else:
            note = ""
        # Short ID
        short = tid if len(tid) < 48 else "..." + tid[-45:]
        print(f"  {short:<50} {sym:<18} {note}")

    # ── 12. Final summary ──
    banner("Summary")
    total = len(tasks2)
    by_status = {}
    for t in tasks2.values():
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

    for status_name, count in sorted(by_status.items()):
        pct = count / total * 100
        bar_len = int(pct / 2)
        if status_name == "PASS":
            color = GREEN
        elif status_name == "FAIL":
            color = RED
        else:
            color = YELLOW
        bar = f"{color}{'█' * bar_len}{RESET}{'░' * (50 - bar_len)}"
        print(f"  {status_name:>8}: {bar} {count}/{total} ({pct:.0f}%)")

    print()
    print(f"  {BOLD}Features demonstrated:{RESET}")
    print(f"    ✓ Multi-lib pipeline (4 libs, different branch configs)")
    print(f"    ✓ Scope-based expansion ({total} tasks from 6 steps)")
    print(f"    ✓ Cross-branch dependencies (compile/corner ← char/all)")
    print(f"    ✓ Intra-step dependencies (compile/em ← compile/corner)")
    print(f"    ✓ Fan-in (merge ← all signoff branches)")
    print(f"    ✓ Per-PVT variant output checking (layer 2)")
    print(f"    ✓ Log error detection (false-negative prevention)")
    print(f"    ✓ Cascade failure (upstream FAIL → downstream FAIL)")
    print(f"    ✓ State persistence (CSV)")
    print(f"    ✓ Incremental re-run (skip unchanged PASS tasks)")
    print(f"    ✓ Mermaid DAG visualization (abstract + concrete)")
    print(f"    ✓ Text matrix dashboard (branch × step grid)")
    print()


if __name__ == "__main__":
    main()
