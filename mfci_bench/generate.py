# Vendored from HyTri scripts/create_defects4j_multifault_realistic.py,
# scripts/create_bears_multifault_realistic.py and
# scripts/create_bugswarm_multifault_realistic.py
# @ 4039de468073f7a81c3eab2f577654880205467f
# Modified: the three scripts are merged into one module (dataset-specific behaviour is
# selected by `dataset`); module-level constants became arguments (seed, max_builds,
# difficulty mix, k range); the global `random` module is replaced by a seeded
# random.Random instance (same sequence as random.seed(seed)); builds are streamed to disk
# instead of held in memory; a manifest is written alongside. Selection and
# build-construction logic is unchanged, so seed 42 reproduces the paper's corpora.
# Set-valued fields (changed_files, exception_types, packages) are now emitted sorted; the
# original emitted them in hash-seed-dependent set order, so only their order differs.
"""Multi-fault CI build synthesis (paper Sec. "CI Build Synthesis").

Combine k in {2..5} single-fault bugs of the same project such that every bug has
at least two failing tests, and no two bugs share a changed file or a failing test.
"""

from __future__ import annotations

import gzip
import json
import random
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from mfci_bench.difficulty import compute_combo_difficulty
from mfci_bench.sources import DATASETS, PACKAGE_PREFIXES, load_source_bugs

MIN_TESTS_PER_BUG = 2
MIN_BUGS_PER_BUILD = 2
MAX_BUGS_PER_BUILD = 5
RANDOM_SEED = 42
DEFAULT_DIFFICULTY_MIX = {'easy': 0.20, 'medium': 0.40, 'hard': 0.40}

# Defects4J only: combos per project are capped and large projects are sampled.
D4J_MAX_COMBOS_PER_PROJECT = 500
D4J_SAMPLING_THRESHOLD = 50

SOURCE_LABEL = {
    'defects4j': 'Defects4J dataset (realistic)',
    'bears': 'Bears dataset (realistic)',
    'bugswarm': 'BugSwarm dataset (realistic)',
}


def check_no_overlaps(bugs_list: List[Dict]) -> bool:
    """True iff the bugs share no changed file and no failing test."""
    all_files: set = set()
    all_tests: set = set()
    for bug in bugs_list:
        bug_files = bug['data']['changed_files']
        bug_tests = bug['data']['failing_tests']
        if all_files & bug_files or all_tests & bug_tests:
            return False
        all_files.update(bug_files)
        all_tests.update(bug_tests)
    return True


def _bugs_by_project(bugs: Dict[str, Dict], min_tests: int) -> Dict[str, List[Dict]]:
    by_project: Dict[str, List[Dict]] = defaultdict(list)
    for bug_id, data in bugs.items():
        if len(data['failing_tests']) >= min_tests and data['project']:
            by_project[data['project']].append({'bug_id': bug_id, 'data': data})
    return by_project


def _combo(project, bug_list, prefixes) -> Dict:
    difficulty, similarity = compute_combo_difficulty(bug_list, prefixes)
    return {
        'project': project,
        'bugs': bug_list,
        'num_bugs': len(bug_list),
        'difficulty': difficulty,
        'similarity_score': similarity,
    }


def find_combinations_defects4j(bugs, rng: random.Random, min_tests=MIN_TESTS_PER_BUG,
                                min_bugs=MIN_BUGS_PER_BUILD, max_bugs=MAX_BUGS_PER_BUILD,
                                max_combos_per_project=D4J_MAX_COMBOS_PER_PROJECT,
                                verbose=True) -> Dict[str, List[Dict]]:
    """Defects4J variant: projects sorted, <=500 combos per project, projects with
    more than 50 eligible bugs are sampled randomly instead of enumerated."""
    prefixes = PACKAGE_PREFIXES['defects4j']
    by_project = _bugs_by_project(bugs, min_tests)
    if verbose:
        print(f"  Bugs with {min_tests}+ failing tests: {sum(len(v) for v in by_project.values())}")
    out: Dict[str, List[Dict]] = {'easy': [], 'medium': [], 'hard': []}

    for project, proj_bugs in sorted(by_project.items()):
        if len(proj_bugs) < min_bugs:
            continue
        project_combos: List[Dict] = []
        if len(proj_bugs) > D4J_SAMPLING_THRESHOLD:
            attempts = max_combos_per_project * 10
            for _ in range(attempts):
                if len(project_combos) >= max_combos_per_project:
                    break
                combo_size = rng.choice(range(min_bugs, min(max_bugs + 1, len(proj_bugs) + 1)))
                bug_list = list(tuple(rng.sample(proj_bugs, combo_size)))
                if check_no_overlaps(bug_list):
                    project_combos.append(_combo(project, bug_list, prefixes))
        else:
            for combo_size in range(min_bugs, min(max_bugs + 1, len(proj_bugs) + 1)):
                for bug_combo in combinations(proj_bugs, combo_size):
                    bug_list = list(bug_combo)
                    if check_no_overlaps(bug_list):
                        project_combos.append(_combo(project, bug_list, prefixes))
                    if len(project_combos) >= max_combos_per_project:
                        break
                if len(project_combos) >= max_combos_per_project:
                    break
        if verbose:
            print(f"  {project}: {len(proj_bugs)} eligible bugs -> {len(project_combos)} valid combos")
        for combo in project_combos:
            out[combo['difficulty']].append(combo)
    return out


def find_combinations_exhaustive(bugs, dataset: str, min_tests=MIN_TESTS_PER_BUG,
                                 min_bugs=MIN_BUGS_PER_BUILD, max_bugs=MAX_BUGS_PER_BUILD,
                                 verbose=True) -> Dict[str, List[Dict]]:
    """Bears / BugSwarm variant: exhaustive enumeration, projects in file order."""
    prefixes = PACKAGE_PREFIXES[dataset]
    by_project = _bugs_by_project(bugs, min_tests)
    out: Dict[str, List[Dict]] = {'easy': [], 'medium': [], 'hard': []}
    for project, proj_bugs in by_project.items():
        if len(proj_bugs) < min_bugs:
            continue
        n = 0
        for combo_size in range(min_bugs, min(max_bugs + 1, len(proj_bugs) + 1)):
            for bug_combo in combinations(proj_bugs, combo_size):
                bug_list = list(bug_combo)
                if check_no_overlaps(bug_list):
                    combo = _combo(project, bug_list, prefixes)
                    out[combo['difficulty']].append(combo)
                    n += 1
        if verbose:
            print(f"  {project}: {len(proj_bugs)} eligible bugs -> {n} valid combos")
    return out


def select_balanced_combinations(combos_by_difficulty: Dict[str, List[Dict]],
                                 rng: random.Random, target_count: Optional[int] = None,
                                 mix: Dict[str, float] = DEFAULT_DIFFICULTY_MIX) -> List[Dict]:
    """Take int(target * share) combos per tier, then fill up from any tier.

    With ``target_count=None`` (the paper setting) the target is *all* valid combos, so
    every combo is kept and the corpus difficulty distribution is whatever the data
    yields -- the 20/40/40 mix is only enforced when a smaller target is given.
    """
    selected: List[Dict] = []
    total_available = sum(len(c) for c in combos_by_difficulty.values())
    if target_count is None:
        target_count = total_available

    for difficulty, share in mix.items():
        target_for_difficulty = int(target_count * share)
        available = combos_by_difficulty[difficulty]
        rng.shuffle(available)
        selected.extend(available[:target_for_difficulty])

    remaining = target_count - len(selected)
    if remaining > 0:
        all_remaining: List[Dict] = []
        for difficulty, combos in combos_by_difficulty.items():
            used = int(target_count * mix[difficulty])
            all_remaining.extend(combos[used:])
        rng.shuffle(all_remaining)
        selected.extend(all_remaining[:remaining])
    return selected


def create_synthetic_build(combo: Dict, build_id: str) -> Dict:
    """Assemble one multi-fault build record from a bug combination."""
    all_failures = []
    all_changed_files: set = set()
    all_file_diffs: Dict[str, str] = {}
    total_additions = 0
    total_deletions = 0
    component_bugs = []

    for bug in combo['bugs']:
        bug_id = bug['bug_id']
        bug_data = bug['data']
        for failure in bug_data['failures']:
            synth_failure = failure.copy()
            synth_failure['original_build_id'] = failure.get('build_id')
            synth_failure['synthetic_build_id'] = build_id
            synth_failure['ground_truth_bug'] = bug_id
            all_failures.append(synth_failure)

        all_changed_files.update(bug_data['changed_files'])
        all_file_diffs.update(bug_data.get('file_diffs', {}))
        total_additions += bug_data.get('diff_stats', {}).get('additions', 0)
        total_deletions += bug_data.get('diff_stats', {}).get('deletions', 0)

        component_bugs.append({
            'bug_id': bug_id,
            'num_failures': len(bug_data['failures']),
            'changed_files': sorted(bug_data['changed_files']),
            'file_diffs': bug_data.get('file_diffs', {}),
            'diff_stats': bug_data.get('diff_stats', {}),
            'ground_truth': bug_data['ground_truth'],
            'exception_types': sorted(bug_data.get('exception_types', set())),
            'packages': sorted(bug_data.get('packages', set())),
        })

    return {
        'build_id': build_id,
        'project': combo['project'],
        'num_bugs': combo['num_bugs'],
        'num_failures': len(all_failures),
        'difficulty': combo.get('difficulty', 'unknown'),
        'similarity_score': combo.get('similarity_score', 0.0),
        'component_bugs': component_bugs,
        'combined_changed_files': sorted(all_changed_files),
        'combined_file_diffs': all_file_diffs,
        'combined_diff_stats': {'additions': total_additions, 'deletions': total_deletions},
        'failures': all_failures,
        'created_at': datetime.now().isoformat(),
    }


def build_from_bug_ids(bugs: Dict[str, Dict], bug_ids: Sequence[str], build_id: str,
                       dataset: str) -> Dict:
    """Rebuild a build deterministically from its component bug ids (manifest row)."""
    missing = [b for b in bug_ids if b not in bugs]
    if missing:
        raise KeyError(f"bug ids not in sources: {missing}")
    bug_list = [{'bug_id': b, 'data': bugs[b]} for b in bug_ids]
    project = bugs[bug_ids[0]]['project']
    combo = _combo(project, bug_list, PACKAGE_PREFIXES[dataset])
    return create_synthetic_build(combo, build_id)


def to_failure_instances(build: Dict, language: Optional[str] = None) -> Iterable[Dict]:
    """Flatten a build into evaluation failure records
    (the format of ``failure_instances_multifault.jsonl``)."""
    for failure in build['failures']:
        yield {
            'build_id': build['build_id'],
            'failure_id': f"{build['build_id']}::{failure.get('failure_id', failure.get('test_name', ''))}",
            'test_name': failure.get('test_name'),
            'exception_type': failure.get('exception_type'),
            'exception_message': failure.get('exception_message'),
            'stack_trace': failure.get('stack_trace'),
            'frames': failure.get('frames', []),
            'project': build['project'],
            'ground_truth': {
                'root_cause_id': failure['ground_truth_bug'],
                'changed_files': failure.get('changed_files', []),
                'original_bug_id': failure['ground_truth_bug'],
            },
            'language': language or failure.get('language', 'java'),
            'changed_files': failure.get('changed_files', []),
            'file_diffs': failure.get('file_diffs', {}),
            'diff_stats': failure.get('diff_stats', {}),
            'build_changed_files': build['combined_changed_files'],
            'build_file_diffs': build.get('combined_file_diffs', {}),
            'difficulty': build['difficulty'],
        }


def manifest_row(index: int, build: Dict) -> Dict:
    return {
        'index': index,
        'build_id': build['build_id'],
        'project': build['project'],
        'num_bugs': build['num_bugs'],
        'num_failures': build['num_failures'],
        'difficulty': build['difficulty'],
        'similarity_score': build['similarity_score'],
        'bug_ids': [c['bug_id'] for c in build['component_bugs']],
    }


def generate(dataset: str, sources_dir, output_dir, seed: int = RANDOM_SEED,
             max_builds: Optional[int] = None, mix: Dict[str, float] = DEFAULT_DIFFICULTY_MIX,
             min_bugs: int = MIN_BUGS_PER_BUILD, max_bugs: int = MAX_BUGS_PER_BUILD,
             write_builds: bool = True, write_failures: bool = True,
             verbose: bool = True) -> Dict:
    """Generate a multi-fault corpus. Returns the summary dict.

    Writes to ``output_dir``: ``manifest.jsonl.gz`` (always), ``synthetic_builds.jsonl``
    and ``failure_instances_multifault.jsonl`` (unless disabled), ``dataset_summary.json``.
    """
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    rng = random.Random(seed)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Loading {dataset} single-fault bugs from {sources_dir} ...")
    bugs = load_source_bugs(dataset, sources_dir, verbose=verbose)
    if verbose:
        print(f"Loaded {len(bugs)} unique bugs\nFinding valid combinations ...")

    if dataset == 'defects4j':
        combos = find_combinations_defects4j(bugs, rng, MIN_TESTS_PER_BUG, min_bugs, max_bugs,
                                             verbose=verbose)
    else:
        combos = find_combinations_exhaustive(bugs, dataset, MIN_TESTS_PER_BUG, min_bugs,
                                              max_bugs, verbose=verbose)
    if verbose:
        for d, c in combos.items():
            print(f"  {d}: {len(c)} combinations")

    selected = select_balanced_combinations(combos, rng, max_builds, mix)
    rng.shuffle(selected)

    builds_f = open(out / 'synthetic_builds.jsonl', 'w') if write_builds else None
    fails_f = open(out / 'failure_instances_multifault.jsonl', 'w') if write_failures else None
    manifest_f = gzip.open(out / 'manifest.jsonl.gz', 'wt', encoding='utf-8')
    total_failures = 0
    difficulty_dist: Counter = Counter()
    cluster_dist: Counter = Counter()
    sim_sum = 0.0
    projects = set()
    by_diff = defaultdict(lambda: {'builds': 0, 'total_failures': 0, 'sim': 0.0})
    builds_with_diffs = 0
    total_diff_files = 0
    try:
        for idx, combo in enumerate(selected):
            build = create_synthetic_build(combo, f"synthetic_{dataset}_{idx:04d}")
            if builds_f:
                builds_f.write(json.dumps(build) + '\n')
            if fails_f:
                lang = 'java' if dataset == 'defects4j' else None
                for rec in to_failure_instances(build, language=lang):
                    fails_f.write(json.dumps(rec) + '\n')
            manifest_f.write(json.dumps(manifest_row(idx, build)) + '\n')
            total_failures += build['num_failures']
            difficulty_dist[build['difficulty']] += 1
            cluster_dist[build['num_bugs']] += 1
            sim_sum += build['similarity_score']
            projects.add(build['project'])
            bd = by_diff[build['difficulty']]
            bd['builds'] += 1
            bd['total_failures'] += build['num_failures']
            bd['sim'] += build['similarity_score']
            if build.get('combined_file_diffs'):
                builds_with_diffs += 1
            total_diff_files += len(build.get('combined_file_diffs', {}))
    finally:
        for fh in (builds_f, fails_f, manifest_f):
            if fh:
                fh.close()

    n = len(selected)
    summary = {
        'created_at': datetime.now().isoformat(),
        'source': SOURCE_LABEL[dataset],
        'config': {
            'min_tests_per_bug': MIN_TESTS_PER_BUG,
            'min_bugs_per_build': min_bugs,
            'max_bugs_per_build': max_bugs,
            'random_seed': seed,
            'max_builds': max_builds,
            'difficulty_distribution_target': mix,
        },
        'stats': {
            'total_builds': n,
            'total_failures': total_failures,
            'unique_projects': len(projects),
            'avg_failures_per_build': total_failures / n if n else 0,
            'avg_clusters_per_build': sum(k * c for k, c in cluster_dist.items()) / n if n else 0,
            'avg_similarity_score': sim_sum / n if n else 0,
            'difficulty_distribution': dict(difficulty_dist),
            'cluster_distribution': dict(sorted(cluster_dist.items())),
            'builds_with_diffs': builds_with_diffs,
            'total_diff_files': total_diff_files,
        },
        'by_difficulty': {
            d: {'builds': v['builds'], 'total_failures': v['total_failures'],
                'avg_similarity': v['sim'] / v['builds']}
            for d, v in ((d, by_diff[d]) for d in ('easy', 'medium', 'hard')) if v['builds']
        },
    }
    with open(out / 'dataset_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    if verbose:
        s = summary['stats']
        print(f"Wrote {n} builds / {total_failures} failures to {out}")
        print(f"  difficulty: {s['difficulty_distribution']}  k: {s['cluster_distribution']}")
    return summary
