# B-cubed functions vendored from HyTri scripts/run_evaluation.py
# (compute_bcubed_precision/recall/f1, compute_all_metrics)
# @ 4039de468073f7a81c3eab2f577654880205467f
# Modified: added evaluate_build / evaluate_builds wrappers.
"""Partition metrics used in the paper: ARI, NMI, V-measure and B-cubed P/R/F1.

Metrics are computed per build and macro-averaged over builds.
"""

from __future__ import annotations

from statistics import mean
from typing import Dict, List, Mapping, Sequence

import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, v_measure_score

METRICS = ('ari', 'nmi', 'v_measure', 'bcubed_precision', 'bcubed_recall', 'bcubed_f1')


def compute_bcubed_precision(true_labels, pred_labels) -> float:
    if not len(true_labels):
        return 0.0
    true_arr, pred_arr = np.array(true_labels), np.array(pred_labels)
    n = len(true_arr)
    total = 0.0
    for i in range(n):
        same_pred = pred_arr == pred_arr[i]
        same_true_in_pred = true_arr[same_pred] == true_arr[i]
        total += same_true_in_pred.sum() / same_pred.sum()
    return float(total / n)


def compute_bcubed_recall(true_labels, pred_labels) -> float:
    if not len(true_labels):
        return 0.0
    true_arr, pred_arr = np.array(true_labels), np.array(pred_labels)
    n = len(true_arr)
    total = 0.0
    for i in range(n):
        same_true = true_arr == true_arr[i]
        same_pred_in_true = pred_arr[same_true] == pred_arr[i]
        total += same_pred_in_true.sum() / same_true.sum()
    return float(total / n)


def compute_bcubed_f1(true_labels, pred_labels) -> float:
    p = compute_bcubed_precision(true_labels, pred_labels)
    r = compute_bcubed_recall(true_labels, pred_labels)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def compute_all_metrics(true_labels: Sequence, pred_labels: Sequence) -> Dict[str, float]:
    """All partition metrics for one build."""
    return {
        'ari': float(adjusted_rand_score(true_labels, pred_labels)),
        'nmi': float(normalized_mutual_info_score(true_labels, pred_labels)),
        'v_measure': float(v_measure_score(true_labels, pred_labels)),
        'bcubed_precision': compute_bcubed_precision(true_labels, pred_labels),
        'bcubed_recall': compute_bcubed_recall(true_labels, pred_labels),
        'bcubed_f1': compute_bcubed_f1(true_labels, pred_labels),
    }


def evaluate_build(build: Mapping, pred_labels: Sequence) -> Dict[str, float]:
    """Score predicted cluster labels (one per ``build['failures']`` entry, any hashable)."""
    from mfci_bench.data import ground_truth_labels

    truth = ground_truth_labels(build)
    if len(pred_labels) != len(truth):
        raise ValueError(f"{build['build_id']}: {len(pred_labels)} labels for {len(truth)} failures")
    remap: Dict = {}
    pred = [remap.setdefault(p, len(remap)) for p in pred_labels]
    return compute_all_metrics(truth, pred)


def evaluate_builds(builds: Sequence[Mapping], predictions: Mapping[str, Sequence]) -> Dict[str, float]:
    """Macro-average of :func:`evaluate_build` over builds; ``predictions`` maps
    build_id -> labels. Every build must have a prediction."""
    rows: List[Dict[str, float]] = [evaluate_build(b, predictions[b['build_id']]) for b in builds]
    return {m: mean(r[m] for r in rows) for m in METRICS}
