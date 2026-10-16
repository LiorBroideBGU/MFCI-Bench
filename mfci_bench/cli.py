"""Command-line entry points: ``mfci-generate`` and ``mfci-sample``."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from mfci_bench.data import data_root, save_jsonl_gz
from mfci_bench.sources import DATASETS


def _parse_mix(text):
    if not text:
        return None
    mix = {}
    for part in text.split(','):
        k, v = part.split('=')
        mix[k.strip()] = float(v)
    if set(mix) != {'easy', 'medium', 'hard'}:
        raise argparse.ArgumentTypeError("mix must name easy, medium and hard, e.g. easy=0.2,medium=0.4,hard=0.4")
    return mix


def generate_main(argv=None) -> None:
    from mfci_bench.generate import DEFAULT_DIFFICULTY_MIX, generate

    p = argparse.ArgumentParser(
        prog='mfci-generate',
        description='Synthesize a multi-fault CI corpus from single-fault sources. '
                    'Defaults reproduce the paper corpora (seed 42, all valid combinations).')
    p.add_argument('dataset', choices=DATASETS)
    p.add_argument('--sources', type=Path, default=data_root() / 'sources',
                   help='directory holding <dataset>/ source files (default: data/sources)')
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--max-builds', type=int, default=None,
                   help='target corpus size; None (default) keeps every valid combination. '
                        'When set, the difficulty mix is enforced as far as the data allows.')
    p.add_argument('--mix', type=_parse_mix, default=None,
                   help='difficulty mix used with --max-builds (default easy=0.2,medium=0.4,hard=0.4)')
    p.add_argument('--min-bugs', type=int, default=2)
    p.add_argument('--max-bugs', type=int, default=5)
    p.add_argument('--manifest-only', action='store_true',
                   help='write only manifest.jsonl.gz + dataset_summary.json (no multi-GB JSONL)')
    p.add_argument('--no-failure-file', action='store_true',
                   help='skip failure_instances_multifault.jsonl (derivable from the builds)')
    a = p.parse_args(argv)
    generate(a.dataset, a.sources, a.output_dir, seed=a.seed, max_builds=a.max_builds,
             mix=a.mix or DEFAULT_DIFFICULTY_MIX, min_bugs=a.min_bugs, max_bugs=a.max_bugs,
             write_builds=not a.manifest_only,
             write_failures=not (a.manifest_only or a.no_failure_file))


def sample_main(argv=None) -> None:
    from mfci_bench.data import sample_builds

    p = argparse.ArgumentParser(
        prog='mfci-sample',
        description='Sample builds from a full corpus manifest and rebuild them from sources. '
                    '`--n 150 --seed 42` without --mix reproduces the paper eval set.')
    p.add_argument('dataset', choices=DATASETS)
    p.add_argument('--n', type=int, default=150)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--mix', type=_parse_mix, default=None,
                   help='stratify by difficulty, e.g. easy=0.2,medium=0.4,hard=0.4 (default: uniform, as in the paper)')
    p.add_argument('--output', type=Path, required=True, help='output .jsonl.gz')
    a = p.parse_args(argv)
    builds = sample_builds(a.dataset, a.n, a.seed, a.mix)
    save_jsonl_gz(builds, a.output, compact=True)
    print(json.dumps({
        'dataset': a.dataset, 'builds': len(builds),
        'failures': sum(b['num_failures'] for b in builds),
        'difficulty': dict(Counter(b['difficulty'] for b in builds)),
        'k': dict(sorted(Counter(b['num_bugs'] for b in builds).items())),
        'output': str(a.output),
    }, indent=2))
