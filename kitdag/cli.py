"""CLI entry point for kitdag."""

import argparse
import logging
import sys
from typing import List, Optional


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kitdag",
        description="kitdag - Universal DAG platform for kit generation",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Execute kitdag pipeline")
    run_parser.add_argument("flow_script", help="Path to Python flow definition script")
    run_parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Max auto-retry attempts (default: 3)",
    )
    run_parser.add_argument(
        "--gui", action="store_true",
        help="Launch dashboard after execution",
    )

    # --- gui command ---
    gui_parser = subparsers.add_parser("gui", help="Launch dashboard from saved state")
    gui_parser.add_argument("flow_script", help="Path to Python flow definition script")

    # --- status command ---
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument("work_dir", help="Work directory (containing kitdag_status.csv)")

    # --- viz command ---
    viz_parser = subparsers.add_parser("viz", help="Visualize DAG as mermaid")
    viz_parser.add_argument("flow_script", help="Path to Python flow definition script")
    viz_parser.add_argument(
        "--lib", default=None,
        help="Show concrete DAG for a specific lib (requires get_branches in flow script)",
    )
    viz_parser.add_argument(
        "-o", "--output", default=None,
        help="Write mermaid to file instead of stdout",
    )

    # Global options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    return parser.parse_args(argv)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_flow_module(script_path: str):
    """Load a flow definition from a Python script.

    The script should define:
    - flow: Flow instance
    - get_branches(lib, step_name) -> list[str]
    - get_inputs(lib, branch, step_name) -> dict
    - libs: list[str]
    - output_root: str
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("flow_def", script_path)
    if spec is None or spec.loader is None:
        print(f"Error: cannot load flow script: {script_path}")
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_status(args: argparse.Namespace) -> int:
    """Show current kitdag status."""
    from kitdag.state.manager import StateManager

    state = StateManager(work_dir=args.work_dir)
    tasks = state.load()

    if not tasks:
        print("No status file found.")
        return 1

    summary = {}
    for t in tasks.values():
        key = t.status.value
        summary[key] = summary.get(key, 0) + 1

    print(f"Total tasks: {len(tasks)}")
    for status, count in sorted(summary.items()):
        print(f"  {status}: {count}")

    from kitdag.core.task import TaskStatus
    failures = [t for t in tasks.values() if t.status == TaskStatus.FAIL]
    if failures:
        print(f"\nFailed tasks ({len(failures)}):")
        for t in failures:
            msg = t.error_message
            if t.variant_details:
                msg = f"{t.variant_summary} - {msg}"
            print(f"  {t.id}: {msg}")

    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    """Visualize DAG as mermaid."""
    module = _load_flow_module(args.flow_script)
    flow = module.flow

    if args.lib and hasattr(module, "get_branches"):
        mermaid = flow.to_mermaid(lib=args.lib, get_branches=module.get_branches)
    else:
        mermaid = flow.to_mermaid()

    if args.output:
        with open(args.output, "w") as f:
            f.write(mermaid)
        print(f"Mermaid diagram written to {args.output}")
    else:
        print(mermaid)

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the pipeline."""
    module = _load_flow_module(args.flow_script)
    flow = module.flow

    pipeline = flow.build(
        libs=module.libs,
        get_branches=module.get_branches,
        get_inputs=module.get_inputs,
        output_root=module.output_root,
    )

    from kitdag.engine.local import LocalEngine

    engine = LocalEngine(
        pipeline=pipeline,
        get_inputs=module.get_inputs,
        max_retries=args.max_retries,
    )

    success = engine.run()

    if args.gui:
        _launch_gui(engine.get_tasks(), engine.get_dag(), flow)

    return 0 if success else 1


def cmd_gui(args: argparse.Namespace) -> int:
    """Launch dashboard from saved state."""
    module = _load_flow_module(args.flow_script)
    flow = module.flow

    pipeline = flow.build(
        libs=module.libs,
        get_branches=module.get_branches,
        get_inputs=module.get_inputs,
        output_root=module.output_root,
    )

    from kitdag.state.manager import StateManager

    state = StateManager(work_dir=module.output_root)
    tasks = state.load()

    if not tasks:
        print("No status file found. Run the pipeline first.")
        return 1

    return _launch_gui(tasks, pipeline.dag, flow)


def _launch_gui(tasks, dag, flow):
    """Launch the KitDAG dashboard."""
    from kitdag.gui.app import KitDAGApp

    step_order = list(flow.steps.keys())
    return KitDAGApp.launch(
        tasks=tasks,
        dag=dag,
        step_order=step_order,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(getattr(args, "verbose", False))

    if args.command is None:
        parse_args(["--help"])
        return 1

    if args.command == "status":
        return cmd_status(args)
    if args.command == "viz":
        return cmd_viz(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "gui":
        return cmd_gui(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
