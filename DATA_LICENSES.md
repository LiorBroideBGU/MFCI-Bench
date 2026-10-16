# Data licenses and upstream credits

The **code** in this repository is MIT-licensed (see `LICENSE`). The **data** under
`data/` and the release assets are derived from three public bug datasets and are
redistributed under the terms of those datasets. If you use MFCI-Bench, please also cite
the upstream datasets.

| Data | Derived from | Upstream license (as declared in the upstream repository, checked 2026-10-16) |
|---|---|---|
| `data/sources/defects4j/`, `data/eval/defects4j.jsonl.gz`, `data/manifests/defects4j.jsonl.gz`, release `defects4j_*` | [Defects4J](https://github.com/rjust/defects4j) (Just, Jalali, Ernst, ISSTA 2014) | MIT |
| `data/sources/bears/`, `data/eval/bears.jsonl.gz`, `data/manifests/bears.jsonl.gz`, release `bears_*` | [Bears](https://github.com/bears-bugs/bears-benchmark) (Madeiral et al., SANER 2019) | GPL-3.0 |
| `data/sources/bugswarm/`, `data/eval/bugswarm.jsonl.gz`, `data/manifests/bugswarm.jsonl.gz`, release `bugswarm_*` | [BugSwarm](https://github.com/BugSwarm/bugswarm) (Tomassi et al., ICSE 2019) | BSD-3-Clause |

What was derived, and how:

* **Defects4J.** Each buggy version was checked out and its full test suite executed to
  collect failing tests, stack traces, exception types and messages; line-level fix diffs
  were extracted from the VCS (`collection/collect_defects4j_v3.py`).
* **Bears / BugSwarm.** Failure artifacts (failing tests, logs, stack traces) and diffs were
  taken from the datasets' published metadata and the referenced GitHub commits
  (`collection/collect_bears.py`, `collection/collect_bugswarm.py`).

The records also contain fragments of the subject programs (file paths, test names,
stack-trace text and source-code diffs) from the open-source projects packaged by those
datasets (e.g. Apache Commons, Closure Compiler, Jackson, Jsoup, Spoon, MATSim, Traccar).
Those fragments remain under their projects' own licenses. Some diffs and traces contain
author e-mail addresses or file-system paths that were present in the upstream projects
or CI logs (for example `@author` tags and `/home/travis/...` paths); they are kept
verbatim so that the data stays byte-identical to what was evaluated in the paper.

## Upstream citations

```bibtex
@inproceedings{just2014defects4j,
  author    = {Just, Ren{\'e} and Jalali, Darioush and Ernst, Michael D.},
  title     = {{Defects4J}: A Database of Existing Faults to Enable Controlled Testing Studies for {Java} Programs},
  booktitle = {Proceedings of the 2014 International Symposium on Software Testing and Analysis (ISSTA)},
  year      = {2014},
  pages     = {437--440},
  doi       = {10.1145/2610384.2628055}
}

@inproceedings{madeiral2019bears,
  author    = {Madeiral, Fernanda and Urli, Simon and Maia, Marcelo and Monperrus, Martin},
  title     = {{Bears}: An Extensible {Java} Bug Benchmark for Automatic Program Repair Studies},
  booktitle = {Proceedings of the 26th IEEE International Conference on Software Analysis, Evolution and Reengineering (SANER)},
  year      = {2019},
  pages     = {468--478},
  doi       = {10.1109/SANER.2019.8667991}
}

@inproceedings{tomassi2019bugswarm,
  author    = {Tomassi, David A. and Dmeiri, Naji and Wang, Yichen and Bhowmick, Antara and Liu, Yen-Chuan and Devanbu, Premkumar T. and Vasilescu, Bogdan and Rubio-Gonz{\'a}lez, Cindy},
  title     = {{BugSwarm}: Mining and Continuously Growing a Dataset of Reproducible Failures and Fixes},
  booktitle = {Proceedings of the 41st International Conference on Software Engineering (ICSE)},
  year      = {2019},
  pages     = {339--349},
  doi       = {10.1109/ICSE.2019.00048}
}
```
