"""Flipt YAML -> FlagModel."""
import json

from . import semantics as S
from .formats.flipt import FliptDoc, match_segment, rule_segments_match
from .model import Alloc, FlagModel, Leaf, Reach
from .witness import Collector, MISSING

ENTITY = "$entityId"
BUCKET = "$thresholdBucket"


def _collect_segment(coll, seg):
    for c in seg["constraints"]:
        ctype = c.get("type") or "STRING_COMPARISON_TYPE"
        prop = ENTITY if ctype == "ENTITY_ID_COMPARISON_TYPE" else c.get("property")
        if not isinstance(prop, str):
            coll.unknown(str(prop), "non-string constraint property")
            continue
        op = c.get("operator")
        val = c.get("value")
        if val is not None and not isinstance(val, str):
            # Flipt decodes `value` into a string field; a YAML sequence/number there is either a load error or
            # coerced — not verified from source, so the witness set is marked incomplete.
            coll.unknown(prop, "constraint value is not a YAML string (%s)" % type(val).__name__)
            continue
        val = "" if val is None else val
        if ctype in ("STRING_COMPARISON_TYPE", "ENTITY_ID_COMPARISON_TYPE"):
            if op in ("eq", "neq"):
                coll.eq(prop, val)
                coll.eq(prop, " " + val)
            elif op == "prefix":
                coll.prefix(prop, val)
                coll.eq(prop, " " + val)
            elif op == "suffix":
                coll.suffix(prop, val)
                coll.eq(prop, val + " ")
            elif op in ("contains", "notcontains"):
                coll.contains(prop, val)
            elif op in ("isoneof", "isnotoneof"):
                try:
                    for x in json.loads(val):
                        coll.eq(prop, str(x))
                except (ValueError, TypeError):
                    coll.unknown(prop, "unparseable isoneof list")
            elif op in ("empty", "notempty"):
                coll.eq(prop, " ")
            else:
                coll.unknown(prop, "operator %r" % op)
        elif ctype == "NUMBER_COMPARISON_TYPE":
            if op in ("isoneof", "isnotoneof"):
                try:
                    for x in json.loads(val):
                        coll.order(prop, float(x))
                except (ValueError, TypeError):
                    coll.unknown(prop, "unparseable isoneof list")
            elif op in ("present", "notpresent"):
                coll.present(prop)
            else:
                try:
                    coll.order(prop, float(val))
                except ValueError:
                    coll.unknown(prop, "non-numeric constraint value")
        elif ctype == "BOOLEAN_COMPARISON_TYPE":
            coll.boolean(prop)
        elif ctype == "DATETIME_COMPARISON_TYPE":
            if op in ("present", "notpresent"):
                coll.present(prop)
            else:
                coll.datetime(prop, val)
        else:
            coll.unknown(prop, "constraint type %r" % ctype)


def analyze_doc(docs):
    fdoc = FliptDoc(docs)
    models = []
    for fl in sorted(fdoc.flags, key=lambda x: (x.doc_index, str(x.namespace), str(x.key))):
        models.append(_flag_model(fdoc, fl))
    return fdoc, models


def _flag_model(fdoc, fl):
    leaves, allocs = [], []
    is_bool = fl.type == "BOOLEAN_FLAG_TYPE"
    if is_bool:
        variants = []  # boolean flags declare no variants (F3 not applicable)
        for ro in fl.rollouts:
            lid = "rollouts[%d]" % ro["index"]
            leaves.append(Leaf(id=lid, label="rollout %d (%s) -> %s" % (ro["index"] + 1, ro["kind"], ro["value"]),
                               explicit=True, kind="variant", variant="true" if ro["value"] else "false"))
        leaves.append(Leaf(id="default", label="no rollout matched -> enabled (%s)" % fl.enabled, explicit=False,
                           kind="variant", variant="true" if fl.enabled else "false"))
        default = "true" if fl.enabled else "false"
        for ro in fl.rollouts:
            if ro["kind"] == "threshold":
                allocs.append(_threshold_alloc(fl, ro))
        # rules on a boolean flag are never evaluated (F7-a) but their declared distributions are still
        # checked by F2 (P1-C-3 applies to every rule's distributions).
        for r in fl.rules:
            if r["distributions"]:
                a = _dist_alloc(fl, r, "rules[%d]/distributions" % r["index"])
                a.evaluated = False
                for f in a.f2:
                    f["note"] = "declared on a BOOLEAN_FLAG_TYPE flag: the engine never evaluates these rules (F7-a)"
                allocs.append(a)
    else:
        variants = list(fl.variant_keys)
        default = fl.default_variant
        for r in fl.rules:
            lid = "rules[%d]" % r["index"]
            valid = [d for d in r["distributions"] if _num(d["rollout"]) and float(d["rollout"]) > 0]
            if valid:
                aid = lid + "/distributions"
                leaves.append(Leaf(id=lid, label="rule %d (segments %s)" % (r["index"] + 1, ",".join(map(str, r["segment_keys"]))),
                                   explicit=True, kind="alloc", alloc_id=aid))
                allocs.append(_dist_alloc(fl, r, aid))
            else:
                leaves.append(Leaf(id=lid, label="rule %d with no positive distribution -> default variant" % (r["index"] + 1),
                                   explicit=True, kind="default"))
                if r["distributions"]:
                    allocs.append(_dist_alloc(fl, r, lid + "/distributions"))
        leaves.append(Leaf(id="default", label="no rule matched -> default variant", explicit=False, kind="default"))
    # rules/rollouts naming an unknown segment make the engine reject the snapshot at load (snapshot.go L421, L550):
    # they are not silently unreachable, so they are not F1 candidates.
    unknown = set()
    for it, prefix in ((fl.rollouts, "rollouts") if is_bool else (fl.rules, "rules"),):
        for x in it:
            if any(k not in fl.segments for k in x.get("segment_keys", [])):
                unknown.add("%s[%d]" % (prefix, x["index"]))
    for l in leaves:
        if l.id in unknown:
            l.explicit = False
            l.label += " [references an unknown segment: engine rejects the file at load]"
    has_cond = bool(fl.rollouts if is_bool else fl.rules)
    has_mech = has_cond
    m = FlagModel(key=fl.key, format="flipt", variants=variants, variant_values={}, default_variant=default,
                  has_mechanism=has_mech, leaves=leaves, allocs=allocs, has_conditions=has_cond)
    m.location = {"namespace": fl.namespace, "document": fl.doc_index}
    if not is_bool and not fl.enabled:
        m.disabled = "variant flag enabled: false (explicit; rules are not evaluated)"
    # F7 catalog (P1-B-2 / P1-Z-1)
    if is_bool and fl.rules:
        decl = [{"rule": r["index"] + 1, "segments": r["segment_keys"],
                 "distributions": [[d["variant"], d["rollout"]] for d in r["distributions"]]} for r in fl.rules]
        m.f7.append({"entry": "F7-a", "what": "BOOLEAN_FLAG_TYPE flag has %d rule(s); boolean evaluation reads only rollouts" % len(fl.rules),
                     "ignored": decl,
                     "evidence": ["flipt@v2.14.2 internal/server/evaluation/evaluation.go L314, L338",
                                  "flipt@v1.62.1 internal/server/evaluation/evaluation.go L134-",
                                  "flipt-client-sdks@19e54652 flipt-evaluation/src/lib.rs L302"]})
    if not is_bool and fl.rollouts:
        m.f7.append({"entry": "F7-e", "what": "variant flag has %d rollout(s); variant evaluation reads only rules" % len(fl.rollouts),
                     "ignored": [{"rollout": ro["index"] + 1, "kind": ro["kind"]} for ro in fl.rollouts],
                     "evidence": ["flipt@v2.14.2 internal/server/evaluation/evaluation.go L172",
                                  "flipt@v2.14.2 internal/storage/fs/snapshot.go L490-L609, L803-L810",
                                  "flipt-client-sdks@19e54652 flipt-evaluation/src/lib.rs L149"]})
    if fdoc.load_errors:
        m.notes.append({"engine_rejects_file_at_load": fdoc.load_errors[:10]})
    if has_cond and not m.disabled:
        m.reach = _reach(fl, is_bool)
    return m


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _reach(fl, is_bool):
    results = {}
    for dialect in ("go", "rust"):
        coll = Collector(mode="string")
        items = fl.rollouts if is_bool else fl.rules
        for it in items:
            if is_bool and it["kind"] == "threshold":
                coll.order(BUCKET, it["percentage"] if _num(it["percentage"]) else 0)
                continue
            for k in it.get("segment_keys", []):
                seg = fl.segments.get(k)
                if seg:
                    _collect_segment(coll, seg)
        gen, complete, reason, n = coll.assignments()
        hits = set()
        for assign in gen:
            ctx = {k: v for k, v in assign.items() if v is not MISSING and k not in (ENTITY, BUCKET)}
            ent = assign.get(ENTITY)
            ent = "" if ent is MISSING or ent is None else ent
            hits.add(_first(fl, is_bool, ctx, ent, assign.get(BUCKET), dialect))
        results[dialect] = (hits, complete, reason, n)
    hits = results["go"][0] | results["rust"][0]
    complete = results["go"][1] and results["rust"][1]
    r = Reach(hits=hits, complete=complete, reason=results["go"][2] or results["rust"][2],
              n_assignments=results["go"][3])
    # DECISIONS P3-Z-6 B-3b: a rule reached by one constraint dialect only (Go servers trim whitespace for empty /
    # prefix / suffix, the Rust engine does not) stays clean, with the engines where it is unreachable noted.
    names = {"go": "flipt/server-legacy, flipt/server-v2.9+", "rust": "flipt/rust-client"}
    for d in ("go", "rust"):
        miss = sorted(h for h in hits - results[d][0])
        if miss and results[d][1]:
            r.engine_unreached[names[d]] = miss
    return r


def _first(fl, is_bool, ctx, ent, bucket, dialect):
    if is_bool:
        for ro in fl.rollouts:
            if ro["kind"] == "threshold":
                try:
                    b = float(bucket) if bucket is not MISSING and bucket is not None else 0.0
                except ValueError:
                    b = 0.0
                b = min(max(b, 0.0), 99.0)
                b = float(int(b))
                if _num(ro["percentage"]) and b < float(ro["percentage"]):
                    return "rollouts[%d]" % ro["index"]
            else:
                m, _ = rule_segments_match(fl, ro["segment_keys"], ro["operator"], ctx, ent, dialect)
                if m:
                    return "rollouts[%d]" % ro["index"]
        return "default"
    for r in fl.rules:
        m, _ = rule_segments_match(fl, r["segment_keys"], r["operator"], ctx, ent, dialect)
        if m:
            return "rules[%d]" % r["index"]
    return "default"


def _dist_alloc(fl, r, aid):
    entries = [(d["variant"], d["rollout"]) for d in r["distributions"]]
    f2, f2nj = [], None
    if not all(_num(w) for _, w in entries):
        f2nj = "non-numeric rollout"
        total = None
    else:
        total = sum(float(w) for _, w in entries)
        if abs(total - 100.0) > 1e-9:
            legacy = S.get("flipt/server-legacy").impl
            valid = [(v, float(w)) for v, w in entries if float(w) > 0]
            edges = legacy.edges([w for _, w in valid]) if valid else []
            shares = {}
            for b in range(1000):
                idx = legacy.index_for_bucket(edges, b, len(valid)) if valid else None
                k = valid[idx][0] if idx is not None else "(no match -> default variant %s)" % fl.default_variant
                shares[k] = shares.get(k, 0) + 1
            f2.append({"kind": "rollout-sum-not-100", "declared_sum": total,
                       "declared": [[v, w] for v, w in entries],
                       "effective_per_mille": {"flipt/server-legacy": dict(sorted(shares.items())),
                                               "flipt/server-v2.9+ and rust-client": "normalised to sum 100"},
                       "effect": ("remainder %.4g%% silently falls to the flag default (legacy); "
                                  "v2.9+/Rust rescale every share by 100/%.4g" % (100 - total, total)) if total < 100 else
                                 ("excess %.4g%% silently dropped (legacy); v2.9+/Rust rescale by 100/%.4g" % (total - 100, total))})
    positive = tuple(v for v, w in entries if _num(w) and float(w) > 0)
    legacy_residual = ()
    if total is not None and total < 100 - 1e-9:
        legacy_residual = ("flipt/server-legacy",)
    a = Alloc(id=aid, label="rule %d distributions" % (r["index"] + 1), rule_path="rules[%d]" % r["index"],
              entries=entries, f2=f2, f2_nj=f2nj, positive=positive, default_on_some_semantics=legacy_residual)
    valid = [(v, float(w)) for v, w in entries if _num(w) and float(w) > 0]
    if f2nj:
        a.nj_reason = f2nj

    def compute(sem, tk, _valid=valid, _fl=fl):
        # DECISIONS P3-A-2: compare the variant the application receives. With no matching distribution the
        # response keeps the flag's default variant (flipt v1.62.1 legacy_evaluator.go L94-L96, L227-L229).
        dflt = _fl.default_variant if _fl.default_variant else "(code default: no default variant)"
        if not _valid:
            return dflt
        idx = sem.impl.variant_index(_fl.key, tk, [w for _, w in _valid])
        return _valid[idx][0] if idx is not None else dflt

    a.compute = compute
    return a


def _threshold_alloc(fl, ro):
    pct = ro["percentage"]
    a = Alloc(id="rollouts[%d]/threshold" % ro["index"], label="rollout %d threshold %s%%" % (ro["index"] + 1, pct),
              rule_path="rollouts[%d]" % ro["index"], entries=[(str(ro["value"]).lower(), pct)])
    if not _num(pct):
        a.nj_reason = "non-numeric threshold percentage"

    def compute(sem, tk, _p=pct, _v=ro["value"], _fl=fl):
        hit = sem.impl.threshold_hit(_fl.key, tk, _p)
        return ("true" if _v else "false") if hit else "(fall through to next rollout)"

    a.compute = compute
    return a
