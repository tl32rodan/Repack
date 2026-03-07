"""CLI entry point for kitdag."""

import argparse
import logging
import sys
from typing import List, Optional


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kitdag",
        description="kitdag - Kit generation DAG platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Execute kitdag pipeline")
    run_parser.add_argument("input", help="Path to input.yaml")
    run_parser.add_argument("--kits", help="Path to Python script defining kits")
    run_parser.add_argument(
        "--executor", choices=["local", "cwl"], default=None,
        help="Override executor type (default: from input.yaml)",
    )
    run_parser.add_argument(
        "--max-workers", type=int, default=None,
        help="Max parallel workers (local engine)",
    )
    run_parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Max auto-retry attempts (default: 3)",
    )
    run_parser.add_argument(
        "--gui", action="store_true",
        help="Launch dashboard after execution",
    )

    # --- gui command ---
    gui_parser = subparsers.add_parser("gui", help="Launch dashboard")
    gui_parser.add_argument("input", help="Path to input.yaml")
    gui_parser.add_argument("--kits", help="Path to Python script defining kits")

    # --- status command ---
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument("work_dir", help="Work directory (containing kitdag_status.csv)")

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


def cmd_status(args: argparse.Namespace) -> int:
    """Show current kitdag status."""
    from kitdag.state.manager import StateManager

    state = StateManager(work_dir=args.work_dir)
    targets = state.load()

    if not targets:
        print("No status file found.")
        return 1

    summary = {}
    for t in targets.values():
        key = t.status.value
        summary[key] = summary.get(key, 0) + 1

    print(f"Total targets: {len(targets)}")
    for status, count in sorted(summary.items()):
        print(f"  {status}: {count}")

    failures = [t for t in targets.values() if t.status.value == "FAIL"]
    if failures:
        print(f"\nFailed targets ({len(failures)}):")
        for t in failures:
            msg = t.error_message
            if t.pvt_details:
                msg = f"{t.pvt_summary} - {msg}"
            print(f"  {t.id}: {msg}")

    return 0


def _load_kits(args, pipeline):
    """Load kit definitions from --kits script."""
    from kitdag.core.kit_loader import load_kits_from_script

    if not getattr(args, "kits", None):
        return {}

    kits = load_kits_from_script(args.kits, pipeline)
    return {k.name: k for k in kits}


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(getattr(args, "verbose", False))

    if args.command is None:
        parse_args(["--help"])
        return 1

    if args.command == "status":
        return cmd_status(args)

    # For run/gui, load pipeline config
    from kitdag.pipeline import load_pipeline

    pipeline = load_pipeline(args.input)

    # Apply CLI overrides
    if getattr(args, "executor", None):
        pipeline.executor = args.executor
    if getattr(args, "max_workers", None):
        pipeline.max_workers = args.max_workers

    # Load kit definitions
    kits = _load_kits(args, pipeline)
    if not kits:
        print("Error: no kits defined. Use --kits to specify kit definitions.")
        return 1

    if args.command == "run":
        # Select engine
        if pipeline.executor == "cwl":
            from kitdag.engine.cwl import CwlEngine
            engine = CwlEngine(
                pipeline=pipeline, kits=kits,
                max_retries=args.max_retries,
            )
        else:
            from kitdag.engine.local import LocalEngine
            engine = LocalEngine(
                pipeline=pipeline, kits=kits,
                max_retries=args.max_retries,
            )

        success = engine.run()

        if args.gui:
            _launch_gui(engine.get_targets(), engine.get_dag(), kits, pipeline)

        return 0 if success else 1

    if args.command == "gui":
        from kitdag.state.manager import StateManager
        from kitdag.core.dag import DAGBuilder

        state = StateManager(work_dir=pipeline.output_root)
        targets = state.load()

        dag = DAGBuilder()
        dag.add_targets(list(targets.values()))
        kit_deps = {
            name: step.dependencies
            for name, step in pipeline.steps.items()
        }
        dag.build_edges(kit_deps)

        return _launch_gui(targets, dag, kits, pipeline)

    return 0


def _launch_gui(targets, dag, kits, pipeline):
    """Launch the KitDAG dashboard."""
    from kitdag.gui.app import KitDAGApp

    pvts = set()
    corner_kit_names = []
    for name, kit in kits.items():
        if kit.pvt_key:
            corner_kit_names.append(name)
            step = pipeline.steps.get(name)
            if step:
                step_pvts = step.inputs.get(kit.pvt_key, [])
                if isinstance(step_pvts, list):
                    pvts.update(step_pvts)

    return KitDAGApp.launch(
        targets=targets,
        dag=dag,
        pvts=sorted(pvts),
        corner_kit_names=corner_kit_names,
    )


if __name__ == "__main__":
    sys.exit(main())
