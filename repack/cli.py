"""CLI entry point for Repack."""

import argparse
import logging
import sys
from typing import List, Optional

from repack.config import RepackConfig, load_config


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repack",
        description="Repack - Standard cell library kit repack utility",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Execute repack pipeline")
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

    # --- convert command ---
    convert_parser = subparsers.add_parser(
        "convert", help="Convert ddi.sh to YAML config"
    )
    convert_parser.add_argument(
        "ddi_sh", help="Path to ddi.sh file"
    )
    convert_parser.add_argument(
        "-o", "--output", default="repack_config.yaml",
        help="Output YAML config path"
    )

    # --- status command ---
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument(
        "work_dir", help="Repack work directory (containing repack_status.csv)"
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
    """Show current repack status."""
    from repack.state.manager import StateManager

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

    if args.command == "convert":
        from repack.compat.ddi_converter import DDIConverter
        import yaml

        converter = DDIConverter()
        config = converter.from_ddi_sh(args.ddi_sh)
        # Serialize to YAML (simplified)
        data = {
            "old_name": config.old_name,
            "old_ver": config.old_ver,
            "new_name": config.new_name,
            "new_ver": config.new_ver,
            "library_name": config.library_name,
            "source_lib": config.source_lib,
            "output_root": config.output_root,
            "upload_dest": config.upload_dest,
            "pvts": config.pvts,
            "cells": config.cells,
            "executor_type": config.executor_type,
            "max_workers": config.max_workers,
            "extra": config.extra,
        }
        with open(args.output, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        print(f"Config written to {args.output}")
        return 0

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
        from repack.engine import RepackEngine
        engine = RepackEngine(
            config=config,
            kits=kits,
            executor=executor,
            max_retries=args.max_retries,
        )
        success = engine.run()

        # Optionally launch GUI
        if args.gui:
            from repack.core.kit import CornerBasedKit
            from repack.gui.app import RepackGUI
            corner_names = [
                k.name for k in kits if isinstance(k, CornerBasedKit)
            ]
            RepackGUI.launch(
                targets=engine.get_targets(),
                dag=engine.get_dag(),
                pvts=config.pvts,
                corner_kit_names=corner_names,
            )

        return 0 if success else 1

    if args.command == "gui":
        kits = _load_kits(args.script, config) if args.script else []

        from repack.core.kit import CornerBasedKit
        from repack.gui.app import RepackGUI
        from repack.state.manager import StateManager

        state = StateManager(work_dir=config.output_root)
        targets = state.load()

        from repack.core.dag import DAGBuilder
        dag = DAGBuilder()
        dag.add_targets(list(targets.values()))
        if kits:
            kit_deps = {k.name: k.dependencies for k in kits}
            dag.build_edges(kit_deps)

        corner_names = [
            k.name for k in kits if isinstance(k, CornerBasedKit)
        ]
        return RepackGUI.launch(
            targets=targets,
            dag=dag,
            pvts=config.pvts,
            corner_kit_names=corner_names,
        )

    return 0


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


def _create_executor(config: RepackConfig):
    """Create the appropriate executor based on config."""
    if config.executor_type == "lsf":
        # LSFExecutor is abstract - users must subclass it.
        # For now, fall back to local with a warning.
        logging.getLogger(__name__).warning(
            "LSFExecutor requires site-specific subclass. "
            "Falling back to LocalExecutor."
        )
        from repack.executor.local import LocalExecutor
        return LocalExecutor(max_workers=config.max_workers)
    else:
        from repack.executor.local import LocalExecutor
        return LocalExecutor(max_workers=config.max_workers)


if __name__ == "__main__":
    sys.exit(main())
