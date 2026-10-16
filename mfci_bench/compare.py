"""Order-insensitive comparison of build records (used by tests and verification)."""

from __future__ import annotations

from typing import Dict

# Fields that are sets in the generator; their list order in the paper corpora depends on
# Python's string hash seed, so they are compared as sets.
_SET_FIELDS = ('changed_files', 'exception_types', 'packages')


def normalize_build(build: Dict) -> Dict:
    b = {k: v for k, v in build.items() if k != 'created_at'}
    b['combined_changed_files'] = sorted(b.get('combined_changed_files', []))
    b['component_bugs'] = [
        {k: (sorted(v) if k in _SET_FIELDS else v) for k, v in c.items()}
        for c in b.get('component_bugs', [])
    ]
    return b


def builds_equal(a: Dict, b: Dict) -> bool:
    """Equal up to created_at and the order of set-valued fields."""
    return normalize_build(a) == normalize_build(b)
