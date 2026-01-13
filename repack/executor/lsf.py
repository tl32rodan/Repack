from abc import abstractmethod
from typing import List, Callable, Dict
import subprocess
import os
import time

from .base import Executor, Job

class LSFExecutor(Executor):
    """
    Abstract executor for LSF (Load Sharing Facility).
    Subclasses should implement site-specific flag generation.
    """
    def __init__(self):
        self.target_to_lsf: Dict[str, str] = {} # target_id -> lsf_id
        self.callbacks: Dict[str, Callable[[str, bool], None]] = {} # target_id -> callback

    def submit(self, job: Job, dependency_job_ids: List[str] = None, on_complete: Callable[[str, bool], None] = None) -> str:
        bsub_cmd = ["bsub"]

        # Log path
        os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
        bsub_cmd.extend(["-o", job.log_path])
        bsub_cmd.extend(["-e", job.log_path]) # Merge stderr

        # Job Name
        bsub_cmd.extend(["-J", job.id])

        # Dependencies
        if dependency_job_ids:
            # Resolve target IDs to LSF IDs
            lsf_deps = []
            for dep_tid in dependency_job_ids:
                lsf_id = self.target_to_lsf.get(dep_tid)
                if lsf_id:
                    lsf_deps.append(lsf_id)
                else:
                    # If dep not found, maybe it finished already or wasn't tracked.
                    # For safety, we might want to warn.
                    pass

            if lsf_deps:
                conditions = [f"done({jid})" for jid in lsf_deps]
                bsub_cmd.extend(["-w", " && ".join(conditions)])

        # Site specific flags
        bsub_cmd.extend(self.get_bsub_flags(job))

        # Command
        cmd_str = " ".join(job.command)
        bsub_cmd.append(cmd_str)

        # Execute bsub
        lsf_job_id = self._execute_bsub(bsub_cmd)
        self.target_to_lsf[job.id] = lsf_job_id

        if on_complete:
            self.callbacks[job.id] = on_complete

        return job.id

    def wait(self, job_ids: List[str]) -> None:
        """
        Polls LSF for status of jobs.
        """
        pending_jobs = set(job_ids)

        while pending_jobs:
            # Check status of all pending jobs
            # Inefficient to check one by one, usually bjobs -u user
            # But here we abstract.

            done = set()
            for tid in pending_jobs:
                lsf_id = self.target_to_lsf.get(tid)
                if not lsf_id:
                    # If we don't know the LSF ID, assume done or error?
                    done.add(tid)
                    continue

                status = self._get_lsf_status(lsf_id)
                if status == "DONE":
                    if tid in self.callbacks:
                        self.callbacks[tid](tid, True)
                    done.add(tid)
                elif status == "EXIT":
                    if tid in self.callbacks:
                        self.callbacks[tid](tid, False)
                    done.add(tid)
                # Else PEND or RUN

            pending_jobs -= done

            if pending_jobs:
                time.sleep(5) # Poll interval

    @abstractmethod
    def get_bsub_flags(self, job: Job) -> List[str]:
        """
        Return list of site-specific bsub flags.
        e.g. ["-q", "normal", "-R", "rusage[mem=1000]"]
        """
        pass

    def _execute_bsub(self, cmd: List[str]) -> str:
        """
        Executes bsub command and parses output to return LSF Job ID.
        """
        try:
            output = subprocess.check_output(cmd, encoding='utf-8')
            import re
            match = re.search(r"Job <(\d+)>", output)
            if match:
                return match.group(1)
            raise Exception(f"Could not parse LSF Job ID from: {output}")
        except subprocess.CalledProcessError as e:
            raise Exception(f"bsub failed: {e}")

    def _get_lsf_status(self, lsf_id: str) -> str:
        """
        Returns LSF status: DONE, EXIT, RUN, PEND, or UNKNOWN.
        """
        # Default implementation using bjobs
        try:
            # bjobs -noheader -o "stat" <job_id>
            cmd = ["bjobs", "-noheader", "-o", "stat", lsf_id]
            output = subprocess.check_output(cmd, encoding='utf-8').strip()
            return output
        except subprocess.CalledProcessError:
            return "UNKNOWN"
