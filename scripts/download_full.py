#!/usr/bin/env python3
"""Download, verify and decompress the full MFCI-Bench corpora (GitHub release v1.0.0).

    python scripts/download_full.py                     # all three datasets, builds only
    python scripts/download_full.py bears --failures    # also the flattened failure files
    python scripts/download_full.py --keep-compressed   # do not decompress

Decompressed sizes: Defects4J 1.1 GB, BugSwarm 0.8 GB, Bears 5.7 GB of builds; the optional
failure files add 2.6 / 1.9 / 30.0 GB. You can also stream the .zst files directly with
``mfci_bench.iter_corpus(path)`` without decompressing to disk.

Decompression uses the ``zstd`` CLI (``--long=31``) or, if absent, the ``zstandard``
Python package (``pip install zstandard``).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/LiorBroideBGU/MFCI-Bench/releases/download/v1.0.0/"

# file -> (sha256 of .zst asset, sha256 of decompressed file)
ASSETS = {
    "defects4j_synthetic_builds.jsonl.zst": (
        "ac5cef310fa9d104ce777290ee5cf45e9622bee58b0ff1a2fddde5c5f228e300",
        "b30d78c3a4b04caf99e9a2c25e5e5f88f788e674cf17af25d47a814062530c2c"),
    "defects4j_failure_instances_multifault.jsonl.zst": (
        "545b6330c7e0c9d0c5e87a10f677604538651983e8cad05f2b522dd8a8e1b38c",
        "909f285e119ea99017a1da580230ae2e6bc39f0498c171ca923fc4330038fc7d"),
    "bears_synthetic_builds.jsonl.zst": (
        "07e63739662c0c112d30d9f6e8c16da8a8fbcd2800877dd35d14948eaea19b51",
        "026a3aa1bc608f4d7044ab8e3024fe88724271fd678eb99fb106a217d8b1facb"),
    "bears_failure_instances_multifault.jsonl.zst": (
        "5d77061a9fe7196450a7d9114f2b5b111dd4e64da98978cbc050b31bd53b9a85",
        "4b50a28cf1a42fa047df0535d5397fb6011b8220a3d413c68821708168d81e56"),
    "bugswarm_synthetic_builds.jsonl.zst": (
        "23dd0367f33a8004e5637632cbccb1fd6e73fea6de1cde58613f35b9c7a7651b",
        "8b3742edf2cb16db8f61c15774e464bf63949ec13b0d30b564a10334057fbaac"),
    "bugswarm_failure_instances_multifault.jsonl.zst": (
        "eaecd0794343790fdc5bf54bad904548287d93abe52120bf7ffcedf2a4b51e39",
        "6ec3c4cfdb9ad3a7003fef04c14aa0c3bca86e00e95cac7fe321d5f1e2c55f0d"),
}
DATASETS = ("defects4j", "bears", "bugswarm")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decompress(src: Path, dst: Path) -> None:
    if shutil.which("zstd"):
        subprocess.run(["zstd", "-d", "--long=31", "-q", "-f", str(src), "-o", str(dst)], check=True)
        return
    try:
        import zstandard
    except ImportError:
        sys.exit("need the `zstd` CLI or `pip install zstandard` to decompress")
    dctx = zstandard.ZstdDecompressor(max_window_size=2 ** 31)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        dctx.copy_stream(fi, fo)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("datasets", nargs="*", choices=DATASETS, default=list(DATASETS))
    p.add_argument("--out", type=Path, default=Path("data/full"))
    p.add_argument("--failures", action="store_true", help="also fetch failure_instances_multifault")
    p.add_argument("--keep-compressed", action="store_true", help="skip decompression")
    a = p.parse_args()

    for ds in a.datasets or DATASETS:
        kinds = ["synthetic_builds"] + (["failure_instances_multifault"] if a.failures else [])
        for kind in kinds:
            name = f"{ds}_{kind}.jsonl.zst"
            zsha, rawsha = ASSETS[name]
            target_dir = a.out / ds
            target_dir.mkdir(parents=True, exist_ok=True)
            zpath = target_dir / f"{kind}.jsonl.zst"
            if not (zpath.exists() and sha256(zpath) == zsha):
                print(f"downloading {name} ...")
                urllib.request.urlretrieve(BASE + name, zpath)
            if sha256(zpath) != zsha:
                sys.exit(f"checksum mismatch for {zpath}")
            print(f"  {zpath} sha256 OK")
            if a.keep_compressed:
                continue
            raw = target_dir / f"{kind}.jsonl"
            print(f"  decompressing to {raw} ...")
            decompress(zpath, raw)
            if sha256(raw) != rawsha:
                sys.exit(f"checksum mismatch for {raw}")
            print(f"  {raw} sha256 OK")


if __name__ == "__main__":
    main()
