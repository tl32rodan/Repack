from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class RepackRequest:
    """
    Holds the global configuration for a Repack run.
    """
    library_name: str
    pvts: List[str]
    corners: List[str]
    cells: List[str]
    output_root: str
    
    # Optional metadata or extra flags
    extra_options: Dict[str, Any] = field(default_factory=dict)
