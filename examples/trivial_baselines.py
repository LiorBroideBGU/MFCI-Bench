#!/usr/bin/env python3
"""Score two trivial baselines on the MFCI-Bench eval sets.

* one-cluster   -- all failures of a build in a single cluster
* singletons    -- every failure in its own cluster
* by-exception  -- group failures by exception type (a weak structural heuristic)

Usage:  python examples/trivial_baselines.py
"""

from mfci_bench import DATASETS, evaluate_builds, load_eval_set

BASELINES = {
    'one-cluster': lambda b: [0] * len(b['failures']),
    'singletons': lambda b: list(range(len(b['failures']))),
    'by-exception': lambda b: [f.get('exception_type') or 'Unknown' for f in b['failures']],
}


def main() -> None:
    print(f"{'dataset':<10} {'method':<13} {'ARI':>6} {'NMI':>6} {'B3-P':>6} {'B3-R':>6} {'B3-F1':>6}")
    for ds in DATASETS:
        builds = load_eval_set(ds)
        for name, method in BASELINES.items():
            preds = {b['build_id']: method(b) for b in builds}
            m = evaluate_builds(builds, preds)
            print(f"{ds:<10} {name:<13} {m['ari']:6.3f} {m['nmi']:6.3f} "
                  f"{m['bcubed_precision']:6.3f} {m['bcubed_recall']:6.3f} {m['bcubed_f1']:6.3f}")


if __name__ == '__main__':
    main()
