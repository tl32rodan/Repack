from enum import Enum
from typing import Dict, List, Optional
import csv
import os
from .kit import KitTarget

class TargetStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"

class StateManager:
    """
    Manages the persistent state of the repack run (Full vs Incremental).
    """
    def __init__(self, status_file_path: str):
        self.status_file_path = status_file_path
        self.state: Dict[str, TargetStatus] = {}

    def initialize(self, all_targets: List[KitTarget], clean_callback=None) -> bool:
        """
        Initializes the state.
        
        Args:
            all_targets: List of all targets involved in this run.
            clean_callback: Function to call if a FULL cleanup is needed.
        
        Returns:
            True if incremental run, False if full run (clean triggered).
        """
        is_incremental = False
        loaded_state = {}

        # 1. Check if status file exists
        if os.path.exists(self.status_file_path):
            try:
                with open(self.status_file_path, 'r', newline='') as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    if header == ["id", "status"]:
                        for row in reader:
                            if len(row) >= 2:
                                tid, status_str = row[0], row[1]
                                # Convert string back to Enum, default to PENDING if invalid
                                try:
                                    status = TargetStatus(status_str)
                                except ValueError:
                                    status = TargetStatus.PENDING
                                loaded_state[tid] = status
                        is_incremental = True
            except Exception:
                # If file is corrupt, treat as full run
                is_incremental = False

        # 2. Logic branching
        if is_incremental:
            # Incremental: Use loaded state
            self.state = loaded_state
        else:
            # Full Run: Clean up and start fresh
            if clean_callback:
                clean_callback()
            self.state = {}

        # 3. Reconcile with current targets (add missing as PENDING)
        for target in all_targets:
            if target.id not in self.state:
                self.state[target.id] = TargetStatus.PENDING

        # 4. Flush immediately to save the verified state
        self._flush()
        
        return is_incremental

    def get_status(self, target_id: str) -> TargetStatus:
        return self.state.get(target_id, TargetStatus.PENDING)

    def set_status(self, target_id: str, status: TargetStatus):
        self.state[target_id] = status
        self._flush()

    def _flush(self):
        """Writes state to CSV."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.status_file_path), exist_ok=True)
        
        with open(self.status_file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["id", "status"])
            for tid, status in self.state.items():
                writer.writerow([tid, status.value])
