"""SpecCollection - manages per-kit specs and change detection via hashing."""

import hashlib
import json
from typing import Any, Dict, Optional


class SpecCollection:
    """Holds per-kit spec data and computes hashes for change detection.

    The conversion layer (ddi_converter) populates this from ddi.sh args.
    Each kit can have its own spec dict, plus there's a global spec section.
    """

    def __init__(self, global_spec: Optional[Dict[str, Any]] = None):
        self._global: Dict[str, Any] = global_spec or {}
        self._kit_specs: Dict[str, Dict[str, Any]] = {}
        self._hash_cache: Dict[str, str] = {}

    @property
    def global_spec(self) -> Dict[str, Any]:
        return self._global

    def set_kit_spec(self, kit_name: str, spec: Dict[str, Any]) -> None:
        """Set or update spec for a specific kit."""
        self._kit_specs[kit_name] = spec
        self._hash_cache.pop(kit_name, None)

    def get_kit_spec(self, kit_name: str) -> Dict[str, Any]:
        """Get spec for a kit, merged with global spec.

        Kit-specific values override global values.
        """
        merged = dict(self._global)
        merged.update(self._kit_specs.get(kit_name, {}))
        return merged

    def compute_hash(self, kit_name: str) -> str:
        """Compute a deterministic hash of the kit's effective spec.

        Used for incremental run detection: if spec hash changes,
        the kit needs to be re-run.
        """
        if kit_name in self._hash_cache:
            return self._hash_cache[kit_name]

        spec = self.get_kit_spec(kit_name)
        canonical = json.dumps(spec, sort_keys=True, default=str)
        h = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        self._hash_cache[kit_name] = h
        return h

    def has_changed(self, kit_name: str, previous_hash: str) -> bool:
        """Check if a kit's spec has changed compared to a previous hash."""
        return self.compute_hash(kit_name) != previous_hash
