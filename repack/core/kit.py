from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from .request import RepackRequest

@dataclass(frozen=True)
class KitTarget:
    """
    Represents an atomic unit of work to be scheduled.
    """
    kit_name: str
    pvt: Optional[str] = None
    
    @property
    def id(self) -> str:
        """Returns a unique string identifier for this target."""
        if self.pvt:
            return f"{self.kit_name}::{self.pvt}"
        return f"{self.kit_name}::ALL"

class Kit(ABC):
    """
    Abstract base class for all Repack kits.
    """
    
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_output_path(self, request: RepackRequest) -> str:
        """
        Returns the absolute path to the output directory.
        Used for cleaning before a full run.
        """
        pass

    @abstractmethod
    def get_targets(self, request: RepackRequest) -> List[KitTarget]:
        """
        Returns a list of schedule-able targets for this kit
        based on the request (e.g., expanded PVTs).
        """
        pass

    @abstractmethod
    def get_dependencies(self) -> List[str]:
        """
        Returns a list of Kit names that this Kit depends on.
        """
        pass

    @abstractmethod
    def construct_command(self, target: KitTarget, request: RepackRequest) -> List[str]:
        """
        Returns the command line arguments to execute.
        """
        pass

    def clean_output_path(self, request: RepackRequest) -> None:
        """
        Helper to clean the output directory.
        Subclasses can override if specialized cleaning is needed.
        """
        # Implementation to be added in Utils or here
        pass
