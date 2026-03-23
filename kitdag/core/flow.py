"""Flow — declarative DAG definition with scope-based expansion.

A Flow defines:
  1. Steps (command templates)
  2. Dependencies between steps (with branch_map for cross-branch deps)

At build() time, the flow is expanded into concrete Tasks using:
  - libs: list of library names
  - get_branches(lib, step_name) -> list[str]: which branches per (lib, step)
  - get_inputs(lib, branch, step_name) -> dict: inputs for each task

Dependency resolution:
  - Auto-resolved by matching on intersecting scope keys
  - branch_map overrides: specify which upstream branches a downstream branch needs
  - Auto-intersection: if upstream branch doesn't exist for a lib, it's skipped
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from kitdag.core.step import Step
from kitdag.core.task import Task

logger = logging.getLogger(__name__)


@dataclass
class Dependency:
    """A dependency declaration between steps.

    Attributes:
        downstream: step that depends on upstream
        upstream: step being depended on
        branch_map: {downstream_branch: [upstream_branches_needed]}
            Branches not in the map default to same-branch matching.
            If upstream == downstream, this defines intra-step branch deps.
    """

    downstream: str
    upstream: str
    branch_map: Dict[str, List[str]] = field(default_factory=dict)


class Flow:
    """Declarative DAG definition.

    Usage::

        flow = Flow("ap_char")
        flow.add_step("extract", kit=ExtractKit())
        flow.add_step("char",    kit=CharKit())
        flow.add_dep("char", on="extract")

        pipeline = flow.build(
            libs=["lib_a", "lib_b"],
            get_branches=my_get_branches,
            get_inputs=my_get_inputs,
            output_root="/data/output",
        )
    """

    def __init__(self, name: str = ""):
        self.name = name
        self._steps: Dict[str, Step] = {}
        self._step_order: List[str] = []
        self._deps: List[Dependency] = []

    def add_step(self, name: str, kit: Step) -> None:
        """Register a step with its command template (Kit/Step)."""
        if name in self._steps:
            raise ValueError(f"Step '{name}' already registered")
        kit.name = name
        self._steps[name] = kit
        self._step_order.append(name)

    def add_dep(
        self,
        step: str,
        on: str,
        branch_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Declare a dependency: ``step`` depends on ``on``.

        Args:
            step: downstream step name
            on: upstream step name
            branch_map: optional cross-branch mapping.
                {downstream_branch: [list of upstream branches needed]}.
                Branches not in the map default to same-branch matching.
                At build time, the upstream branch list is auto-intersected
                with the lib's actual branches.
        """
        if step not in self._steps:
            raise ValueError(f"Unknown step '{step}'")
        if on not in self._steps:
            raise ValueError(f"Unknown step '{on}'")
        self._deps.append(Dependency(
            downstream=step,
            upstream=on,
            branch_map=branch_map or {},
        ))

    def get_step(self, name: str) -> Step:
        """Get a step by name."""
        return self._steps[name]

    @property
    def steps(self) -> Dict[str, Step]:
        return dict(self._steps)

    @property
    def deps(self) -> List[Dependency]:
        return list(self._deps)

    # ------------------------------------------------------------------
    # Build: expand flow into concrete tasks
    # ------------------------------------------------------------------

    def build(
        self,
        libs: List[str],
        get_branches: Callable[[str, str], List[str]],
        get_inputs: Callable[[str, str, str], Dict[str, Any]],
        output_root: str,
    ) -> "Pipeline":
        """Expand the flow into a concrete Pipeline of Tasks.

        Args:
            libs: list of library names (primary key)
            get_branches: (lib, step_name) -> list of branch names.
                Return [] for per-lib-only steps (no branch expansion).
            get_inputs: (lib, branch, step_name) -> input dict for the task.
                For per-lib steps, branch will be "".
            output_root: base directory for all outputs
        """
        from kitdag.core.dag import DAGBuilder

        tasks: Dict[str, Task] = {}

        # 1. Create tasks for each (lib, step, branch) combination
        for lib in libs:
            for step_name in self._step_order:
                branches = get_branches(lib, step_name)
                if branches:
                    for branch in branches:
                        scope = {"lib": lib, "branch": branch}
                        task = self._make_task(
                            step_name, scope, get_inputs, output_root,
                        )
                        tasks[task.id] = task
                else:
                    # Per-lib step, no branch expansion
                    scope = {"lib": lib}
                    task = self._make_task(
                        step_name, scope, get_inputs, output_root,
                    )
                    tasks[task.id] = task

        # 2. Build dependency edges
        edges: Dict[str, Set[str]] = {tid: set() for tid in tasks}
        task_index = _build_task_index(tasks)

        for dep in self._deps:
            self._resolve_dep(dep, tasks, task_index, edges)

        # 3. Build DAG
        dag = DAGBuilder()
        dag.add_tasks(list(tasks.values()))
        dag.set_edges(edges)

        return Pipeline(
            name=self.name,
            flow=self,
            tasks=tasks,
            dag=dag,
            output_root=output_root,
        )

    def _make_task(
        self,
        step_name: str,
        scope: Dict[str, str],
        get_inputs: Callable,
        output_root: str,
    ) -> Task:
        lib = scope.get("lib", "")
        branch = scope.get("branch", "")

        # Build output path from scope
        parts = [output_root]
        if lib:
            parts.append(lib)
        if branch:
            parts.append(branch)
        parts.append(step_name)
        output_dir = "/".join(parts)
        log_path = f"{output_dir}/{step_name}.log"

        return Task(
            step_name=step_name,
            scope=dict(scope),
            output_dir=output_dir,
            log_path=log_path,
        )

    def _resolve_dep(
        self,
        dep: Dependency,
        tasks: Dict[str, Task],
        task_index: "_TaskIndex",
        edges: Dict[str, Set[str]],
    ) -> None:
        """Resolve a dependency declaration into concrete task edges."""
        # Find all downstream tasks for this dep
        downstream_tasks = task_index.by_step.get(dep.downstream, [])

        for ds_task in downstream_tasks:
            ds_lib = ds_task.scope.get("lib", "")
            ds_branch = ds_task.scope.get("branch", "")

            # Determine which upstream branches are needed
            if ds_branch and ds_branch in dep.branch_map:
                # Explicit branch_map: list of upstream branches needed
                needed_branches = dep.branch_map[ds_branch]
            elif ds_branch:
                # Default: same branch
                needed_branches = [ds_branch]
            else:
                # Downstream has no branch → fan-in: all upstream branches
                needed_branches = None  # means "all"

            # Find matching upstream tasks
            upstream_tasks = task_index.by_step.get(dep.upstream, [])
            for us_task in upstream_tasks:
                # Never create self-edges
                if us_task.id == ds_task.id:
                    continue

                us_lib = us_task.scope.get("lib", "")
                us_branch = us_task.scope.get("branch", "")

                # Must match on lib
                if us_lib != ds_lib:
                    continue

                # Branch matching
                if needed_branches is None:
                    # Fan-in: accept all branches of this lib
                    edges[ds_task.id].add(us_task.id)
                elif us_branch in needed_branches:
                    # Specific branch match
                    edges[ds_task.id].add(us_task.id)
                elif not us_branch and not ds_branch:
                    # Both per-lib, no branch → match
                    edges[ds_task.id].add(us_task.id)

    # ------------------------------------------------------------------
    # Mermaid visualization
    # ------------------------------------------------------------------

    def to_mermaid(
        self,
        lib: Optional[str] = None,
        get_branches: Optional[Callable[[str, str], List[str]]] = None,
    ) -> str:
        """Generate a Mermaid diagram of the dependency graph.

        Args:
            lib: if provided, show concrete DAG for this lib
            get_branches: required if lib is provided

        Returns:
            Mermaid graph string
        """
        if lib and get_branches:
            return self._mermaid_concrete(lib, get_branches)
        return self._mermaid_abstract()

    def _mermaid_abstract(self) -> str:
        """Abstract diagram showing all possible branch patterns."""
        # Collect all branches mentioned in deps and steps
        all_branches = set()
        for dep in self._deps:
            for branches in dep.branch_map.values():
                all_branches.update(branches)
            all_branches.update(dep.branch_map.keys())

        # If no branch_map defined, show step-level only
        if not all_branches:
            return self._mermaid_step_level()

        lines = ["graph LR"]

        # Create subgraphs for each step
        for step_name in self._step_order:
            safe = _safe_id(step_name)
            lines.append(f"    subgraph {step_name}")
            for branch in sorted(all_branches):
                lines.append(f'        {safe}_{branch}["{branch}"]')
            lines.append("    end")
            lines.append("")

        # Draw edges
        for dep in self._deps:
            ds_safe = _safe_id(dep.downstream)
            us_safe = _safe_id(dep.upstream)

            if dep.branch_map:
                # Draw explicit branch_map edges
                drawn = set()
                for ds_branch, us_branches in dep.branch_map.items():
                    for us_branch in us_branches:
                        src = f"{us_safe}_{us_branch}"
                        dst = f"{ds_safe}_{ds_branch}"
                        if src == dst:
                            continue  # no self-edges
                        edge = f"    {src} --> {dst}"
                        if edge not in drawn:
                            lines.append(edge)
                            drawn.add(edge)
                # Default same-branch for branches not in map
                for branch in sorted(all_branches):
                    if branch not in dep.branch_map:
                        src = f"{us_safe}_{branch}"
                        dst = f"{ds_safe}_{branch}"
                        if src == dst:
                            continue
                        edge = f"    {src} --> {dst}"
                        if edge not in drawn:
                            lines.append(edge)
                            drawn.add(edge)
            else:
                # Same-branch for all
                for branch in sorted(all_branches):
                    lines.append(
                        f"    {us_safe}_{branch} --> {ds_safe}_{branch}"
                    )
            lines.append("")

        return "\n".join(lines)

    def _mermaid_concrete(
        self, lib: str, get_branches: Callable[[str, str], List[str]]
    ) -> str:
        """Concrete diagram for a specific lib."""
        lines = [f"graph LR"]

        # Collect branches per step
        step_branches: Dict[str, List[str]] = {}
        for step_name in self._step_order:
            step_branches[step_name] = get_branches(lib, step_name)

        # Create subgraphs
        for step_name in self._step_order:
            safe = _safe_id(step_name)
            branches = step_branches[step_name]
            lines.append(f"    subgraph {step_name}")
            if branches:
                for branch in branches:
                    lines.append(f'        {safe}_{branch}["{branch}"]')
            else:
                lines.append(f'        {safe}_all["(per-lib)"]')
            lines.append("    end")
            lines.append("")

        # Draw edges
        for dep in self._deps:
            ds_safe = _safe_id(dep.downstream)
            us_safe = _safe_id(dep.upstream)
            ds_branches = step_branches.get(dep.downstream, [])
            us_branches_set = set(step_branches.get(dep.upstream, []))

            for ds_branch in (ds_branches or [""]):
                if ds_branch and ds_branch in dep.branch_map:
                    needed = dep.branch_map[ds_branch]
                elif ds_branch:
                    needed = [ds_branch]
                else:
                    needed = None  # fan-in

                if needed is None:
                    # Fan-in: all upstream branches → this downstream
                    ds_node = f"{ds_safe}_all"
                    for us_branch in step_branches.get(dep.upstream, []):
                        lines.append(
                            f"    {us_safe}_{us_branch} --> {ds_node}"
                        )
                    if not step_branches.get(dep.upstream):
                        lines.append(
                            f"    {us_safe}_all --> {ds_node}"
                        )
                else:
                    ds_node = f"{ds_safe}_{ds_branch}" if ds_branch else f"{ds_safe}_all"
                    for us_branch in needed:
                        if us_branch in us_branches_set:
                            us_node = f"{us_safe}_{us_branch}"
                            if us_node != ds_node:  # no self-edges
                                lines.append(
                                    f"    {us_node} --> {ds_node}"
                                )
                        elif not us_branches_set:
                            lines.append(
                                f"    {us_safe}_all --> {ds_node}"
                            )
            lines.append("")

        return "\n".join(lines)

    def _mermaid_step_level(self) -> str:
        """Simple step-level diagram when no branch patterns defined."""
        lines = ["graph LR"]
        for dep in self._deps:
            lines.append(f"    {dep.upstream} --> {dep.downstream}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Pipeline — result of flow.build()
# ------------------------------------------------------------------

class Pipeline:
    """A concrete pipeline: expanded tasks + DAG, ready for execution."""

    def __init__(
        self,
        name: str,
        flow: Flow,
        tasks: Dict[str, Task],
        dag: "DAGBuilder",
        output_root: str,
    ):
        self.name = name
        self.flow = flow
        self.tasks = tasks
        self.dag = dag
        self.output_root = output_root

    @property
    def libs(self) -> List[str]:
        """Unique libs in this pipeline."""
        seen = []
        seen_set = set()
        for t in self.tasks.values():
            lib = t.scope.get("lib", "")
            if lib and lib not in seen_set:
                seen.append(lib)
                seen_set.add(lib)
        return seen

    def tasks_for_lib(self, lib: str) -> Dict[str, Task]:
        """Return all tasks for a given lib."""
        return {
            tid: t for tid, t in self.tasks.items()
            if t.scope.get("lib") == lib
        }

    def get_task(self, step_name: str, lib: str, branch: str = "") -> Optional[Task]:
        """Look up a specific task by step/lib/branch."""
        scope = {"lib": lib}
        if branch:
            scope["branch"] = branch
        task = Task(step_name=step_name, scope=scope)
        return self.tasks.get(task.id)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

@dataclass
class _TaskIndex:
    """Index for fast task lookup during dependency resolution."""

    by_step: Dict[str, List[Task]] = field(default_factory=dict)
    by_lib_step: Dict[Tuple[str, str], List[Task]] = field(default_factory=dict)


def _build_task_index(tasks: Dict[str, Task]) -> _TaskIndex:
    idx = _TaskIndex()
    for task in tasks.values():
        idx.by_step.setdefault(task.step_name, []).append(task)
        lib = task.scope.get("lib", "")
        idx.by_lib_step.setdefault((lib, task.step_name), []).append(task)
    return idx


def _safe_id(name: str) -> str:
    """Convert a step name to a safe mermaid node ID."""
    return name.replace("-", "_").replace(".", "_").replace(" ", "_")
