"""Abstract executor interface and Job dataclass."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


@dataclass
class Job:
    """A single executable unit in the repack pipeline."""

    id: str
    command: List[str]
    cwd: str = "."
    log_path: str = ""
    environment: Dict[str, str] = field(default_factory=dict)
    dependencies: Set[str] = field(default_factory=set)


class Executor(ABC):
    """Abstract base for job execution backends."""

    @abstractmethod
    def submit(self, job: Job) -> None:
        """Submit a job for execution.

        The executor is responsible for honoring job.dependencies -
        the job should not start until all dependencies have completed.
        """

    @abstractmethod
    def wait_all(self) -> Dict[str, bool]:
        """Wait for all submitted jobs to complete.

        Returns:
            Dict mapping job_id -> success (True/False)
        """

    @abstractmethod
    def cancel_all(self) -> None:
        """Cancel all pending/running jobs."""

    def set_callback(self, callback: Callable[[str, bool], None]) -> None:
        """Set a callback to be invoked when each job completes.

        Args:
            callback: function(job_id, success) called on completion.
        """
        self._callback = callback

    def _notify(self, job_id: str, success: bool) -> None:
        if hasattr(self, "_callback") and self._callback:
            self._callback(job_id, success)
