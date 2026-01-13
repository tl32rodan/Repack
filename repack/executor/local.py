import subprocess
import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future, wait
from typing import List, Dict, Set, Callable

from .base import Executor, Job

class LocalExecutor(Executor):
    def __init__(self, max_workers: int = 1):
        self.pool = ThreadPoolExecutor(max_workers=max_workers)
        self.futures: Dict[str, Future] = {}
        self.lock = threading.Lock()
        # Track pending dependencies for jobs that haven't started
        self.pending_dependencies: Dict[str, Set[str]] = {}
        self.jobs: Dict[str, Job] = {}
        self.callbacks: Dict[str, Callable[[str, bool], None]] = {}

    def submit(self, job: Job, dependency_job_ids: List[str] = None, on_complete: Callable[[str, bool], None] = None) -> str:
        self.jobs[job.id] = job
        if on_complete:
            self.callbacks[job.id] = on_complete

        job_future = Future()

        with self.lock:
            self.futures[job.id] = job_future

            # Check dependencies
            pending = set()
            dependency_failed = False

            if dependency_job_ids:
                for dep_id in dependency_job_ids:
                    dep_future = self.futures.get(dep_id)
                    if not dep_future:
                        # Dependency not found/not submitted.
                        # In this framework, engine submits in topological order, so deps should exist.
                        # Unless filtered out? The engine logic ensures only submitted deps are passed.
                        continue

                    if dep_future.done():
                        # Check if it failed
                        try:
                            dep_future.result()
                        except:
                            dependency_failed = True
                            break
                    else:
                        pending.add(dep_id)

            if dependency_failed:
                # Fail immediately
                job_future.set_exception(Exception(f"Dependency failed"))
                if on_complete:
                    # Notify failure
                    # We need to run this likely in a separate thread or immediately?
                    # Safer to submit to pool to avoid blocking caller
                    self.pool.submit(on_complete, job.id, False)
                return job.id

            if not pending:
                # No running dependencies, submit immediately
                self.pool.submit(self._run_job, job, job_future)
            else:
                self.pending_dependencies[job.id] = pending
                # Add callbacks
                for dep_id in pending:
                    self.futures[dep_id].add_done_callback(lambda f, jid=job.id, did=dep_id: self._on_dependency_complete(jid, did))

        return job.id

    def _on_dependency_complete(self, job_id: str, dep_id: str):
        # Check if dependency failed
        dep_future = self.futures.get(dep_id)
        dep_failed = False
        try:
            if dep_future:
                dep_future.result()
        except:
            dep_failed = True

        with self.lock:
            # Check if job is already done (e.g. failed by another dependency)
            if self.futures[job_id].done():
                return

            if dep_failed:
                # Fail this job
                self.futures[job_id].set_exception(Exception(f"Dependency {dep_id} failed"))
                # Cleanup pending
                if job_id in self.pending_dependencies:
                    del self.pending_dependencies[job_id]

                # Notify callback
                cb = self.callbacks.get(job_id)
                if cb:
                    self.pool.submit(cb, job_id, False)
                return

            if job_id not in self.pending_dependencies:
                return

            deps = self.pending_dependencies[job_id]
            if dep_id in deps:
                deps.remove(dep_id)

            if not deps:
                # All dependencies done and successful
                del self.pending_dependencies[job_id]
                job = self.jobs[job_id]
                job_future = self.futures[job_id]
                self.pool.submit(self._run_job, job, job_future)

    def _run_job(self, job: Job, future: Future):
        success = False
        try:
            # Ensure output dir exists
            os.makedirs(os.path.dirname(job.log_path), exist_ok=True)

            with open(job.log_path, 'w') as log_file:
                # Write header
                log_file.write(f"Executing: {' '.join(job.command)}\n")
                log_file.write(f"CWD: {job.cwd}\n")
                log_file.flush()

                process = subprocess.Popen(
                    job.command,
                    cwd=job.cwd,
                    env={**os.environ, **job.environment},
                    stdout=log_file,
                    stderr=subprocess.STDOUT
                )
                rc = process.wait()

                if rc == 0:
                    success = True
                    future.set_result(True)
                else:
                    success = False
                    future.set_exception(Exception(f"Job {job.id} failed with exit code {rc}"))

        except Exception as e:
            success = False
            future.set_exception(e)
        finally:
            cb = self.callbacks.get(job.id)
            if cb:
                cb(job.id, success)

    def wait(self, job_ids: List[str]) -> None:
        fs = []
        with self.lock:
            for jid in job_ids:
                if jid in self.futures:
                    fs.append(self.futures[jid])

        wait(fs)

    def shutdown(self):
        self.pool.shutdown(wait=True)
