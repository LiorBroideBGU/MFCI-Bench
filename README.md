# MFCI-Bench: Multi-Fault CI Builds Benchmark

[![DOI](https://img.shields.io/badge/DOI-10.1145%2F3832783.3837467-blue)](https://doi.org/10.1145/3832783.3837467)
[![Code: MIT](https://img.shields.io/badge/code-MIT-green.svg)](LICENSE)
[![Data: upstream licenses](https://img.shields.io/badge/data-upstream%20licenses-lightgrey.svg)](DATA_LICENSES.md)

MFCI-Bench is a benchmark for **test-failure triage in multi-fault CI builds**: given all
failing tests of one CI build, group them so that failures caused by the same fault end
up in the same cluster. Every build is synthesized from 2 to 5 independent real bugs of the
same project, so each failing test has exactly one, correct-by-construction root cause.

It was introduced in:

> Lior Broide, Argaman Mordoch, and Roni Stern. 2026. **HyTri: Hybrid Triage of CI Failures
> via LLM Guided Semantic Reasoning and Change Attribution.** In *Proceedings of the 41st
> IEEE/ACM International Conference on Automated Software Engineering (ASE '26)*, Munich,
> Germany. https://doi.org/10.1145/3832783.3837467

## Why

No public benchmark existed for multi-fault test-failure triage. The closest prior work,
BuildSheriff (Zhang et al., ICSE 2022), evaluated on 200 manually labeled CI builds that were
not released, and 78.5% of those builds contained a single fault, so the trivial "put
everything in one cluster" baseline is competitive there. MFCI-Bench provides builds that are
always multi-fault, with labels that need no manual annotation.

## Construction and guarantees

Built from three established single-fault datasets: **Defects4J**, **Bears** and **BugSwarm**
(all Java). For Bears and BugSwarm, failure artifacts and diffs come from the datasets'
metadata. For Defects4J, every buggy version was checked out, its full test suite was run to
collect failing tests, stack traces, exception types and messages, and line-level fix diffs
were extracted.

A synthesized build combines k ∈ {2, 3, 4, 5} bugs such that:

* all bugs come from the **same project**;
* each bug has **at least two failing tests** in its original single-fault version;
* **disjoint changed files**: no source file is modified by more than one component bug;
* **disjoint failing tests**: no test fails because of more than one component bug.

The build carries the union of the component bugs' failures, changed files and line-level
diffs, so change-aware methods can use the code change exactly as in a real CI build. Under
the two disjointness constraints, the ground-truth partition (each failure → the bug that
caused it) is correct by construction. All of these invariants are checked by
`tests/test_eval_sets.py`.

**Difficulty.** For each pair of bugs the similarity is
`0.3·package + 0.4·exception + 0.3·frame`, where each term is a Jaccard similarity over,
respectively, the Java package prefixes (including parents) of the changed files, the
normalized exception types, and the top-10 stack frames normalized to `Class.method`.
A build's score is the mean over its C(k, 2) bug pairs; builds are **easy** (< 0.1),
**medium** (0.1 to < 0.3) or **hard** (≥ 0.3). See `mfci_bench/difficulty.py`.

## Statistics

Full corpora: **5,162** (Defects4J), **12,856** (Bears) and **4,139** (BugSwarm) builds.
The paper evaluates on a random sample of **150 builds per dataset (450 in total)**, drawn with
seed 42; those exact builds are in `data/eval/`.

| | Defects4J | Bears | BugSwarm | Total |
|---|---:|---:|---:|---:|
| Builds (eval set) | 150 | 150 | 150 | 450 |
| Projects (full corpus) | 17 | 11 | 8 | 36 |
| Projects (eval set) | 14 | 2 | 5 | 21 |
| Total failures | 1,787 | 6,003 | 3,514 | 11,304 |
| Failures / build (median) | 8 | 15 | 16 | 14 |
| Failures / build (max) | 48 | 152 | 114 | 152 |
| Faults / build (mean) | 3.0 | 4.5 | 4.1 | 3.9 |
| k = 2 | 45 | 1 | 12 | 58 |
| k = 3 | 74 | 10 | 26 | 110 |
| k = 4 | 19 | 47 | 49 | 115 |
| k = 5 | 12 | 92 | 63 | 167 |
| Difficulty easy / medium / hard (eval set) | 1 / 48 / 101 | 4 / 121 / 25 | 65 / 74 / 11 | 70 / 243 / 137 |
| Difficulty easy / medium / hard (full corpus) | 82 / 1,839 / 3,241 | 186 / 10,698 / 1,972 | 1,797 / 1,983 / 359 | |

Run `python scripts/benchmark_stats.py` to recompute these numbers from the shipped files.
The datasets are complementary: Defects4J has deep, informative stack traces; Bears is
dominated by assertion failures with one-frame traces whose file is reported as `Unknown`,
so stack-trace methods have little to work with; BugSwarm combines deep traces with rich
diffs.

### Reproducibility notes

* The paper's table reports "Projects" as 17 / 11 / 8; these are the project counts of the
  **full corpora**. The 150-build eval samples cover 14 / 2 / 5 projects (Bears and BugSwarm
  corpora are dominated by a few projects with many bugs).
* The paper's stack-trace rows (median frame depth 20 / 1 / 13; shallow stacks ≤ 3 frames
  0.6% / 100% / 15.4%; empty/Unknown file frames 1.9% / 99.7% / 0.0%) were produced by an
  analysis script that is not part of this release. Recomputed from the shipped `frames`
  field they are 20 / 1 / 10, 0.3% / 100% / 14.9% and 0.0% / 99.2% / 0.0%. All counts
  (builds, failures, per-build median/max, fault distribution) match exactly.
* The generator is configured with a 20/40/40 easy/medium/hard target, but with the paper
  setting (`max_builds=None`, keep every valid combination) that target does not constrain
  the corpus, and the eval set is a uniform random sample of the corpus. The resulting
  difficulty mixes are given in the table above. Use `mfci-sample --mix ...` (below) for a
  stratified sample.

## Data tiers

| Tier | Where | Size | What it is |
|---|---|---|---|
| 1. Eval set | `data/eval/<dataset>.jsonl.gz` (in repo) | 1.3–5.6 MB each | The exact 450 builds used in the paper, failures inline |
| 2. Manifests | `data/manifests/<dataset>.jsonl.gz` (in repo) | 94–286 KB each | One row per build of the full corpus: `index, build_id, project, num_bugs, num_failures, difficulty, similarity_score, bug_ids` |
| 3. Full corpora | [GitHub release v1.0.0](https://github.com/LiorBroideBGU/MFCI-Bench/releases/tag/v1.0.0) | 19 MB compressed (≈ 42 GB uncompressed) | `synthetic_builds.jsonl` and `failure_instances_multifault.jsonl` per dataset, as used in the paper |
| 4. Sources | `data/sources/<dataset>/` (in repo) | 6.5 MB | The single-fault inputs; any build, or the whole corpus, can be rebuilt from them |

The full-corpus summaries produced at generation time are in `data/summaries/`.

### Release assets (tier 3)

Compressed with `zstd -19 --long=31`; decompress with `zstd -d --long=31 FILE` (the long
window needs the flag), or let the download script do it:

```bash
python scripts/download_full.py                  # builds for all datasets -> data/full/<dataset>/
python scripts/download_full.py bears --failures # also the flattened failure file
```

| Asset | Compressed (bytes) | Uncompressed (bytes) |
|---|---:|---:|
| `defects4j_synthetic_builds.jsonl.zst` | 1,361,771 | 1,134,643,231 |
| `defects4j_failure_instances_multifault.jsonl.zst` | 1,641,955 | 2,580,504,132 |
| `bears_synthetic_builds.jsonl.zst` | 4,023,460 | 5,651,427,118 |
| `bears_failure_instances_multifault.jsonl.zst` | 10,085,286 | 29,960,927,720 |
| `bugswarm_synthetic_builds.jsonl.zst` | 831,919 | 780,909,744 |
| `bugswarm_failure_instances_multifault.jsonl.zst` | 1,354,519 | 1,903,437,209 |

SHA-256 of the compressed assets (also in the release's `SHA256SUMS`):

```
ac5cef310fa9d104ce777290ee5cf45e9622bee58b0ff1a2fddde5c5f228e300  defects4j_synthetic_builds.jsonl.zst
545b6330c7e0c9d0c5e87a10f677604538651983e8cad05f2b522dd8a8e1b38c  defects4j_failure_instances_multifault.jsonl.zst
07e63739662c0c112d30d9f6e8c16da8a8fbcd2800877dd35d14948eaea19b51  bears_synthetic_builds.jsonl.zst
5d77061a9fe7196450a7d9114f2b5b111dd4e64da98978cbc050b31bd53b9a85  bears_failure_instances_multifault.jsonl.zst
23dd0367f33a8004e5637632cbccb1fd6e73fea6de1cde58613f35b9c7a7651b  bugswarm_synthetic_builds.jsonl.zst
eaecd0794343790fdc5bf54bad904548287d93abe52120bf7ffcedf2a4b51e39  bugswarm_failure_instances_multifault.jsonl.zst
```

`failure_instances_multifault.jsonl` is a denormalized view of `synthetic_builds.jsonl` (one
row per failure, with the build's diffs repeated on every row). It is shipped for
convenience; `mfci_bench.generate.to_failure_instances(build)` derives the same rows.
You can stream the `.zst` files without decompressing them to disk:
`mfci_bench.iter_corpus("data/full/bears/synthetic_builds.jsonl.zst")` (needs the `zstd` CLI).

## Install

Requires Python ≥ 3.10. Clone the repository (the data lives in it) and install in
editable mode:

```bash
git clone https://github.com/LiorBroideBGU/MFCI-Bench.git
cd MFCI-Bench
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest                                    # 15 tests, a few seconds
```

Runtime dependencies are `numpy` and `scikit-learn` (for the metrics). If you install the
package elsewhere, point `MFCI_BENCH_DATA` at the repository's `data/` directory.

## Quickstart

```python
from mfci_bench import load_eval_set, evaluate_builds

builds = load_eval_set("bears")          # 150 builds, as evaluated in the paper
b = builds[0]
print(b["build_id"], b["project"], b["num_bugs"], len(b["failures"]))

def my_triage(build):                    # return one cluster label per failure
    return [f["exception_type"] for f in build["failures"]]

preds = {b["build_id"]: my_triage(b) for b in builds}
print(evaluate_builds(builds, preds))    # macro-averaged ARI, NMI, V-measure, B³ P/R/F1
```

What a method may use: everything in a failure record except the label fields
(`ground_truth_bug`, `ground_truth`, `bug_id`, and the per-build `component_bugs`), plus
the build-level `combined_changed_files`, `combined_file_diffs` and `combined_diff_stats`,
which play the role of the CI build's code change. Note that a failure's own
`changed_files` / `file_diffs` / `diff_stats` are those of its component bug and therefore
leak the label; use the `combined_*` build fields instead.

A runnable example with three trivial baselines:

```
$ python examples/trivial_baselines.py
dataset    method           ARI    NMI   B3-P   B3-R  B3-F1
defects4j  one-cluster    0.000  0.000  0.430  1.000  0.592
defects4j  singletons     0.000  0.599  1.000  0.330  0.480
defects4j  by-exception   0.398  0.560  0.727  0.844  0.759
bears      one-cluster    0.000  0.000  0.378  1.000  0.514
bears      singletons     0.000  0.594  1.000  0.276  0.412
bears      by-exception   0.262  0.493  0.611  0.783  0.647
bugswarm   one-cluster    0.000  0.000  0.371  1.000  0.524
bugswarm   singletons     0.000  0.585  1.000  0.252  0.388
bugswarm   by-exception   0.777  0.860  0.858  0.960  0.900
```

## Evaluation protocol

As in the paper, each build is scored independently and the scores are averaged over the
builds of a dataset (macro average): adjusted Rand index (ARI), normalized mutual
information (NMI), and B-cubed precision / recall / F1 (Amigó et al., 2009). ARI and NMI come
from scikit-learn; B³ is implemented in `mfci_bench/metrics.py`. Report per-dataset results
on the 150-build eval sets; the paper also reports the 450-build total.

## Data schema

Each line of `data/eval/<dataset>.jsonl.gz` is one build. On disk, the per-failure fields
`changed_files`, `file_diffs` and `diff_stats` are deduplicated into a per-build `_shared`
list; `load_eval_set` restores them, and the result is identical to the paper's records
(checked when the files were written). A real record (Defects4J, trimmed with `…`):

```json
{
  "build_id": "synthetic_defects4j_0520",
  "project": "Jsoup",
  "num_bugs": 2,
  "num_failures": 4,
  "difficulty": "hard",
  "similarity_score": 0.30681818181818177,
  "component_bugs": [
    {
      "bug_id": "Jsoup-40",
      "num_failures": 2,
      "changed_files": ["src/main/java/org/jsoup/nodes/DocumentType.java", "…"],
      "file_diffs": {"src/main/java/org/jsoup/nodes/DocumentType.java": "diff --git a/src/main/java/org/jsoup/nodes/DocumentType.java …"},
      "diff_stats": {"additions": 3, "deletions": 20},
      "ground_truth": {"root_cause_id": "Jsoup-40", "changed_files": ["…"]},
      "exception_types": ["IllegalArgumentException"],
      "packages": ["org.jsoup.nodes", "org.jsoup.parser"]
    },
    "…"
  ],
  "combined_changed_files": ["src/main/java/org/jsoup/nodes/DocumentType.java", "src/main/java/org/jsoup/nodes/Element.java", "…"],
  "combined_file_diffs": {"src/main/java/org/jsoup/nodes/DocumentType.java": "diff --git …", "…": "…"},
  "combined_diff_stats": {"additions": 4, "deletions": 41},
  "failures": [
    {
      "build_id": "defects4j_Jsoup_40",
      "failure_id": "defects4j_Jsoup_40::failure_0",
      "test_name": "org.jsoup.nodes.DocumentTypeTest::constructorValidationOkWithBlankName",
      "exception_type": "IllegalArgumentException",
      "exception_message": "String must not be empty",
      "stack_trace": "java.lang.IllegalArgumentException: String must not be empty\n\tat org.jsoup.helper.Validate…",
      "frames": [
        {"file": "Validate.java", "line": 92, "func": "Validate.notEmpty"},
        {"file": "DocumentType.java", "line": 22, "func": "DocumentType.<init>"},
        "…"
      ],
      "stderr": "", "stdout": "",
      "project": "Jsoup",
      "bug_id": "Jsoup-40",
      "timestamp": "2026-01-19T02:07:46.271236",
      "changed_files": ["…"], "file_diffs": {"…": "…"}, "diff_stats": {"additions": 3, "deletions": 20},
      "ground_truth": {"root_cause_id": "Jsoup-40", "changed_files": ["…"]},
      "language": "java",
      "original_build_id": "defects4j_Jsoup_40",
      "synthetic_build_id": "synthetic_defects4j_0520",
      "ground_truth_bug": "Jsoup-40"
    },
    "…"
  ],
  "created_at": "2026-02-05T21:11:21.568974"
}
```

Key fields: `ground_truth_bug` on each failure is the label; `build_id` / `failure_id` on a
failure refer to the original single-fault run, `synthetic_build_id` to the MFCI build.
Bears and BugSwarm failures additionally carry dataset-specific `ground_truth` metadata.

## Re-sampling and regenerating

Every build of the full corpora can be rebuilt from `data/sources/` plus its manifest row,
and the rebuilt record equals the paper's record (up to `created_at` and the order of
set-valued lists, which depended on Python's hash seed in the original run; the generator
now emits them sorted).

```bash
# Re-draw the paper's eval set from the manifest + sources (identical to data/eval/bears.jsonl.gz)
mfci-sample bears --n 150 --seed 42 --output out/bears_seed42.jsonl.gz

# Another seed, or a difficulty-stratified sample (extension; not used in the paper)
mfci-sample bears --n 150 --seed 7 --output out/bears_seed7.jsonl.gz
mfci-sample defects4j --n 150 --seed 42 --mix easy=0.2,medium=0.4,hard=0.4 --output out/d4j_strat.jsonl.gz
```

```python
from mfci_bench import sample_builds
builds = sample_builds("bugswarm", n=300, seed=1)                    # uniform
builds = sample_builds("bugswarm", n=300, seed=1, mix={"easy": .2, "medium": .4, "hard": .4})
```

Regenerate a full corpus from the sources (seed 42 reproduces the paper's corpora; the
manifests were verified to be identical for all three datasets):

```bash
mfci-generate defects4j --output-dir out/defects4j                 # ~1.1 GB builds + 2.6 GB failures
mfci-generate bears --output-dir out/bears --no-failure-file       # ~5.7 GB builds
mfci-generate bugswarm --output-dir out/bugswarm --manifest-only   # manifest + summary only, seconds
mfci-generate defects4j --output-dir out/small --max-builds 50 --seed 1   # small corpus, 20/40/40 target
```

Options: `--seed`, `--max-builds` (target size; the difficulty mix is applied only when
this is set), `--mix`, `--min-bugs` / `--max-bugs` (k range), `--manifest-only`,
`--no-failure-file`. Note the per-dataset differences inherited from the paper's
generators: Defects4J caps each project at 500 valid combinations and samples (rather than
enumerates) projects with more than 50 eligible bugs; Bears and BugSwarm enumerate all
combinations.

**Collecting the single-fault sources** from the upstream datasets again requires Docker
and network access; the original collection scripts are in `collection/` for provenance
(`run_docker_defects4j.sh` + `collect_defects4j_v3.py`, `collect_bears.py`,
`collect_bugswarm.py` + `Dockerfile.bugswarm`). They were not re-run for this release.

## Repository layout

```
mfci_bench/          library: sources.py (load single-fault data), generate.py (synthesis),
                     difficulty.py (scoring), data.py (eval sets, manifests, sampling),
                     metrics.py (ARI/NMI/B³), compare.py, cli.py
scripts/             benchmark_stats.py, download_full.py
examples/            trivial_baselines.py
tests/               test_eval_sets.py
collection/          original upstream-collection scripts (provenance only)
data/eval/           the 450 paper eval builds
data/manifests/      full-corpus manifests
data/sources/        single-fault inputs
data/summaries/      full-corpus generation summaries
```

## Scope and limitations

* Java only (Defects4J, Bears, BugSwarm).
* The disjointness constraints that make the labels unambiguous also make the builds
  cleaner than real CI builds, where several faults may touch the same file or make the same
  test fail.
* The paper additionally evaluated on the Defects4J multi-fault dataset of
  [coinse/Defects4J-multifault](https://github.com/coinse/Defects4J-multifault) ("transplant"
  experiment, multi-label ground truth). That dataset is not part of MFCI-Bench and is not
  redistributed here; obtain it from its authors.

## Citation

If you use MFCI-Bench, please cite the paper (also in `CITATION.bib` / `CITATION.cff`):

```bibtex
@inproceedings{broide2026hytri,
  title={HyTri: Hybrid Triage of CI Failures via LLM Guided Semantic Reasoning and Change Attribution},
  author={Broide, Lior and Mordoch, Argaman and Stern, Roni},
  booktitle={Proceedings of the 41st IEEE/ACM International Conference on Automated Software Engineering},
  pages={2165--2176},
  year={2026}
}
```

and the upstream datasets Defects4J, Bears and BugSwarm (BibTeX in
[DATA_LICENSES.md](DATA_LICENSES.md)).

## License

* Code: MIT ([LICENSE](LICENSE)).
* Data: derived from Defects4J (MIT), Bears (GPL-3.0) and BugSwarm (BSD-3-Clause) and
  distributed under those licenses; code fragments inside the records remain under their
  projects' licenses. See [DATA_LICENSES.md](DATA_LICENSES.md).
* The paper is published under CC BY 4.0.

## Acknowledgements

This research was supported by a grant from the Israeli Ministry of Science and Technology
(MOST). We thank the authors of Defects4J, Bears and BugSwarm for making their datasets
available.
