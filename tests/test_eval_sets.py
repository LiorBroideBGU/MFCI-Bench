"""Smoke tests: the shipped eval sets match the paper and satisfy the construction invariants."""

from collections import Counter

import pytest

from mfci_bench import (
    DATASETS,
    evaluate_build,
    ground_truth_labels,
    load_eval_set,
    load_manifest,
    materialize,
    sample_indices,
)
from mfci_bench.compare import builds_equal
from mfci_bench.difficulty import classify

# Paper, Table "MFCI-Bench statistics (150 builds per dataset)".
PAPER = {
    'defects4j': {'failures': 1787, 'max': 48, 'k': {2: 45, 3: 74, 4: 19, 5: 12}},
    'bears': {'failures': 6003, 'max': 152, 'k': {2: 1, 3: 10, 4: 47, 5: 92}},
    'bugswarm': {'failures': 3514, 'max': 114, 'k': {2: 12, 3: 26, 4: 49, 5: 63}},
}
# Paper Sec. "Difficulty Levels and General Statistics": full corpus sizes.
CORPUS_SIZE = {'defects4j': 5162, 'bears': 12856, 'bugswarm': 4139}


@pytest.fixture(scope='module', params=DATASETS)
def dataset(request):
    return request.param, load_eval_set(request.param)


def test_counts_match_paper(dataset):
    name, builds = dataset
    assert len(builds) == 150
    assert len({b['build_id'] for b in builds}) == 150
    assert sum(len(b['failures']) for b in builds) == PAPER[name]['failures']
    assert max(len(b['failures']) for b in builds) == PAPER[name]['max']
    assert dict(Counter(b['num_bugs'] for b in builds)) == PAPER[name]['k']


def test_construction_invariants(dataset):
    _, builds = dataset
    for b in builds:
        comps = b['component_bugs']
        assert 2 <= b['num_bugs'] == len(comps) <= 5
        assert b['num_failures'] == len(b['failures'])
        # (1) disjoint changed files
        files = [f for c in comps for f in c['changed_files']]
        assert len(files) == len(set(files)), b['build_id']
        # (2) disjoint failing tests
        tests_by_bug = {}
        for f in b['failures']:
            tests_by_bug.setdefault(f['ground_truth_bug'], set()).add(f['test_name'])
        all_tests = [t for ts in tests_by_bug.values() for t in ts]
        assert len(all_tests) == len(set(all_tests)), b['build_id']
        # each component bug has >= 2 distinct failing tests and every failure is labelled
        assert set(tests_by_bug) == {c['bug_id'] for c in comps}
        assert all(len(ts) >= 2 for ts in tests_by_bug.values())
        # same project
        assert len({f['project'] for f in b['failures']}) == 1
        # difficulty label consistent with score
        assert classify(b['similarity_score']) == b['difficulty']
        assert len(set(ground_truth_labels(b))) == b['num_bugs']


def test_eval_set_is_seed42_sample_of_manifest(dataset):
    name, builds = dataset
    manifest = load_manifest(name)
    assert len(manifest) == CORPUS_SIZE[name]
    picked = [manifest[i]['build_id'] for i in sample_indices(len(manifest), 150, 42)]
    assert picked == [b['build_id'] for b in builds]


def test_perfect_prediction_scores_one(dataset):
    _, builds = dataset
    m = evaluate_build(builds[0], ground_truth_labels(builds[0]))
    assert m['ari'] == pytest.approx(1.0) and m['bcubed_f1'] == pytest.approx(1.0)


@pytest.mark.slow
def test_manifest_expansion_reproduces_eval_builds(dataset):
    """Rebuilding from data/sources gives the shipped builds field-for-field
    (up to created_at and the order of set-valued fields)."""
    name, builds = dataset
    rows = {r['build_id']: r for r in load_manifest(name)}
    sample = builds[:10]
    rebuilt = materialize(name, [rows[b['build_id']] for b in sample])
    for a, b in zip(sample, rebuilt):
        assert builds_equal(a, b), a['build_id']
