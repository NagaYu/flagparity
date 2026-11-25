"""Class checks F1, F2, F3 (redefined), F4, F7 and F5 (info) over a FlagModel.

Every verdict is one of detected / clean / not-applicable / not-judgeable (with reason), DECISIONS P1-C-1.
"""
import itertools
import json
import os

from . import semantics as S
from .contexts import d6_keys, DESCRIPTION as D6

_FID = None


def fidelity_table():
    global _FID
    if _FID is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vectors", "fidelity.json")
        try:
            with open(p, encoding="utf-8") as fh:
                _FID = json.load(fh)["semantics"]
        except (OSError, ValueError):
            _FID = {}
    return _FID


def fidelity(sem_id):
    return fidelity_table().get(sem_id, {}).get("status", "unknown")


def V(status, **kw):
    d = {"status": status}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def check_f1(m):
    if m.disabled:
        return V("not-applicable", reason=m.disabled)
    if m.time_dependent:
        return V("not-judgeable", reason=m.time_dependent)
    if not m.has_conditions:
        return V("not-applicable", reason="no targeting conditions")
    r = m.reach
    explicit = [l for l in m.leaves if l.explicit]
    unreached = [l for l in explicit if l.id not in r.hits]
    if not unreached:
        notes = {e: [l for l in ids if l in {x.id for x in explicit}] for e, ids in (r.engine_unreached or {}).items()}
        notes = {e: v for e, v in notes.items() if v}
        return V("clean", basis="every authored rule/branch has a witness context (%d witness contexts)" % r.n_assignments,
                 engine_note=({"unreachable_only_in": notes, "severity": "info",
                               "why": "reachable in another engine; F1 is reported only when no engine reaches the rule (DECISIONS P3-Z-6 B-3b)"}
                              if notes else None))
    if not r.complete:
        return V("not-judgeable", reason="no witness found for %d rule(s) and the witness set is not complete: %s"
                 % (len(unreached), r.reason or m.f1_nj))
    return V("detected", findings=[{"rule": l.id, "label": l.label,
                                    "why": "no context reaches it: earlier rules capture every context that satisfies its condition, or its condition is unsatisfiable"}
                                   for l in unreached],
             basis="exhaustive over %d representative contexts (complete for the operators used)" % r.n_assignments,
             reproduce="evaluate the flag with any context; the listed rule is never the first match")


def check_f2(m):
    if not m.allocs:
        return V("not-applicable", reason="no allocation (fractional / distributions / percentage)")
    found = []
    nj = []
    for a in m.allocs:
        for f in a.f2:
            g = dict(f)
            g["allocation"] = a.id
            found.append(g)
        if a.f2_nj and not a.f2:
            nj.append("%s: %s" % (a.id, a.f2_nj))
    if found:
        return V("detected", findings=found)
    if nj:
        return V("not-judgeable", reason="; ".join(nj))
    return V("clean", basis="%d allocation(s) checked" % len(m.allocs))


def check_f3(m):
    if m.disabled:
        return V("not-applicable", reason=m.disabled)
    if not m.variants:
        return V("not-applicable", reason="no declared variants (boolean flag)")
    if not m.has_mechanism:
        return V("not-applicable", reason="toggle without rules or allocation (P1-B-1: excluded)")
    if m.time_dependent:
        return V("not-judgeable", reason=m.time_dependent)
    r = m.reach
    hits = r.hits if r else {l.id for l in m.leaves}
    allocs = {a.id: a for a in m.allocs}
    produced, maybe, refs = set(), set(), set()
    dynamic_reached = []

    def outputs(l):
        if l.kind == "variant":
            return {l.variant}
        if l.kind == "alloc":
            a = allocs.get(l.alloc_id)
            out = set(a.positive) if a else set()
            if a and a.default_on_some_semantics and m.default_variant:
                out.add(m.default_variant)
            if a and any(f.get("kind") == "zero-total-weight" for f in a.f2) and m.default_variant:
                out.add(m.default_variant)
            return out
        if l.kind == "default":
            return {m.default_variant} if m.default_variant else set()
        if l.kind == "multi":
            return set(l.produces)
        if l.kind == "boolexpr":
            outs = set((r.outputs or {}).get(l.id, set())) if r else set()
            res = {x for x in outs if x != "\u0000default"}
            if "\u0000default" in outs and m.default_variant:
                res.add(m.default_variant)
            return res
        return set()

    for l in m.leaves:
        o = outputs(l)
        if l.kind in ("variant", "multi"):
            refs |= o
        if l.kind == "alloc" and l.alloc_id in allocs:
            refs |= {e[0] for e in allocs[l.alloc_id].entries if isinstance(e[0], str)}
        if l.id in hits:
            produced |= o
            if l.kind == "dynamic":
                dynamic_reached.append(l.label)
            if l.kind == "boolexpr" and not (r and r.complete):
                maybe |= {"true", "false"} | ({m.default_variant} if m.default_variant else set())
        elif not (r and r.complete):
            maybe |= o
            if l.kind == "dynamic":
                dynamic_reached.append(l.label)
    if dynamic_reached:
        return V("not-judgeable", reason="variant computed at evaluation time: %s" % dynamic_reached[0])
    if m.format == "flagd" and m.default_variant:
        refs.add(m.default_variant)  # P1-B-1 sub-case: a default naming an undeclared variant (flagd rejects it at load)
    undefined = sorted(x for x in refs if x not in m.variants and not x.startswith("<"))
    ghosts = [v for v in m.variants if v not in produced]
    definite = [v for v in ghosts if v not in maybe]
    findings = [{"variant": v, "why": "no reachable rule, positive-weight allocation or default produces it"} for v in definite]
    findings += [{"undefined_variant_referenced": x, "why": "a rule/allocation names a variant that is not declared"} for x in undefined]
    if findings:
        return V("detected", findings=findings,
                 basis="produced by reachable paths: %s" % sorted(produced))
    if ghosts:
        return V("not-judgeable", reason="variants %s are produced only by rules whose reachability is undecided: %s"
                 % (ghosts, r.reason if r else ""))
    return V("clean", basis="every declared variant is produced by a reachable path")


def check_f4(m):
    if m.disabled:
        return V("not-applicable", reason=m.disabled)
    sems = S.for_format(m.format)
    allocs_eval = [a for a in m.allocs if a.evaluated]
    if not allocs_eval:
        return V("not-applicable", reason="no evaluated allocation to bucket")
    if m.time_dependent:
        return V("not-judgeable", reason=m.time_dependent)
    keys = d6_keys()
    per_alloc, nj, detected_pairs = [], [], set()
    for a in allocs_eval:
        if a.nj_reason or a.compute is None:
            nj.append("%s: %s" % (a.id, a.nj_reason or "no computation"))
            continue
        try:
            res = {s.id: [a.compute(s, k) for k in keys] for s in sems}
        except ValueError as e:
            nj.append("%s: %s" % (a.id, e))
            continue
        pairs = []
        for s1, s2 in itertools.combinations(sems, 2):
            x, y = res[s1.id], res[s2.id]
            flips = [(p, q) for p, q in zip(x, y) if p != q]
            if not flips:
                continue
            breakdown = {}
            for p, q in flips:
                kk = "%s -> %s" % (p, q)
                breakdown[kk] = breakdown.get(kk, 0) + 1
            pair = "%s ~ %s" % (s1.id, s2.id)
            detected_pairs.add(pair)
            first = next(i for i, (p, q) in enumerate(zip(x, y)) if p != q)
            pairs.append({"pair": [s1.id, s2.id], "flips": len(flips), "flip_rate": len(flips) / len(keys),
                          "breakdown": dict(sorted(breakdown.items())),
                          "example": {"targetingKey": keys[first], s1.id: x[first], s2.id: y[first]},
                          "fidelity": {s1.id: fidelity(s1.id), s2.id: fidelity(s2.id)}})
        alloc_summary = {s.id: _counts(res[s.id]) for s in sems}
        per_alloc.append({"allocation": a.id, "rule_path": a.rule_path, "assignment_counts": alloc_summary,
                          "divergent_pairs": pairs})
    if detected_pairs:
        src_only = sorted({sid for p in detected_pairs for sid in p.split(" ~ ") if fidelity(sid) != "vector-verified"})
        return V("detected", divergent_pairs=sorted(detected_pairs), allocations=per_alloc, contexts=D6,
                 fidelity_caveat=("semantics not vector-verified: %s" % src_only) if src_only else None,
                 reproduce="for each targetingKey in user-0000..user-0999 evaluate the allocation under each listed semantics")
    if nj:
        return V("not-judgeable", reason="; ".join(nj))
    if len(sems) < 2:
        return V("not-applicable", reason="fewer than two semantics modelled for %s" % m.format)
    return V("clean", allocations=per_alloc, contexts=D6, basis="no context flips between any semantics pair")


def _counts(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def check_f7(m):
    if not m.f7_applicable:
        return V("not-applicable", reason=m.f7_na_reason)
    rejects = [n for n in m.notes if "engine_rejects_file_at_load" in n]
    if rejects:
        return V("not-applicable", reason="the engine rejects this file at load (not silent): %s" %
                 rejects[0]["engine_rejects_file_at_load"][0])
    if m.f7:
        return V("detected", findings=m.f7)
    return V("clean", basis="no F7 catalog condition holds")


def check_f5(m):
    if not m.variant_values:
        return V("not-applicable", severity="info", reason="no typed variant values in this format")
    types = {}
    for k, v in m.variant_values.items():
        t = "null" if v is None else "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) \
            else "string" if isinstance(v, str) else "array" if isinstance(v, list) else "object"
        types.setdefault(t, []).append(k)
    if len(types) > 1:
        return V("detected", severity="info", types={t: sorted(v) for t, v in sorted(types.items())},
                 note="informational only: already caught by flagd schema / GOFF load-time IsValid (Phase 0 KT-1)")
    return V("clean", severity="info")


def check_all(m):
    return {"F1": check_f1(m), "F2": check_f2(m), "F3": check_f3(m), "F4": check_f4(m), "F7": check_f7(m),
            "F5": check_f5(m)}
