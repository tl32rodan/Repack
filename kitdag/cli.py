"""CLI entry point for kitdag."""

import argparse
import logging
import sys
from typing import List, Optional

from kitdag.config import Config, load_config


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kitdag",
        description="kitdag - Kit generation DAG platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Execute kitdag pipeline")
    run_parser.add_argument(
        "config", help="Path to YAML config file"
    )
    run_parser.add_argument(
        "--script", help="Path to Python script defining kits"
    )
    run_parser.add_argument(
        "--executor", choices=["local", "lsf"], default=None,
        help="Override executor type"
    )
    run_parser.add_argument(
        "--max-workers", type=int, default=None,
        help="Max parallel workers (local executor)"
    )
    run_parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Max auto-retry attempts for failed targets (default: 3)"
    )
    run_parser.add_argument(
        "--gui", action="store_true",
        help="Launch GUI after execution"
    )

    # --- gui command ---
    gui_parser = subparsers.add_parser("gui", help="Launch summary GUI")
    gui_parser.add_argument(
        "config", help="Path to YAML config file"
    )
    gui_parser.add_argument(
        "--script", help="Path to Python script defining kits"
    )

    # --- status command ---
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument(
        "work_dir", help="KitDAG work directory (containing kitdag_status.csv)"
    )

    # Global options
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )

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

    # Print summary
    summary = {}
    for t in targets.values():
        key = t.status.value
        summary[key] = summary.get(key, 0) + 1

    print(f"Total targets: {len(targets)}")
    for status, count in sorted(summary.items()):
        print(f"  {status}: {count}")

    # Print failures
    failures = [t for t in targets.values() if t.status.value == "FAIL"]
    if failures:
        print(f"\nFailed targets ({len(failures)}):")
        for t in failures:
            print(f"  {t.id}: {t.error_message}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(getattr(args, "verbose", False))

    if args.command is None:
        parse_args(["--help"])
        return 1

    if args.command == "status":
        return cmd_status(args)

    # For run/gui commands, config is required
    config = load_config(args.config)

    # Apply CLI overrides
    if hasattr(args, "executor") and args.executor:
        config.executor_type = args.executor
    if hasattr(args, "max_workers") and args.max_workers:
        config.max_workers = args.max_workers

    if args.command == "run":
        # Load kit definitions from script
        kits = _load_kits(args.script, config) if args.script else []
        if not kits:
            print("Error: no kits defined. Use --script to specify kit definitions.")
            return 1

        # Create executor
        executor = _create_executor(config)

        # Run engine
        from kitdag.engine import Engine
        engine = Engine(
            config=config,
            kits=kits,
            executor=executor,
            max_retries=args.max_retries,
        )
        success = engine.run()

        # Optionally launch GUI
        if args.gui:
            _launch_gui(engine.get_targets(), engine.get_dag(), kits, config)

        return 0 if success else 1

    if args.command == "gui":
        kits = _load_kits(args.script, config) if args.script else []

        from kitdag.state.manager import StateManager
        from kitdag.core.dag import DAGBuilder

        state = StateManager(work_dir=config.output_root)
        targets = state.load()

        dag = DAGBuilder()
        dag.add_targets(list(targets.values()))
        if kits:
            kit_deps = {k.name: k.dependencies for k in kits}
            dag.build_edges(kit_deps)

        return _launch_gui(targets, dag, kits, config)

    return 0


def _launch_gui(targets, dag, kits, config):
    """Launch the KitDAG GUI."""
    from kitdag.gui.app import KitDAGApp

    # Collect pvts from kit targets
    pvts = sorted({t.pvt for t in targets.values() if t.pvt != "ALL"})
    # All kits with per-pvt targets are "corner kits"
    corner_kit_names = []
    for kit in kits:
        kit_targets = kit.get_targets(config)
        if any(t.pvt != "ALL" for t in kit_targets):
            corner_kit_names.append(kit.name)

    return KitDAGApp.launch(
        targets=targets,
        dag=dag,
        pvts=pvts,
        corner_kit_names=corner_kit_names,
    )


def _load_kits(script_path, config):
    """Load kit definitions from a Python script.

    The script should define a function `register_kits(config)` that
    returns a list of Kit instances.
    """
    import importlib.util

    if not script_path:
        return []

    spec = importlib.util.spec_from_file_location("kit_defs", script_path)
    if spec is None or spec.loader is None:
        print(f"Error: cannot load kit script: {script_path}")
        return []

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "register_kits"):
        return module.register_kits(config)
    else:
        print(f"Warning: {script_path} has no register_kits() function")
        return []


def _create_executor(config: Config):
    """Create the appropriate executor based on config."""
    if config.executor_type == "lsf":
        logging.getLogger(__name__).warning(
            "LSFExecutor requires site-specific subclass. "
            "Falling back to LocalExecutor."
        )
        from kitdag.executor.local import LocalExecutor
        return LocalExecutor(max_workers=config.max_workers)
    else:
        from kitdag.executor.local import LocalExecutor
        return LocalExecutor(max_workers=config.max_workers)


if __name__ == "__main__":
    sys.exit(main())
