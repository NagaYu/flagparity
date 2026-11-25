"""GO Feature Flag YAML -> FlagModel."""
import json

from .formats import nikunjy
from .formats.goff import GoffDoc
from .model import Alloc, FlagModel, Leaf, Reach
from .witness import Collector, MISSING


def _collect_query(coll, node):
    for attr, rtype, val, op in nikunjy.constants(node):
        if rtype == "pr":
            coll.present(attr)
        elif rtype == "string":
            if op in ("EQ", "NE"):
                coll.eq(attr, val)
            elif op == "SW":
                coll.prefix(attr, val.lower())
            elif op == "EW":
                coll.suffix(attr, val.lower())
            elif op == "CO":
                coll.contains(attr, val.lower())
            else:
                coll.unknown(attr, "string ordering comparison")
        elif rtype == "list_string":
            for x in val:
                coll.eq(attr, x)
        elif rtype in ("int", "double"):
            coll.order(attr, val)
        elif rtype in ("list_int", "list_double"):
            for x in val:
                coll.eq(attr, x)
                coll.order(attr, x)
        elif rtype == "bool":
            coll.boolean(attr)
        elif rtype == "null":
            coll.present(attr)
        elif rtype == "version":
            coll.semver(attr, val)
        else:
            coll.unknown(attr, rtype)


def analyze_doc(docs):
    gdoc = GoffDoc(docs)
    models = [_flag_model(f) for f in sorted(gdoc.flags, key=lambda x: x.name)]
    if gdoc.load_errors:
        for m in models:
            m.notes.append({"engine_rejects_file_at_load": ["YAML decode (gopkg.in/yaml.v3): %s" % e for e in gdoc.load_errors[:10]]})
    return gdoc, models


def _rule_leaf_and_alloc(flag, rule, lid, label):
    allocs = []
    kind = rule.outcome_kind()
    if kind == "progressive":
        pr = rule.progressive
        prod = tuple(x for x in ((pr.get("initial") or {}).get("variation"), (pr.get("end") or {}).get("variation"))
                     if isinstance(x, str))
        leaf = Leaf(id=lid, label=label + " (progressiveRollout)", explicit=rule.index is not None, kind="multi", produces=prod)
    elif kind == "percentage":
        aid = lid + "/percentage"
        leaf = Leaf(id=lid, label=label + " (percentage)", explicit=rule.index is not None, kind="alloc", alloc_id=aid)
        allocs.append(_pct_alloc(flag, rule, aid, lid))
    elif kind == "variation":
        leaf = Leaf(id=lid, label=label + " -> %s" % rule.variation, explicit=rule.index is not None, kind="variant",
                    variant=str(rule.variation))
    else:
        leaf = Leaf(id=lid, label=label + " (no outcome)", explicit=rule.index is not None, kind="error")
    if rule.percentage_malformed:
        leaf.kind = "dynamic"
    return leaf, allocs


def _flag_model(flag):
    leaves, allocs = [], []
    for r in flag.rules:
        if r.disable:
            continue
        lid = "targeting[%d]" % r.index
        lf, al = _rule_leaf_and_alloc(flag, r, lid, "rule %d%s" % (r.index + 1, " %r" % r.name if r.name else ""))
        leaves.append(lf)
        allocs += al
    if flag.default_rule:
        lf, al = _rule_leaf_and_alloc(flag, flag.default_rule, "defaultRule", "defaultRule")
        lf.explicit = False
        leaves.append(lf)
        allocs += al
    has_cond = any(not r.disable for r in flag.rules)
    has_mech = has_cond or bool(allocs) or any(l.kind == "multi" for l in leaves)
    default_variant = flag.default_rule.variation if (flag.default_rule and flag.default_rule.outcome_kind() == "variation") else None
    m = FlagModel(key=flag.name, format="goff", variants=list(flag.variation_names),
                  variant_values={str(k): v for k, v in flag.variations.items()}, default_variant=default_variant,
                  has_mechanism=has_mech, leaves=leaves, allocs=allocs, has_conditions=has_cond)
    if flag.disable:
        m.disabled = "disable: true (explicit)"
    if flag.raw.get("scheduledRollout"):
        m.time_dependent = "scheduledRollout changes the configuration at runtime dates"
    elif flag.raw.get("experimentation"):
        m.time_dependent = "experimentation window depends on evaluation time"
    # F7 catalog
    for r in ([flag.default_rule] if flag.default_rule else []) + flag.rules:
        where = "defaultRule" if r.is_default else "targeting[%d]" % r.index
        if r.progressive is not None and (r.percentage or r.variation is not None):
            m.f7.append({"entry": "F7-c", "where": where,
                         "what": "progressiveRollout set together with %s; the latter is never evaluated" %
                                 " and ".join(x for x, c in (("percentage", r.percentage), ("variation", r.variation is not None)) if c),
                         "evidence": ["go-feature-flag@v1.59.1 modules/core/flag/rule.go L109-L113",
                                      "go-feature-flag@v1.59.1 modules/core/flag/rule_test.go (\"Progressive rollout ignore percentage\")"]})
        elif r.percentage and r.variation is not None:
            m.f7.append({"entry": "F7-b", "where": where,
                         "what": "percentage set together with variation %r; the variation is never evaluated" % r.variation,
                         "evidence": ["go-feature-flag@v1.59.1 modules/core/flag/rule.go L115-L123",
                                      "go-feature-flag@v1.59.1 modules/core/flag/rule_test.go L180 (\"Percentage ignore variation result\")"]})
        if r.is_default and r.disable:
            m.f7.append({"entry": "F7-d", "where": where, "what": "defaultRule has disable: true, which the engine ignores",
                         "evidence": ["go-feature-flag@v1.59.1 modules/core/flag/rule.go L106",
                                      "go-feature-flag@v1.59.1 modules/core/flag/rule_validation.go L14"]})
    bad = [r for r in flag.rules if not r.disable and (r.query_error or r.query_format == "jsonlogic")]
    if has_cond and not m.disabled:
        if bad:
            m.f1_nj = "query not analysable: %s" % (bad[0].query_error or "JSONLogic query (not in the modelled fragment)")
        m.reach = _reach(flag)
        if bad:
            m.reach.complete = False
            m.reach.reason = m.f1_nj
    return m


def _reach(flag):
    coll = Collector(mode="json", case_fold=True)
    coll.present("key")
    for r in flag.rules:
        if not r.disable and r.query is not None:
            _collect_query(coll, r.query)
    gen, complete, reason, n = coll.assignments()
    hits = set()
    paths = list(coll.attrs)
    if any(p != q and q.startswith(p + ".") for p in paths for q in paths):
        complete = False
        reason = reason or "attribute is both a value and an object"
    for assign in gen:
        ctx = _nested(assign)
        hit = None
        for r in flag.rules:
            if r.disable:
                continue
            if r.applies(ctx):
                hit = "targeting[%d]" % r.index
                break
        hits.add(hit or "defaultRule")
    return Reach(hits=hits, complete=complete, reason=reason, n_assignments=n)


def _nested(assign):
    ctx = {}
    for path in sorted(assign, key=lambda p: p.count(".")):
        v = assign[path]
        if v is MISSING:
            continue
        cur = ctx
        parts = path.split(".")
        ok = True
        for p in parts[:-1]:
            if p in cur and not isinstance(cur[p], dict):
                ok = False
                break
            cur = cur.setdefault(p, {})
        if ok:
            cur[parts[-1]] = v
    return ctx


def _pct_alloc(flag, rule, aid, lid):
    pc = rule.percentage
    total = sum(pc.values())
    f2 = []
    if abs(total - 100.0) > 1e-9:
        f2.append({"kind": "percentage-sum-not-100", "declared_sum": total,
                   "declared": [[k, v] for k, v in sorted(pc.items())],
                   "effective_share": {"goff/v1.32+": {k: round(v / total * 100, 6) for k, v in sorted(pc.items())},
                                       "goff/pre-v1.32": "rule errors: SDK default value for every context"},
                   "effect": "silently normalised by 100/%.6g since v1.32.0; rejected per evaluation before" % total})
    a = Alloc(id=aid, label="%s percentage" % lid, rule_path=lid, entries=sorted(pc.items()), f2=f2,
              positive=tuple(k for k, v in sorted(pc.items()) if v > 0))
    if flag.bucketing_key is not None and not isinstance(flag.bucketing_key, str):
        a.nj_reason = "bucketingKey is not a string"

    def compute(sem, tk, _pc=dict(pc), _flag=flag):
        v = sem.impl.percentage(_flag.name, tk, _pc)
        return v if v is not None else "(rule error -> SDK default)"

    a.compute = compute
    return a
