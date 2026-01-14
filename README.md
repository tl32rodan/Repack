# Repack Framework

Repack is a Python-based framework for automating standard cell library kit generation. It supports flexible kit definitions, incremental runs using a persistent state (CSV), and execution agnostic backends (Local and LSF).

## Features

*   **Flexible Kit Definitions**: Custom commands, output paths, and dependencies.
*   **Incremental Runs**: Tracks job status in a CSV file (`repack_status.csv`). Only re-runs PENDING or FAILED jobs.
*   **Execution Agnostic**:
    *   `LocalExecutor`: Runs jobs locally using subprocesses and thread pools.
    *   `LSFExecutor`: Submits jobs to an LSF cluster (requires `bsub` available).
*   **Dependency Management**: Automatic DAG construction and topological sorting of kit targets.

## Usage

### Prerequisites

*   Python 3.9+ (or Python 3)

### Running the Demo

A demo script is provided to illustrate how to define kits and run the engine.

```bash
make demo
```

This will execute `demo/demo.py` using the `bin/repack` wrapper. It simulates a run with two kits (`KitA` and `KitB`), where `KitB` depends on `KitA`.

### Running Tests

```bash
make test
```

### Cleaning Artifacts

To clean demo outputs and compiled python files:

```bash
make clean
```

## Architecture

*   **`repack.core`**: Contains domain models (`Kit`, `KitTarget`, `RepackRequest`) and state management (`StateManager`).
*   **`repack.engine`**: Contains the `RepackEngine` responsible for orchestration, dependency resolution, and job dispatch.
*   **`repack.executor`**: Defines the `Executor` interface and concrete implementations (`LocalExecutor`, `LSFExecutor`).

## Directory Structure

```
repack/
  core/
  engine/
  executor/
bin/
  repack       # CLI wrapper
demo/
  demo.py      # Demo script
tests/
  ...
```
