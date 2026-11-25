"""Fetch the third-party files that are not shipped with this export (see THIRD_PARTY.md).

  python3 -I scripts/fetch_third_party.py [--only PREFIX] [--dry-run]

Reads third_party_manifest.json, downloads each file from its URL at the pinned commit, checks its sha256 and writes
it to `dest`. A file whose bytes do not match is not written. Downloaded files are data: nothing here executes them.
After fetching smoke/census/files/, rebuild the dev bench files with:
  python3 bench/build.py && python3 bench/manual_cases.py
"""
import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else ""
    dry = "--dry-run" in argv
    man = json.load(open(os.path.join(ROOT, "third_party_manifest.json"), encoding="utf-8"))
    ok = bad = skipped = 0
    for f in man["files"]:
        if not f["dest"].startswith(only):
            continue
        dest = os.path.join(ROOT, f["dest"])
        if os.path.exists(dest) and hashlib.sha256(open(dest, "rb").read()).hexdigest() == f["sha256"]:
            skipped += 1
            continue
        if dry:
            print("would fetch", f["url"], "->", f["dest"])
            continue
        try:
            req = urllib.request.Request(f["url"], headers={"User-Agent": "flagparity-fetch"})
            data = urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:  # noqa: BLE001
            print("FAIL", f["url"], e)
            bad += 1
            continue
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            print("SHA256 MISMATCH (not written)", f["url"])
            bad += 1
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        ok += 1
    print("fetched", ok, "already present", skipped, "failed", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
