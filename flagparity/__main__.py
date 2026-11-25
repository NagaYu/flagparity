"""CLI.

  python3 -I -m flagparity check FILE... [--root DIR] [--out OUT.json]
  python3 -I -m flagparity request REQUEST.json [--out OUT.json]

`request` takes the versioned request schema flagparity.request/v1:
  {"schema": "flagparity.request/v1", "files": [{"path": "...", "content": "<utf-8 text>"}]}
Path labels in the output are relative to --root (default: current directory).
"""
import json
import os
import sys

from . import INPUT_SCHEMA
from .core import check_files, dumps


def main(argv):
    if len(argv) < 2 or argv[0] not in ("check", "request"):
        sys.stderr.write(__doc__)
        return 2
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    root = "."
    if "--root" in argv:
        i = argv.index("--root")
        root = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if argv[0] == "check":
        items = []
        for p in argv[1:]:
            with open(p, "rb") as fh:
                items.append((os.path.relpath(p, root), fh.read()))
    else:
        with open(argv[1], encoding="utf-8") as fh:
            req = json.load(fh)
        if req.get("schema") != INPUT_SCHEMA:
            sys.stderr.write("unsupported request schema %r\n" % req.get("schema"))
            return 2
        items = [(f["path"], f["content"].encode("utf-8")) for f in req["files"]]
    text = dumps(check_files(items))
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
