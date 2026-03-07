"""DAG builder and topological sort for kit targets."""

from collections import defaultdict, deque
from typing import Dict, List, Set

from kitdag.core.target import KitTarget


class CyclicDependencyError(Exception):
    """Raised when a cycle is detected in the dependency graph."""


class DAGBuilder:
    """Builds a kit-level DAG from step dependencies.

    Each node is one KitTarget (one per kit/step). Edges represent
    kit-level dependencies declared in the pipeline steps section.
    """

    def __init__(self) -> None:
        # adjacency: target_id -> set of target_ids it depends on
        self._deps: Dict[str, Set[str]] = defaultdict(set)
        # reverse adjacency: target_id -> set of target_ids depending on it
        self._rdeps: Dict[str, Set[str]] = defaultdict(set)
        self._all_targets: Dict[str, KitTarget] = {}

    def add_targets(self, targets: List[KitTarget]) -> None:
        """Register targets in the graph."""
        for t in targets:
            self._all_targets[t.id] = t
            if t.id not in self._deps:
                self._deps[t.id] = set()

    def build_edges(self, kit_dependencies: Dict[str, List[str]]) -> None:
        """Build edges from kit-level dependencies.

        Args:
            kit_dependencies: {kit_name: [dependency_kit_names]}
        """
        for kit_name, dep_kit_names in kit_dependencies.items():
            if kit_name not in self._all_targets:
                continue
            for dep_kit_name in dep_kit_names:
                if dep_kit_name not in self._all_targets:
                    continue
                self._deps[kit_name].add(dep_kit_name)
                self._rdeps[dep_kit_name].add(kit_name)

    def topological_sort(self) -> List[str]:
        """Return target IDs in dependency-respecting execution order.

        Uses Kahn's algorithm. Raises CyclicDependencyError if a cycle exists.
        """
        in_degree: Dict[str, int] = {}
        for tid in self._all_targets:
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

        if len(result) != len(self._all_targets):
            missing = set(self._all_targets) - set(result)
            raise CyclicDependencyError(
                f"Cycle detected involving targets: {missing}"
            )

        return result

    def get_dependencies(self, target_id: str) -> Set[str]:
        """Get direct dependencies of a target."""
        return self._deps.get(target_id, set())

    def get_dependents(self, target_id: str) -> Set[str]:
        """Get direct dependents of a target."""
        return self._rdeps.get(target_id, set())

    def get_all_targets(self) -> Dict[str, KitTarget]:
        """Return all registered targets."""
        return dict(self._all_targets)

    def get_execution_stages(self) -> List[List[str]]:
        """Return targets grouped by execution stage (parallelizable).

        Each stage contains targets that can run in parallel.
        Stage N+1 targets depend only on stage <= N targets.
        """
        in_degree: Dict[str, int] = {}
        for tid in self._all_targets:
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
