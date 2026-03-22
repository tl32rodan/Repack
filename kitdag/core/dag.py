"""DAG builder and topological sort for scope-based tasks."""

from collections import defaultdict, deque
from typing import Dict, List, Set

from kitdag.core.task import Task


class CyclicDependencyError(Exception):
    """Raised when a cycle is detected in the dependency graph."""


class DAGBuilder:
    """Builds and manages the task-level DAG.

    Nodes are Tasks (identified by task.id).
    Edges are concrete dependencies resolved from flow Dependency declarations.
    """

    def __init__(self) -> None:
        self._deps: Dict[str, Set[str]] = defaultdict(set)
        self._rdeps: Dict[str, Set[str]] = defaultdict(set)
        self._all_tasks: Dict[str, Task] = {}

    def add_tasks(self, tasks: List[Task]) -> None:
        """Register tasks as nodes in the graph."""
        for t in tasks:
            self._all_tasks[t.id] = t
            if t.id not in self._deps:
                self._deps[t.id] = set()

    def set_edges(self, edges: Dict[str, Set[str]]) -> None:
        """Set dependency edges (task_id -> set of dependency task_ids)."""
        for tid, dep_ids in edges.items():
            if tid not in self._all_tasks:
                continue
            for dep_id in dep_ids:
                if dep_id not in self._all_tasks:
                    continue
                self._deps[tid].add(dep_id)
                self._rdeps[dep_id].add(tid)

    def topological_sort(self) -> List[str]:
        """Return task IDs in dependency-respecting execution order.

        Uses Kahn's algorithm. Raises CyclicDependencyError if cycle detected.
        """
        in_degree: Dict[str, int] = {}
        for tid in self._all_tasks:
            in_degree[tid] = len(self._deps.get(tid, set()))

        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        result: List[str] = []

        while queue:
            tid = queue.popleft()
            result.append(tid)
            for dependent in self._rdeps.get(tid, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._all_tasks):
            missing = set(self._all_tasks) - set(result)
            raise CyclicDependencyError(
                f"Cycle detected involving tasks: {missing}"
            )

        return result

    def get_dependencies(self, task_id: str) -> Set[str]:
        """Get direct dependencies of a task."""
        return self._deps.get(task_id, set())

    def get_dependents(self, task_id: str) -> Set[str]:
        """Get direct dependents of a task."""
        return self._rdeps.get(task_id, set())

    def get_all_tasks(self) -> Dict[str, Task]:
        """Return all registered tasks."""
        return dict(self._all_tasks)

    def get_execution_stages(self) -> List[List[str]]:
        """Return tasks grouped by execution stage (parallelizable).

        Each stage contains tasks that can run in parallel.
        Stage N+1 tasks depend only on stage <= N tasks.
        """
        in_degree: Dict[str, int] = {}
        for tid in self._all_tasks:
            in_degree[tid] = len(self._deps.get(tid, set()))

        current = [tid for tid, deg in in_degree.items() if deg == 0]
        stages: List[List[str]] = []

        while current:
            stages.append(sorted(current))
            next_stage: List[str] = []
            for tid in current:
                for dependent in self._rdeps.get(tid, set()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_stage.append(dependent)
            current = next_stage

        return stages
