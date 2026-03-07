"""DAG builder and topological sort for kit targets."""

from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

from kitdag.core.target import KitTarget


class CyclicDependencyError(Exception):
    """Raised when a cycle is detected in the dependency graph."""


class DAGBuilder:
    """Builds a target-level DAG from kit-level dependencies.

    Kit-level dependencies are expanded to target-level using PVT matching:
    - If both kits are corner-based, targets with the same PVT are linked
    - If upstream is non-corner-based (ALL), downstream PVT targets depend on it
    - If downstream is non-corner-based (ALL), it depends on all upstream PVT targets
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
        """Build target-level edges from kit-level dependencies.

        Args:
            kit_dependencies: {kit_name: [dependency_kit_names]}
        """
        # Group targets by kit name
        by_kit: Dict[str, List[KitTarget]] = defaultdict(list)
        for t in self._all_targets.values():
            by_kit[t.kit_name].append(t)

        for kit_name, dep_kit_names in kit_dependencies.items():
            if kit_name not in by_kit:
                continue
            for dep_kit_name in dep_kit_names:
                if dep_kit_name not in by_kit:
                    continue
                for target in by_kit[kit_name]:
                    for dep_target in by_kit[dep_kit_name]:
                        if self._pvt_matches(target, dep_target):
                            self._deps[target.id].add(dep_target.id)
                            self._rdeps[dep_target.id].add(target.id)

    @staticmethod
    def _pvt_matches(downstream: KitTarget, upstream: KitTarget) -> bool:
        """Check if PVT corners match for dependency linking."""
        if upstream.pvt == "ALL" or downstream.pvt == "ALL":
            return True
        return upstream.pvt == downstream.pvt

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
