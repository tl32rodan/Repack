from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Callable

@dataclass
class Job:
    """
    Represents a standardized execution unit.
    """
    id: str
    command: List[str]
    cwd: str
    log_path: str
    environment: Dict[str, str] = field(default_factory=dict)

class Executor(ABC):
    """
    Abstract interface for executing jobs.
    """

    @abstractmethod
    def submit(self, job: Job, dependency_job_ids: List[str] = None, on_complete: Callable[[str, bool], None] = None) -> str:
        """
        Submits a job for execution.

        Args:
            job: The Job object to execute.
            dependency_job_ids: List of job IDs that this job depends on.
            on_complete: Optional callback invoked when job finishes.
                         Args: job_id (str), success (bool).

        Returns:
            The job_id assigned by the executor (may match input job.id).
        """
        pass

    @abstractmethod
    def wait(self, job_ids: List[str]) -> None:
        """
        Waits for the specified jobs to complete.
        """
        pass
