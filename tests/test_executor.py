import unittest
import os
import tempfile
import time
from concurrent.futures import Future
from repack.executor.local import LocalExecutor
from repack.executor.base import Job

class TestLocalExecutor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.executor = LocalExecutor(max_workers=2)

    def tearDown(self):
        self.executor.shutdown()
        import shutil
        shutil.rmtree(self.test_dir)

    def test_submit_and_wait(self):
        log_file = os.path.join(self.test_dir, "test.log")
        job = Job(
            id="job1",
            command=["echo", "hello world"],
            cwd=self.test_dir,
            log_path=log_file
        )

        callback_called = False
        def on_complete(jid, success):
            nonlocal callback_called
            callback_called = True
            self.assertEqual(jid, "job1")
            self.assertTrue(success)

        job_id = self.executor.submit(job, on_complete=on_complete)
        self.assertEqual(job_id, "job1")

        self.executor.wait([job_id])

        # Verify log file content
        self.assertTrue(os.path.exists(log_file))
        with open(log_file, 'r') as f:
            content = f.read().strip()
            self.assertIn("hello world", content)

        self.assertTrue(callback_called)

    def test_dependency_wait(self):
        log_a = os.path.join(self.test_dir, "a.log")
        log_b = os.path.join(self.test_dir, "b.log")

        job_a = Job(
            id="jobA",
            command=["sleep", "1"],
            cwd=self.test_dir,
            log_path=log_a
        )

        job_b = Job(
            id="jobB",
            command=["touch", log_b],
            cwd=self.test_dir,
            log_path=log_b
        )

        start_time = time.time()
        self.executor.submit(job_a)
        self.executor.submit(job_b, dependency_job_ids=["jobA"])

        self.executor.wait(["jobB"])
        end_time = time.time()

        # Should take at least 1 second
        self.assertGreaterEqual(end_time - start_time, 1.0)
        self.assertTrue(os.path.exists(log_b))

    def test_failure_propagation(self):
        """
        If A fails, B should fail immediately (or not run).
        """
        log_a = os.path.join(self.test_dir, "fail.log")
        log_b = os.path.join(self.test_dir, "no_run.log")

        job_a = Job(
            id="jobA",
            command=["false"], # Fails
            cwd=self.test_dir,
            log_path=log_a
        )

        job_b = Job(
            id="jobB",
            command=["touch", log_b],
            cwd=self.test_dir,
            log_path=log_b
        )

        b_success = None
        def on_b_complete(jid, success):
            nonlocal b_success
            b_success = success

        self.executor.submit(job_a)
        self.executor.submit(job_b, dependency_job_ids=["jobA"], on_complete=on_b_complete)

        # Wait for B (which should finish quickly with failure)
        # However, we need to wait for A to fail first.
        self.executor.wait(["jobA", "jobB"])

        # B should have failed
        self.assertFalse(b_success)
        # B should NOT have run (log file should not exist)
        self.assertFalse(os.path.exists(log_b))

if __name__ == '__main__':
    unittest.main()
