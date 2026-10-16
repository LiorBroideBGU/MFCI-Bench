# Vendored from HyTri scripts/create_defects4j_multifault_realistic.py (load_defects4j_data,
# load_diffs_data) and scripts/create_bears_multifault_realistic.py /
# scripts/create_bugswarm_multifault_realistic.py (load_bears_data / load_bugswarm_data,
# load_builds_data) @ 4039de468073f7a81c3eab2f577654880205467f
# Modified: Bears and BugSwarm loaders were byte-identical apart from their names and are
# merged into load_ci_bugs(); inputs may be gzip-compressed; extract_package takes the
# dataset's prefix list explicitly. Loading logic is otherwise unchanged.
"""Loaders for the single-fault source datasets (``data/sources/<dataset>/``)."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Sequence, Union

from mfci_bench.difficulty import (
    CI_PREFIXES,
    DEFECTS4J_PREFIXES,
    extract_exception_type,
    extract_package,
)

PathLike = Union[str, Path]

DATASETS = ('defects4j', 'bears', 'bugswarm')

# Files expected under data/sources/<dataset>/ (a ``.gz`` variant is also accepted).
SOURCE_FILES = {
    'defects4j': ('failure_instances_defects4j.jsonl', 'defects4j_diffs.json'),
    'bears': ('failure_instances_bears.jsonl', 'builds_bears.jsonl'),
    'bugswarm': ('failure_instances_bugswarm.jsonl', 'builds_bugswarm.jsonl'),
}

PACKAGE_PREFIXES = {
    'defects4j': DEFECTS4J_PREFIXES,
    'bears': CI_PREFIXES,
    'bugswarm': CI_PREFIXES,
}


def open_text(path: PathLike):
    """Open a text file, transparently handling a ``.gz`` sibling."""
    p = Path(path)
    if not p.exists() and Path(str(p) + '.gz').exists():
        p = Path(str(p) + '.gz')
    if p.suffix == '.gz':
        return gzip.open(p, 'rt', encoding='utf-8')
    return open(p, 'r', encoding='utf-8')


def source_paths(dataset: str, sources_dir: PathLike) -> tuple:
    d = Path(sources_dir) / dataset
    return tuple(d / name for name in SOURCE_FILES[dataset])


def _new_bug() -> Dict:
    return {
        'project': None,
        'failures': [],
        'failing_tests': set(),
        'changed_files': set(),
        'file_diffs': {},
        'diff_content': '',
        'diff_stats': {'additions': 0, 'deletions': 0},
        'ground_truth': None,
        'exception_types': set(),
        'packages': set(),
    }


def _split_diff_by_file(diff_content: str) -> Dict[str, str]:
    file_diffs: Dict[str, str] = {}
    if not diff_content:
        return file_diffs
    current_file = None
    current_diff = []
    for line_content in diff_content.split('\n'):
        if line_content.startswith('diff --git') or line_content.startswith('Index:'):
            if current_file and current_diff:
                file_diffs[current_file] = '\n'.join(current_diff)
            if 'diff --git' in line_content:
                parts = line_content.split(' b/')
                if len(parts) > 1:
                    current_file = parts[-1]
            elif 'Index:' in line_content:
                current_file = line_content.replace('Index:', '').strip()
            current_diff = [line_content]
        else:
            current_diff.append(line_content)
    if current_file and current_diff:
        file_diffs[current_file] = '\n'.join(current_diff)
    return file_diffs


def load_defects4j_bugs(failures_path: PathLike, diffs_path: PathLike,
                        verbose: bool = True) -> Dict[str, Dict]:
    """Load Defects4J failure instances grouped by bug_id, enriched with diff data."""
    with open_text(diffs_path) as f:
        diffs_data = json.load(f)
    if verbose:
        print(f"  Loaded diff data for {len(diffs_data)} bugs")

    bugs: Dict[str, Dict] = defaultdict(_new_bug)
    prefixes = DEFECTS4J_PREFIXES

    with open_text(failures_path) as f:
        for line in f:
            failure = json.loads(line)
            bug_id = failure.get('bug_id')
            if not bug_id:
                continue

            # e.g. "Chart-1" -> "Chart"
            project = failure.get('project') or bug_id.split('-')[0]

            diff_info = diffs_data.get(bug_id, {})
            changed_files = diff_info.get('changed_files', [])
            diff_content = diff_info.get('diff', '')
            additions = diff_info.get('additions', 0)
            deletions = diff_info.get('deletions', 0)
            file_diffs = _split_diff_by_file(diff_content)

            failure['changed_files'] = changed_files
            failure['file_diffs'] = file_diffs
            failure['diff_stats'] = {'additions': additions, 'deletions': deletions}

            bug = bugs[bug_id]
            bug['project'] = project
            bug['failures'].append(failure)
            bug['failing_tests'].add(failure.get('test_name', ''))
            bug['changed_files'].update(changed_files)
            bug['file_diffs'].update(file_diffs)
            bug['diff_content'] = diff_content
            bug['diff_stats']['additions'] = additions
            bug['diff_stats']['deletions'] = deletions
            bug['ground_truth'] = failure.get('ground_truth', {})

            bug['exception_types'].add(extract_exception_type(failure))
            for cf in changed_files:
                pkg = extract_package(cf, prefixes)
                if pkg:
                    bug['packages'].add(pkg)

    return dict(bugs)


def load_ci_bugs(failures_path: PathLike, builds_path: PathLike,
                 prefixes: Sequence[str] = CI_PREFIXES, verbose: bool = True) -> Dict[str, Dict]:
    """Load Bears / BugSwarm failure instances grouped by bug_id, enriched with diffs.

    Note: a bug's ``diff_stats`` accumulates the per-failure stats (i.e. it is the
    per-build additions/deletions multiplied by the number of failures). This mirrors
    the code that produced the paper's corpora and is kept for exact reproducibility.
    """
    builds_data: Dict[str, Dict] = {}
    with open_text(builds_path) as f:
        for line in f:
            build = json.loads(line)
            build_id = build.get('build_id')
            if build_id:
                builds_data[build_id] = {
                    'changed_files': build.get('changed_files', []),
                    'file_diffs': build.get('file_diffs', {}),
                    'additions': build.get('additions', 0),
                    'deletions': build.get('deletions', 0),
                }
    if verbose:
        print(f"  Loaded diff data for {len(builds_data)} builds")

    bugs: Dict[str, Dict] = defaultdict(_new_bug)
    with open_text(failures_path) as f:
        for line in f:
            failure = json.loads(line)
            bug_id = failure.get('bug_id')
            if not bug_id:
                continue

            build_info = builds_data.get(failure.get('build_id'), {})
            failure['changed_files'] = build_info.get('changed_files', [])
            failure['file_diffs'] = build_info.get('file_diffs', {})
            failure['diff_stats'] = {
                'additions': build_info.get('additions', 0),
                'deletions': build_info.get('deletions', 0),
            }

            bug = bugs[bug_id]
            bug['project'] = failure.get('project')
            bug['failures'].append(failure)
            bug['failing_tests'].add(failure.get('test_name', ''))
            bug['changed_files'].update(failure['changed_files'])
            bug['file_diffs'].update(failure['file_diffs'])
            bug['diff_stats']['additions'] += failure['diff_stats']['additions']
            bug['diff_stats']['deletions'] += failure['diff_stats']['deletions']
            bug['ground_truth'] = failure.get('ground_truth', {})

            bug['exception_types'].add(extract_exception_type(failure))
            for cf in failure['changed_files']:
                pkg = extract_package(cf, prefixes)
                if pkg:
                    bug['packages'].add(pkg)

    return dict(bugs)


def load_source_bugs(dataset: str, sources_dir: PathLike, verbose: bool = True) -> Dict[str, Dict]:
    """Load the single-fault bugs of ``dataset`` from ``sources_dir/<dataset>/``."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; expected one of {DATASETS}")
    a, b = source_paths(dataset, sources_dir)
    if dataset == 'defects4j':
        return load_defects4j_bugs(a, b, verbose=verbose)
    return load_ci_bugs(a, b, PACKAGE_PREFIXES[dataset], verbose=verbose)
