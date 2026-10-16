"""Loading MFCI-Bench data: evaluation sets, manifests, corpora and re-sampling.

Data tiers (see README):
  * ``data/eval/<dataset>.jsonl.gz``     -- the exact 150 builds/dataset used in the paper
  * ``data/manifests/<dataset>.jsonl.gz`` -- one row per build of the full corpus
  * ``data/sources/<dataset>/``           -- single-fault inputs (rebuild anything)
  * GitHub release assets                 -- the full corpora as zstd archives
"""

from __future__ import annotations

import gzip
import json
import os
import random
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

from mfci_bench.sources import DATASETS, PathLike, load_source_bugs

# Per-failure fields that duplicate bug-level information; stored once per build in the
# compact eval files and restored on load.
_SHARED_FIELDS = ('changed_files', 'file_diffs', 'diff_stats')


def data_root() -> Path:
    """Repository ``data/`` directory (override with ``MFCI_BENCH_DATA``)."""
    env = os.environ.get('MFCI_BENCH_DATA')
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / 'data'


def _check(dataset: str) -> None:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; expected one of {DATASETS}")


def _open(path: Path):
    return gzip.open(path, 'rt', encoding='utf-8') if path.suffix == '.gz' else open(path)


# --------------------------------------------------------------------------- compact form

def compact_build(build: Dict) -> Dict:
    """Deduplicate per-failure diff payloads into ``build['_shared']`` (lossless)."""
    shared: List[Dict] = []
    index: Dict[str, int] = {}
    failures = []
    for f in build['failures']:
        payload = {k: f[k] for k in _SHARED_FIELDS if k in f}
        key = json.dumps(payload, sort_keys=True)
        if key not in index:
            index[key] = len(shared)
            shared.append(payload)
        g = {k: v for k, v in f.items() if k not in _SHARED_FIELDS}
        g['_shared'] = index[key]
        failures.append(g)
    out = dict(build)
    out['failures'] = failures
    out['_shared'] = shared
    return out


def expand_build(build: Dict) -> Dict:
    """Inverse of :func:`compact_build`. No-op for already expanded builds."""
    shared = build.get('_shared')
    if shared is None:
        return build
    out = {k: v for k, v in build.items() if k != '_shared'}
    failures = []
    for f in build['failures']:
        g = {k: v for k, v in f.items() if k != '_shared'}
        g.update(shared[f['_shared']])
        failures.append(g)
    out['failures'] = failures
    return out


# --------------------------------------------------------------------------- loaders

def iter_jsonl(path: PathLike) -> Iterator[Dict]:
    with _open(Path(path)) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_eval_set(dataset: str, root: Optional[PathLike] = None) -> List[Dict]:
    """The 150 builds of ``dataset`` used in the paper's evaluation (seed 42), in
    corpus order, each with its ``failures`` inline."""
    _check(dataset)
    path = Path(root or data_root()) / 'eval' / f'{dataset}.jsonl.gz'
    return [expand_build(b) for b in iter_jsonl(path)]


def load_manifest(dataset: str, root: Optional[PathLike] = None) -> List[Dict]:
    """One row per build of the full corpus: index, build_id, project, num_bugs,
    num_failures, difficulty, similarity_score, bug_ids."""
    _check(dataset)
    return list(iter_jsonl(Path(root or data_root()) / 'manifests' / f'{dataset}.jsonl.gz'))


def iter_corpus(path: PathLike) -> Iterator[Dict]:
    """Stream builds from a ``synthetic_builds.jsonl`` (optionally .gz or .zst)."""
    p = Path(path)
    if p.suffix == '.zst':
        import subprocess
        proc = subprocess.Popen(['zstd', '-dc', '--long=31', str(p)], stdout=subprocess.PIPE,
                                text=True, encoding='utf-8')
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.strip():
                yield json.loads(line)
        if proc.wait() != 0:
            raise RuntimeError(f"zstd failed on {p}")
        return
    yield from (expand_build(b) for b in iter_jsonl(p))


# --------------------------------------------------------------------------- sampling

def sample_indices(total: int, n: int, seed: int = 42) -> List[int]:
    """Indices chosen by HyTri's ``load_multifault_builds_sampled`` (sorted)."""
    rng = random.Random(seed)
    return sorted(rng.sample(range(total), min(n, total)))


def sample_stratified_indices(manifest: Sequence[Dict], n: int, seed: int = 42,
                              mix: Optional[Dict[str, float]] = None) -> List[int]:
    """Difficulty-stratified sample (an extension, not used in the paper).

    Takes ``round(n * share)`` builds per tier (capped by availability) and fills any
    shortfall uniformly from the remaining builds.
    """
    mix = mix or {'easy': 0.2, 'medium': 0.4, 'hard': 0.4}
    rng = random.Random(seed)
    by_tier: Dict[str, List[int]] = {}
    for row in manifest:
        by_tier.setdefault(row['difficulty'], []).append(row['index'])
    chosen: List[int] = []
    for tier, share in mix.items():
        pool = by_tier.get(tier, [])
        chosen.extend(rng.sample(pool, min(len(pool), round(n * share))))
    if len(chosen) < n:
        taken = set(chosen)
        rest = [r['index'] for r in manifest if r['index'] not in taken]
        chosen.extend(rng.sample(rest, min(len(rest), n - len(chosen))))
    return sorted(chosen)


def materialize(dataset: str, rows: Sequence[Dict], sources_dir: Optional[PathLike] = None,
                bugs: Optional[Dict] = None) -> List[Dict]:
    """Rebuild full build records for manifest ``rows`` from the single-fault sources."""
    from mfci_bench.generate import build_from_bug_ids

    _check(dataset)
    if bugs is None:
        bugs = load_source_bugs(dataset, sources_dir or data_root() / 'sources', verbose=False)
    return [build_from_bug_ids(bugs, r['bug_ids'], r['build_id'], dataset) for r in rows]


def sample_builds(dataset: str, n: int = 150, seed: int = 42,
                  mix: Optional[Dict[str, float]] = None,
                  root: Optional[PathLike] = None) -> List[Dict]:
    """Sample ``n`` builds of the full corpus and rebuild them from sources.

    ``mix=None`` reproduces the paper's uniform sampling (seed 42 == the eval set);
    passing a mix such as ``{'easy': .2, 'medium': .4, 'hard': .4}`` stratifies.
    """
    manifest = load_manifest(dataset, root)
    if mix is None:
        idx = sample_indices(len(manifest), n, seed)
    else:
        idx = sample_stratified_indices(manifest, n, seed, mix)
    rows = [manifest[i] for i in idx]
    return materialize(dataset, rows, Path(root or data_root()) / 'sources')


# --------------------------------------------------------------------------- helpers

def ground_truth_labels(build: Dict) -> List[int]:
    """Integer cluster label per failure (failures of the same component bug share one)."""
    mapping: Dict[str, int] = {}
    return [mapping.setdefault(f['ground_truth_bug'], len(mapping)) for f in build['failures']]


def save_jsonl_gz(records, path: PathLike, compact: bool = False) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(p, 'wb', mtime=0) as raw:
        for r in records:
            raw.write((json.dumps(compact_build(r) if compact else r) + '\n').encode('utf-8'))


__all__ = [
    'data_root', 'load_eval_set', 'load_manifest', 'iter_corpus', 'sample_indices',
    'sample_stratified_indices', 'materialize', 'sample_builds', 'ground_truth_labels',
    'compact_build', 'expand_build', 'save_jsonl_gz', 'iter_jsonl',
]
