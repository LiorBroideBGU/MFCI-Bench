#!/usr/bin/env python3
"""Recompute the paper's statistics table (tab:benchmark) from the shipped eval sets."""

from __future__ import annotations

import statistics
from collections import Counter

from mfci_bench import DATASETS, load_eval_set

PAPER = {  # values printed in the ASE 2026 paper, Table "MFCI-Bench statistics"
    'defects4j': dict(builds=150, failures=1787, med=8, max=48, mean_k=3.0, depth=20,
                      shallow=0.6, unknown=1.9, k={2: 45, 3: 74, 4: 19, 5: 12}),
    'bears': dict(builds=150, failures=6003, med=15, max=152, mean_k=4.5, depth=1,
                  shallow=100.0, unknown=99.7, k={2: 1, 3: 10, 4: 47, 5: 92}),
    'bugswarm': dict(builds=150, failures=3514, med=16, max=114, mean_k=4.1, depth=13,
                     shallow=15.4, unknown=0.0, k={2: 12, 3: 26, 4: 49, 5: 63}),
}


def stats(builds):
    failures = [f for b in builds for f in b['failures']]
    per_build = [len(b['failures']) for b in builds]
    depths = [len(f.get('frames') or []) for f in failures]
    frames = [fr for f in failures for fr in (f.get('frames') or [])]
    unknown = sum(1 for fr in frames if not fr.get('file') or fr.get('file') == 'Unknown')
    return dict(
        builds=len(builds),
        projects=len({b['project'] for b in builds}),
        failures=len(failures),
        med=statistics.median(per_build),
        max=max(per_build),
        mean_k=round(statistics.mean(b['num_bugs'] for b in builds), 2),
        depth=statistics.median(depths),
        shallow=round(100 * sum(d <= 3 for d in depths) / len(depths), 1),
        unknown=round(100 * unknown / len(frames), 1) if frames else 0.0,
        k=dict(sorted(Counter(b['num_bugs'] for b in builds).items())),
        difficulty=dict(Counter(b['difficulty'] for b in builds)),
    )


def main() -> None:
    for ds in DATASETS:
        s = stats(load_eval_set(ds))
        print(f"== {ds}")
        for key, val in s.items():
            ref = PAPER[ds].get(key)
            mark = '' if ref is None else ('  (paper: %s)' % ref if ref != val and not
                                           (isinstance(ref, float) and abs(ref - val) < 0.051) else '  ok')
            print(f"  {key:<11} {val}{mark}")


if __name__ == '__main__':
    main()
