from typing import List, Dict, Set
from collections import defaultdict, deque

from repack.core.kit import Kit, KitTarget
from repack.core.request import RepackRequest
from repack.core.state import StateManager, TargetStatus
from repack.executor.base import Executor, Job

class RepackEngine:
    def __init__(self, kits: List[Kit], state_manager: StateManager, executor: Executor):
        self.kits = {k.name: k for k in kits}
        self.state_manager = state_manager
        self.executor = executor

    def run(self, request: RepackRequest):
        # 1. Collect all targets
        all_targets: List[KitTarget] = []
        kit_targets_map: Dict[str, List[KitTarget]] = {}
        target_map: Dict[str, KitTarget] = {}

        for kit in self.kits.values():
            targets = kit.get_targets(request)
            kit_targets_map[kit.name] = targets
            all_targets.extend(targets)
            for t in targets:
                target_map[t.id] = t

        # 2. Init State
        self.state_manager.initialize(all_targets)

        # 3. Build Dependency Graph (Target Level)
        # graph_out: node -> list of nodes that depend on it (outputs)
        # graph_in: node -> list of nodes that it depends on (inputs)
        graph_out = defaultdict(list)
        graph_in = defaultdict(list)

        for target in all_targets:
            kit = self.kits[target.kit_name]
            deps = kit.get_dependencies()
            for dep_kit_name in deps:
                dep_targets = kit_targets_map.get(dep_kit_name, [])
                for dt in dep_targets:
                    # Match logic: Same PVT or dependency is ALL
                    if dt.pvt == target.pvt or dt.pvt == "ALL" or target.pvt == "ALL":
                        graph_out[dt.id].append(target.id)
                        graph_in[target.id].append(dt.id)

        # 4. Topological Sort
        in_degree = {t.id: 0 for t in all_targets}
        for u, dependencies in graph_in.items():
            in_degree[u] = len(dependencies)

        queue = deque([t.id for t in all_targets if in_degree[t.id] == 0])
        sorted_targets = []

        while queue:
            u = queue.popleft()
            sorted_targets.append(u)

            for v in graph_out[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(sorted_targets) != len(all_targets):
            raise Exception("Cycle detected in kit dependencies")

        # 5. Dispatch
        submitted_jobs: Set[str] = set()

        for tid in sorted_targets:
            status = self.state_manager.get_status(tid)
            if status == TargetStatus.PASS:
                continue

            # Prepare job
            target = target_map[tid]
            kit = self.kits[target.kit_name]

            # Resolve dependencies that are actually running
            run_deps = []
            for dep_tid in graph_in[tid]:
                if dep_tid in submitted_jobs:
                    run_deps.append(dep_tid)

            command = kit.construct_command(target, request)
            log_path = f"{kit.get_output_path(request)}/{tid}.log"
            job = Job(
                id=tid,
                command=command,
                cwd=kit.get_output_path(request),
                log_path=log_path
            )

            self.executor.submit(job, run_deps, on_complete=self._make_on_complete(tid))
            submitted_jobs.add(tid)

            self.state_manager.set_status(tid, TargetStatus.RUNNING)

        # 6. Wait for all submitted jobs
        self.executor.wait(list(submitted_jobs))

    def _make_on_complete(self, target_id: str):
        """Helper to create a callback with bound target_id."""
        def callback(job_id: str, success: bool):
            status = TargetStatus.PASS if success else TargetStatus.FAIL
            self.state_manager.set_status(target_id, status)
        return callback
