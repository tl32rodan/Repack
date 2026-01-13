import unittest
import os
import tempfile
import shutil
from repack.core.state import StateManager, TargetStatus
from repack.core.kit import KitTarget

class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.status_file = os.path.join(self.test_dir, "repack_status.csv")
        self.targets = [
            KitTarget(kit_name="libA", pvt="ss_100c"),
            KitTarget(kit_name="libA", pvt="ff_0c"),
            KitTarget(kit_name="libB", pvt="ALL")
        ]
        self.cleaned = False

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def mock_clean_callback(self):
        self.cleaned = True

    def test_full_run_init(self):
        """
        If status file is missing:
        1. Should trigger clean_callback.
        2. Should initialize all targets to PENDING.
        3. Should return False (indicating NOT incremental).
        """
        manager = StateManager(self.status_file)
        is_incremental = manager.initialize(self.targets, clean_callback=self.mock_clean_callback)
        
        self.assertFalse(is_incremental)
        self.assertTrue(self.cleaned, "Clean callback should be called on full run")
        
        # Check in-memory state
        self.assertEqual(manager.get_status(self.targets[0].id), TargetStatus.PENDING)
        
        # Check persisted file
        self.assertTrue(os.path.exists(self.status_file))
        with open(self.status_file, 'r') as f:
            content = f.read()
            self.assertIn("libA::ss_100c,PENDING", content)

    def test_incremental_run_load(self):
        """
        If status file exists:
        1. Should NOT trigger clean_callback.
        2. Should load existing statuses.
        3. Should add new targets as PENDING.
        4. Should return True.
        """
        # Setup existing file
        with open(self.status_file, 'w', newline='') as f:
            f.write("id,status\n")
            f.write(f"{self.targets[0].id},PASS\n") # libA::ss_100c is PASS
            # libA::ff_0c is missing (simulating new target)
            
        manager = StateManager(self.status_file)
        is_incremental = manager.initialize(self.targets, clean_callback=self.mock_clean_callback)
        
        self.assertTrue(is_incremental)
        self.assertFalse(self.cleaned, "Clean callback should NOT be called on incremental")
        
        self.assertEqual(manager.get_status(self.targets[0].id), TargetStatus.PASS)
        self.assertEqual(manager.get_status(self.targets[1].id), TargetStatus.PENDING, "New target should be PENDING")

    def test_manual_rerun_trigger(self):
        """
        User modifies CSV: PASS -> PENDING.
        Manager should load it as PENDING.
        """
        # Setup existing file with USER MODIFICATION
        with open(self.status_file, 'w', newline='') as f:
            f.write("id,status\n")
            f.write(f"{self.targets[0].id},PENDING\n")
            
        manager = StateManager(self.status_file)
        manager.initialize(self.targets)
        
        self.assertEqual(manager.get_status(self.targets[0].id), TargetStatus.PENDING)

    def test_status_update_persists(self):
        """
        Updating status should save to file immediately.
        """
        manager = StateManager(self.status_file)
        manager.initialize(self.targets, clean_callback=self.mock_clean_callback)
        
        manager.set_status(self.targets[0].id, TargetStatus.RUNNING)
        
        # Read back from file independent of manager
        with open(self.status_file, 'r') as f:
            content = f.read()
            self.assertIn(f"{self.targets[0].id},RUNNING", content)

if __name__ == '__main__':
    unittest.main()
