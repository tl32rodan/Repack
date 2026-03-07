"""LSFExecutor - IBM LSF cluster job submission."""

import logging
import os
import re
import subprocess
import time
from abc import abstractmethod
from typing import Dict, List, Optional, Set

from repack.executor.base import Executor, Job

logger = logging.getLogger(__name__)


class LSFExecutor(Executor):
    """Execute jobs via LSF bsub/bjobs.

    Subclass and implement get_bsub_flags() for site-specific configuration
    (queue name, resource requirements, etc.).
    """

    POLL_INTERVAL = 10  # seconds

    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._lsf_ids: Dict[str, str] = {}  # job_id -> LSF job ID
        self._results: Dict[str, bool] = {}
        self._dep_map: Dict[str, Set[str]] = {}  # job_id -> dependency job_ids

    @abstractmethod
    def get_bsub_flags(self, job: Job) -> List[str]:
        """Return site-specific bsub flags.

        Example return: ["-q", "normal", "-R", "rusage[mem=4000]"]
        """

    def submit(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._dep_map[job.id] = set(job.dependencies)

        # Build bsub command
        cmd = ["bsub"]
        cmd.extend(self.get_bsub_flags(job))

        # Job name
        cmd.extend(["-J", job.id])

        # Log output
        if job.log_path:
            os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
            cmd.extend(["-o", job.log_path])

        # Working directory
        cmd.extend(["-cwd", job.cwd])

        # LSF dependency conditions
        dep_conditions = []
        for dep_id in job.dependencies:
            if dep_id in self._lsf_ids:
                dep_conditions.append(f"done({self._lsf_ids[dep_id]})")
            else:
                # Use job name for deps not yet submitted
                dep_conditions.append(f"done({dep_id})")
        if dep_conditions:
            cmd.extend(["-w", " && ".join(dep_conditions)])

        # The actual command
        cmd.append(" ".join(job.command))

        # Submit
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
            )
            lsf_id = self._parse_job_id(result.stdout)
            if lsf_id:
                self._lsf_ids[job.id] = lsf_id
                logger.info("Submitted job %s as LSF %s", job.id, lsf_id)
            else:
                logger.warning(
                    "Could not parse LSF job ID from: %s", result.stdout
                )
        except subprocess.CalledProcessError as e:
            logger.error("Failed to submit job %s: %s", job.id, e.stderr)
            self._results[job.id] = False
            self._notify(job.id, False)

    def wait_all(self) -> Dict[str, bool]:
        """Poll bjobs until all jobs complete."""
        pending = set(self._lsf_ids.keys()) - set(self._results.keys())

        while pending:
            time.sleep(self.POLL_INTERVAL)

            for job_id in list(pending):
                lsf_id = self._lsf_ids.get(job_id)
                if not lsf_id:
                    continue

                status = self._check_status(lsf_id)
                if status == "DONE":
                    self._results[job_id] = True
                    self._notify(job_id, True)
                    pending.discard(job_id)
                elif status in ("EXIT", "ZOMBI"):
                    self._results[job_id] = False
                    self._notify(job_id, False)
                    pending.discard(job_id)
                # PEND, RUN, etc. -> still waiting

        return dict(self._results)

    def cancel_all(self) -> None:
        for lsf_id in self._lsf_ids.values():
            try:
                subprocess.run(["bkill", lsf_id], capture_output=True)
            except Exception:
                pass

    @staticmethod
    def _parse_job_id(bsub_output: str) -> Optional[str]:
        match = re.search(r"Job <(\d+)>", bsub_output)
        return match.group(1) if match else None

    @staticmethod
    def _check_status(lsf_id: str) -> str:
        try:
            result = subprocess.run(
                ["bjobs", "-noheader", "-o", "stat", lsf_id],
                capture_output=True, text=True,
            )
            return result.stdout.strip()
        except Exception:
            return "UNKNOWN"
