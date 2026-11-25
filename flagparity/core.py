"""Verifier core: bytes in, versioned verdict JSON out. Stateless and deterministic (SaaS-ready seam):
no clock, no network, no filesystem access beyond the bundled fidelity table; output depends only on
(path label, bytes) of each input file.
"""
import hashlib
import json
import os

from . import OUTPUT_SCHEMA, TOOL_VERSION
from . import semantics as S
from . import yaml12
from .classes import check_all, fidelity
from .contexts import DESCRIPTION as D6

GATE_CLASSES = ("F1", "F2", "F3", "F4", "F7")


def identify(path, data):
    """DECISIONS.md D-1 (+Z-1, Z-3). Returns (format | None, parsed | None, reason)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, "not UTF-8 text"
    if ext == ".json":
        try:
            doc = json.loads(text)
        except ValueError as e:
            return None, None, "unparseable JSON: %s" % str(e)[:80]
        if isinstance(doc, dict) and isinstance(doc.get("flags"), dict):
            for f in doc["flags"].values():
                if isinstance(f, dict) and f.get("state") in ("ENABLED", "DISABLED") and \
                        isinstance(f.get("variants"), dict) and "defaultVariant" in f:
                    return "flagd", doc, None
        if isinstance(doc, dict) and isinstance(doc.get("flags"), list):
            return None, None, "out of scope: flagd flags-array form (Z-3)"
        return None, None, "JSON but not a flagd flag definition (D-1)"
    if ext in (".yml", ".yaml"):
        try:
            docs = yaml12.load_all(text)
        except Exception as e:  # noqa: BLE001 - any YAML error means unparseable
            return None, None, "unparseable YAML: %s" % str(e).splitlines()[0][:80]
        for d in docs:
            if isinstance(d, dict) and isinstance(d.get("flags"), list) and \
                    set(d) <= {"version", "namespace", "flags", "segments"}:
                for f in d["flags"]:
                    if isinstance(f, dict) and isinstance(f.get("key"), str) and (
                            f.get("type") in ("VARIANT_FLAG_TYPE", "BOOLEAN_FLAG_TYPE") or
                            isinstance(f.get("variants"), list) or isinstance(f.get("rules"), list) or
                            isinstance(f.get("rollouts"), list)):
                        return "flipt", docs, None
        for d in docs:
            if isinstance(d, dict):
                for v in d.values():
                    if isinstance(v, dict) and isinstance(v.get("variations"), dict) and isinstance(v.get("defaultRule"), dict):
                        return "goff", docs, None
        return None, None, "YAML but neither Flipt nor GO Feature Flag v1 format (D-1)"
    return None, None, "unsupported extension %r" % ext


def _analyze(fmt, parsed):
    if fmt == "flagd":
        from .adapters_flagd import analyze_doc
    elif fmt == "flipt":
        from .adapters_flipt import analyze_doc
    else:
        from .adapters_goff import analyze_doc
    _, models = analyze_doc(parsed)
    return models


def check_file(path, data):
    sha = hashlib.sha256(data).hexdigest()
    out = {"path": path, "sha256": sha}
    fmt, parsed, reason = identify(path, data)
    if fmt is None:
        out.update(status="not-judgeable", reason=reason, format=None, flags=[])
        return out
    out["format"] = fmt
    try:
        models = _analyze(fmt, parsed)
    except RecursionError:
        out.update(status="not-judgeable", reason="definition too deeply nested", flags=[])
        return out
    except Exception as e:  # noqa: BLE001 - never drop a file silently (G1-5); surfaced as internal error
        out.update(status="not-judgeable", reason="internal error: %s: %s" % (type(e).__name__, str(e)[:120]), flags=[])
        return out
    if not models:
        out.update(status="not-judgeable", reason="no flag entries", flags=[])
        return out
    flags = []
    for m in models:
        try:
            classes = check_all(m)
        except Exception as e:  # noqa: BLE001
            classes = {c: {"status": "not-judgeable", "reason": "internal error: %s: %s" % (type(e).__name__, str(e)[:120])}
                       for c in GATE_CLASSES + ("F5",)}
        entry = {"flag": m.key, "classes": classes}
        if m.location:
            entry["location"] = m.location
        if m.notes:
            entry["notes"] = m.notes
        flags.append(entry)
    judged = any(f["classes"][c]["status"] in ("detected", "clean", "not-applicable") for f in flags for c in GATE_CLASSES)
    out["status"] = "judged" if judged else "not-judgeable"
    if not judged:
        out["reason"] = "every flag/class not-judgeable"
    out["semantics"] = [{"id": s.id, "fidelity": fidelity(s.id)} for s in S.for_format(fmt)]
    out["flags"] = flags
    return out


def check_files(items):
    """items: iterable of (path_label, bytes). Returns the verdict document (dict)."""
    files = [check_file(p, d) for p, d in sorted(items, key=lambda x: x[0])]
    summary = {"input_files": len(files),
               "judged": sum(1 for f in files if f["status"] == "judged"),
               "not_judgeable": sum(1 for f in files if f["status"] == "not-judgeable")}
    by = {}
    for f in files:
        for fl in f["flags"]:
            for c, v in fl["classes"].items():
                by.setdefault(c, {}).setdefault(v["status"], 0)
                by[c][v["status"]] += 1
    summary["flag_class_status"] = {c: dict(sorted(v.items())) for c, v in sorted(by.items())}
    return {"schema": OUTPUT_SCHEMA, "tool": {"name": "flagparity", "version": TOOL_VERSION},
            "contexts": D6,
            "semantics": [{"id": s.id, "label": s.label, "fidelity": fidelity(s.id)} for s in S.all_semantics()],
            "files": files, "summary": summary}


def dumps(doc):
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
