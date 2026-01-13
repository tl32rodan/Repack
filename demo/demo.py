import os
import sys
import shutil
from typing import List

from repack.core.kit import Kit, KitTarget
from repack.core.request import RepackRequest
from repack.core.state import StateManager
from repack.executor.local import LocalExecutor
from repack.engine.manager import RepackEngine

class DemoKit(Kit):
    def __init__(self, name: str, dependencies: List[str] = None):
        super().__init__(name)
        self._dependencies = dependencies or []

    def get_output_path(self, request: RepackRequest) -> str:
        return os.path.join(request.output_root, self.name)

    def get_targets(self, request: RepackRequest) -> List[KitTarget]:
        # Simple expansion: one target per PVT
        return [KitTarget(self.name, pvt=pvt) for pvt in request.pvts]

    def get_dependencies(self) -> List[str]:
        return self._dependencies

    def construct_command(self, target: KitTarget, request: RepackRequest) -> List[str]:
        # Command: echo "Running {target.id}" && sleep 1
        return ["sh", "-c", f"echo 'Running {target.id}' && sleep 0.5"]

def main():
    print("Initializing Repack Demo...")

    # 1. Setup Request
    output_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "output"))
    status_file = os.path.join(os.path.dirname(__file__), "repack_status.csv")

    request = RepackRequest(
        library_name="demo_lib",
        pvts=["ss_100c", "ff_0c"],
        corners=["tt"],
        cells=["inv", "nand"],
        output_root=output_root
    )

    # 2. Define Kits
    # A -> B (B depends on A)
    kit_a = DemoKit("KitA")
    kit_b = DemoKit("KitB", dependencies=["KitA"])
    kits = [kit_a, kit_b]

    # 3. Setup Executor
    # Using LocalExecutor with 2 workers
    executor = LocalExecutor(max_workers=2)

    # 4. Setup StateManager
    state_manager = StateManager(status_file)

    def clean_callback():
        print("Cleaning previous run artifacts...")
        if os.path.exists(output_root):
            shutil.rmtree(output_root)
        os.makedirs(output_root, exist_ok=True)
        # Re-create output dirs for kits
        for k in kits:
            os.makedirs(k.get_output_path(request), exist_ok=True)

    # 5. Run Engine
    engine = RepackEngine(kits, state_manager, executor)

    # We need to manually handle the clean callback if using engine directly,
    # or rely on engine to call initialize?
    # The engine calls state_manager.initialize(all_targets).
    # But state_manager.initialize takes a clean_callback argument.
    # However, RepackEngine.run() calls self.state_manager.initialize(all_targets) WITHOUT callback.
    # Wait, looking at RepackEngine implementation...
    # It calls: `self.state_manager.initialize(all_targets)`

    # I should probably update RepackEngine to accept a clean_callback or handle it.
    # OR, for this demo, I can just initialize state manager manually before passing to engine?
    # No, Engine calls initialize.

    # Let's check `repack/core/state.py` signature again.
    # initialize(self, all_targets: List[KitTarget], clean_callback=None) -> bool

    # And `repack/engine/manager.py`:
    # self.state_manager.initialize(all_targets) (Line 30)

    # So the clean_callback is NOT passed. This is a small design flaw in my Engine implementation vs State definition.
    # However, for the demo, I can subclass Engine or just pre-clean if I know it's a full run.
    # Or I can update Engine to accept clean_callback.

    # For now, let's implement clean explicitly before running, if status file is missing.
    if not os.path.exists(status_file):
        clean_callback()

    print("Starting Execution...")
    try:
        engine.run(request)
        print("Execution Complete.")
    finally:
        executor.shutdown()

    # verify output
    print("\nVerifying Output:")
    for kit in kits:
        for pvt in request.pvts:
            log_path = os.path.join(kit.get_output_path(request), f"{kit.name}::{pvt}.log")
            if os.path.exists(log_path):
                print(f"[PASS] {log_path} exists.")
            else:
                print(f"[FAIL] {log_path} MISSING.")

if __name__ == "__main__":
    main()
