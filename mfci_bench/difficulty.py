# Vendored from HyTri scripts/create_defects4j_multifault_realistic.py,
# scripts/create_bears_multifault_realistic.py and
# scripts/create_bugswarm_multifault_realistic.py
# @ 4039de468073f7a81c3eab2f577654880205467f
# Modified: the three copies were merged into one module; the only difference between
# them (the path-prefix list used by extract_package) is now the `prefixes` argument;
# float_sum() replaces the built-in sum() for version-independent results.
"""Inter-bug similarity and build difficulty scoring (paper Sec. "Difficulty Levels").

For a pair of bugs the combined score is

    0.3 * package_jaccard + 0.4 * exception_jaccard + 0.3 * frame_jaccard

and a build's score is the mean over all C(k, 2) bug pairs. Builds are labelled
easy (< 0.1), medium (0.1 to < 0.3) or hard (>= 0.3).
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

# Path prefixes stripped before taking the directory as the "package".
# Defects4J additionally strips 'source/' (used by e.g. Closure / Mockito layouts).
DEFECTS4J_PREFIXES: Tuple[str, ...] = (
    'src/main/java/', 'src/test/java/', 'source/', 'src/', 'main/', 'test/',
)
CI_PREFIXES: Tuple[str, ...] = ('src/main/java/', 'src/test/java/', 'src/', 'main/', 'test/')

WEIGHTS = {'package': 0.3, 'exception': 0.4, 'frame': 0.3}
EASY_THRESHOLD = 0.1
HARD_THRESHOLD = 0.3


def extract_package(file_path: str, prefixes: Sequence[str] = DEFECTS4J_PREFIXES) -> str:
    """Extract package/module from file path."""
    path = file_path.replace('\\', '/')
    for prefix in prefixes:
        if prefix in path:
            path = path.split(prefix)[-1]

    parts = path.rsplit('/', 1)
    if len(parts) > 1:
        return parts[0].replace('/', '.')
    return ''


def extract_exception_type(failure: Dict) -> str:
    """Extract normalized exception type (simple class name)."""
    exc_type = failure.get('exception_type', '')
    if not exc_type:
        return 'Unknown'
    return exc_type.split('.')[-1]


def extract_stack_frames(failure: Dict) -> List[str]:
    """Top-10 stack frame signatures normalised to ``Class.method``."""
    frames = failure.get('frames', [])
    signatures = []
    for f in frames[:10]:
        func = f.get('func', '')
        if func:
            parts = func.split('.')
            if len(parts) >= 2:
                signatures.append('.'.join(parts[-2:]))
            else:
                signatures.append(func)
    return signatures


def _package_set(changed_files: Iterable[str], prefixes: Sequence[str]) -> set:
    packages = set()
    for f in changed_files:
        pkg = extract_package(f, prefixes)
        if pkg:
            packages.add(pkg)
            parts = pkg.split('.')
            for i in range(1, len(parts)):
                packages.add('.'.join(parts[:i]))
    return packages


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union > 0 else 0.0


def compute_package_similarity(bug1: Dict, bug2: Dict,
                               prefixes: Sequence[str] = DEFECTS4J_PREFIXES) -> float:
    """Jaccard over package prefixes (including parents) of changed files."""
    return _jaccard(_package_set(bug1.get('changed_files', set()), prefixes),
                    _package_set(bug2.get('changed_files', set()), prefixes))


def compute_exception_similarity(bug1: Dict, bug2: Dict) -> float:
    """Jaccard over normalised exception types of the bugs' failures."""
    return _jaccard({extract_exception_type(f) for f in bug1.get('failures', [])},
                    {extract_exception_type(f) for f in bug2.get('failures', [])})


def compute_frame_similarity(bug1: Dict, bug2: Dict) -> float:
    """Jaccard over top-10 ``Class.method`` frames of the bugs' failures."""
    frames1: set = set()
    frames2: set = set()
    for f in bug1.get('failures', []):
        frames1.update(extract_stack_frames(f))
    for f in bug2.get('failures', []):
        frames2.update(extract_stack_frames(f))
    return _jaccard(frames1, frames2)


def compute_bug_similarity(bug1: Dict, bug2: Dict,
                           prefixes: Sequence[str] = DEFECTS4J_PREFIXES) -> Dict[str, float]:
    return {
        'package': compute_package_similarity(bug1, bug2, prefixes),
        'exception': compute_exception_similarity(bug1, bug2),
        'frame': compute_frame_similarity(bug1, bug2),
    }



def float_sum(values: Sequence[float]) -> float:
    """Sum floats exactly as CPython >= 3.12's built-in ``sum`` does (Neumaier
    compensated summation). The paper corpora were generated with Python 3.12, whose
    ``sum`` differs from 3.10/3.11 in the last bits; using this keeps similarity scores
    bit-identical on every supported Python version."""
    it = iter(values)
    try:
        total = 0 + next(it)
    except StopIteration:
        return 0
    comp = 0.0
    for x in it:
        t = total + x
        if abs(total) >= abs(x):
            comp += (total - t) + x
        else:
            comp += (x - t) + total
        total = t
    if comp and math.isfinite(comp):
        total += comp
    return total


def classify(score: float) -> str:
    if score < EASY_THRESHOLD:
        return 'easy'
    if score < HARD_THRESHOLD:
        return 'medium'
    return 'hard'


def compute_combo_difficulty(bugs_list: List[Dict],
                             prefixes: Sequence[str] = DEFECTS4J_PREFIXES) -> Tuple[str, float]:
    """Difficulty of a bug combination: (level, mean pairwise combined score).

    ``bugs_list`` items are ``{'bug_id': ..., 'data': <bug record>}`` where a bug record
    has ``changed_files`` and ``failures``.
    """
    if len(bugs_list) < 2:
        return 'easy', 0.0

    similarities = []
    for i, bug1 in enumerate(bugs_list):
        for bug2 in bugs_list[i + 1:]:
            sim = compute_bug_similarity(bug1['data'], bug2['data'], prefixes)
            combined = (
                0.3 * sim['package'] +
                0.4 * sim['exception'] +
                0.3 * sim['frame']
            )
            similarities.append(combined)

    avg_similarity = float_sum(similarities) / len(similarities) if similarities else 0.0
    return classify(avg_similarity), avg_similarity
