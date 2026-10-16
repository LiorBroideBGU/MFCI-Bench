"""MFCI-Bench: the Multi-Fault CI Builds Benchmark (Broide, Mordoch, Stern, ASE 2026)."""

from mfci_bench.data import (
    data_root,
    expand_build,
    ground_truth_labels,
    iter_corpus,
    load_eval_set,
    load_manifest,
    materialize,
    sample_builds,
    sample_indices,
    sample_stratified_indices,
)
from mfci_bench.metrics import compute_all_metrics, evaluate_build, evaluate_builds
from mfci_bench.sources import DATASETS

__version__ = "1.0.0"

__all__ = [
    "DATASETS",
    "data_root",
    "load_eval_set",
    "load_manifest",
    "iter_corpus",
    "sample_builds",
    "sample_indices",
    "sample_stratified_indices",
    "materialize",
    "expand_build",
    "ground_truth_labels",
    "compute_all_metrics",
    "evaluate_build",
    "evaluate_builds",
]
