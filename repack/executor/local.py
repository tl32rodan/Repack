"""LocalExecutor - ThreadPool-based local job execution."""

import logging
import os
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, Optional, Set

from repack.executor.base import Executor, Job

logger = logging.getLogger(__name__)


class LocalExecutor(Executor):
    """Execute jobs locally using a thread pool.

    Dependencies are tracked: a job waits until all its dependencies
    have completed successfully before starting.
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers
        self._pool: Optional[ThreadPoolExecutor] = None
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._results: Dict[str, bool] = {}
        self._done: Set[str] = set()
        self._failed: Set[str] = set()

    def submit(self, job: Job) -> None:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self._max_workers)

        self._jobs[job.id] = job
        future = self._pool.submit(self._run_job, job)
        self._futures[job.id] = future

    def _run_job(self, job: Job) -> bool:
        # Wait for dependencies
        while True:
            unmet = job.dependencies - self._done
            if not unmet:
                break
            # Check if any dependency failed
            if unmet & self._failed:
                logger.warning(
                    "Job %s skipped: dependency failed (%s)",
                    job.id, unmet & self._failed,
                )
                self._failed.add(job.id)
                self._done.add(job.id)
                self._results[job.id] = False
                self._notify(job.id, False)
                return False
            time.sleep(0.1)

        # Execute
        os.makedirs(os.path.dirname(job.log_path) if job.log_path else ".", exist_ok=True)
        log_file = open(job.log_path, "w") if job.log_path else None

        try:
            if log_file:
                log_file.write(f"# Job: {job.id}\n")
                log_file.write(f"# Command: {' '.join(job.command)}\n")
                log_file.write(f"# CWD: {job.cwd}\n")
                log_file.write(f"# Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_file.write("# " + "=" * 60 + "\n")
                log_file.flush()

            env = dict(os.environ)
            env.update(job.environment)

            result = subprocess.run(
                job.command,
                cwd=job.cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )

            success = result.returncode == 0
            if log_file:
                log_file.write(f"\n# Exit code: {result.returncode}\n")

        except Exception as e:
            success = False
            if log_file:
                log_file.write(f"\n# EXCEPTION: {e}\n")
            logger.exception("Job %s failed with exception", job.id)
        finally:
            if log_file:
                log_file.close()

        if success:
            self._done.add(job.id)
        else:
            self._failed.add(job.id)
            self._done.add(job.id)

        self._results[job.id] = success
        self._notify(job.id, success)
        return success

    def wait_all(self) -> Dict[str, bool]:
        for future in self._futures.values():
            future.result()

        if self._pool:
            self._pool.shutdown(wait=True)
            self._pool = None

        return dict(self._results)

    def cancel_all(self) -> None:
        for future in self._futures.values():
            future.cancel()
        if self._pool:
            self._pool.shutdown(wait=False)
            self._pool = None
