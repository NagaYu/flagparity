"""flagd JSON -> FlagModel."""
import json

from . import semantics as S
from .contexts import d6_keys
from .formats.flagd import FlagdDoc, make_logic, _go_json_float
from .jsonlogic import JSONLogic, JLError, go_parse_float, referenced_vars, to_number, truthy
from .model import Alloc, FlagModel, Leaf, Reach
from .semantics.flagd import op_sem_ver, op_starts_with, op_ends_with
from .witness import Collector, MISSING

BOOL_RESULT_OPS = {"==", "===", "!=", "!==", "<", "<=", ">", ">=", "!", "!!", "in", "starts_with", "ends_with", "sem_ver"}
DEFAULT_MARK = "\u0000default"
SUPPORTED_COND_OPS = {"==", "===", "!=", "!==", "in", "starts_with", "ends_with", "sem_ver", "<", "<=", ">", ">=",
                      "!", "!!", "and", "or", "if", "?:", "var", "missing", "missing_some"}


def _is_var(x):
    return isinstance(x, dict) and len(x) == 1 and "var" in x


def _var_path(x):
    a = x["var"]
    p = a[0] if isinstance(a, list) and a else a
    return p if isinstance(p, str) else None


def _literal(x):
    return x is None or isinstance(x, (str, int, float, bool)) or (isinstance(x, list) and all(_literal(y) for y in x))


class _CondScan:
    """Feeds a Collector from a JSONLogic condition; records unsupported constructs."""

    def __init__(self, coll):
        self.coll = coll
        self.unsupported = []

    def attr(self, path):
        if path in ("$flagd.flagKey",):
            return None
        if path.startswith("$flagd"):
            self.unsupported.append("condition reads %s (evaluation time)" % path)
            return None
        return path

    def scan(self, node):
        if isinstance(node, list):
            for x in node:
                self.scan(x)
            return
        if not isinstance(node, dict) or len(node) != 1:
            if isinstance(node, dict) and node:
                self.unsupported.append("non-operation object")
            return
        op, args = next(iter(node.items()))
        al = args if isinstance(args, list) else [args]
        if op == "var":
            p = _var_path(node)
            if p is None:
                self.unsupported.append("computed var path")
                return
            a = self.attr(p)
            if a is not None:
                self.coll.present(a)
            return
        if op not in SUPPORTED_COND_OPS:
            vs = referenced_vars(node)
            self.unsupported.append("operator %r outside the decidable fragment" % op)
            for v in vs:
                a = self.attr(v)
                if a:
                    self.coll.unknown(a, "operator %r" % op)
            return
        if op in ("==", "===", "!=", "!==") and len(al) == 2:
            l, r = al
            if _is_var(l) and _literal(r):
                self._eq(l, r)
            elif _is_var(r) and _literal(l):
                self._eq(r, l)
            else:
                self.scan(al)
                if not (_literal(l) and _literal(r)):
                    self._unknown_vars(node, "comparison between expressions")
            return
        if op == "in" and len(al) == 2:
            l, r = al
            if _is_var(l) and isinstance(r, list) and all(_literal(x) for x in r):
                for x in r:
                    self._eq(l, x)
                    if isinstance(x, str):
                        # jsonlogic v3.10.2 lists.go _in: a number matches a string element when
                        # types.toNumber(element) (ParseFloat, 0 on error) equals it -> numeric witnesses needed
                        a = self._a(l)
                        if a:
                            f = go_parse_float(x)
                            self.coll.order(a, 0.0 if f is None or f != f or f in (float("inf"), float("-inf")) else f)
            elif _literal(l) and isinstance(l, str) and _is_var(r):
                a = self._a(r)
                if a:
                    self.coll.contains(a, l)
            else:
                self._unknown_vars(node, "'in' form")
            return
        if op in ("starts_with", "ends_with") and len(al) == 2:
            l, r = al
            if _is_var(l) and isinstance(r, str):
                a = self._a(l)
                if a:
                    (self.coll.prefix if op == "starts_with" else self.coll.suffix)(a, r)
            else:
                self._unknown_vars(node, op + " form")
            return
        if op == "sem_ver" and len(al) == 3:
            l, o, r = al
            if _is_var(l) and _literal(r) and isinstance(o, str):
                a = self._a(l)
                if a:
                    self.coll.semver(a, r if isinstance(r, str) else json.dumps(r))
            elif _is_var(r) and _literal(l):
                a = self._a(r)
                if a:
                    self.coll.semver(a, l if isinstance(l, str) else json.dumps(l))
            else:
                self._unknown_vars(node, "sem_ver form")
            return
        if op in ("<", "<=", ">", ">="):
            ok = True
            for x in al:
                if _is_var(x):
                    continue
                if not (isinstance(x, (int, float)) and not isinstance(x, bool)) and not isinstance(x, str):
                    ok = False
            if ok:
                nums = [x for x in al if isinstance(x, (int, float)) and not isinstance(x, bool)]
                strs = [x for x in al if isinstance(x, str)]
                for x in al:
                    if _is_var(x):
                        a = self._a(x)
                        if a:
                            for n in nums:
                                self.coll.order(a, n)
                            for s in strs:
                                self.coll.unknown(a, "string ordering comparison")
                if sum(1 for x in al if _is_var(x)) > 1:
                    self._unknown_vars(node, "comparison between attributes")
            else:
                self._unknown_vars(node, "ordering over expressions")
            return
        if op in ("missing", "missing_some"):
            for v in referenced_vars(al) + [x for x in (al[-1] if op == "missing_some" else al) if isinstance(x, str)]:
                a = self.attr(v)
                if a:
                    self.coll.present(a)
            return
        self.scan(al)

    def _a(self, var):
        p = _var_path(var)
        if p is None:
            self.unsupported.append("computed var path")
            return None
        return self.attr(p)

    def _eq(self, var, lit):
        a = self._a(var)
        if a is None:
            return
        if isinstance(lit, list):
            self.coll.unknown(a, "comparison with an array")
            return
        self.coll.eq(a, lit)
        if isinstance(lit, (int, float)) and not isinstance(lit, bool):
            self.coll.eq(a, str(lit) if lit == int(lit) else repr(lit))
            self.coll.order(a, lit)
        elif isinstance(lit, str):
            try:
                self.coll.order(a, float(lit))
            except ValueError:
                pass
            # comp.go equals: a non-string operand compares by ToNumber, and ToNumber("") == ToNumber("  ") == 0
            n = to_number(lit)
            if n == n and n not in (float("inf"), float("-inf")):
                self.coll.order(a, n)
        if isinstance(lit, bool):
            self.coll.boolean(a)

    def _unknown_vars(self, node, why):
        for v in referenced_vars(node):
            a = self.attr(v)
            if a:
                self.coll.unknown(a, why)
        self.unsupported.append(why)


def _build_ctx(assign):
    ctx = {}
    for path in sorted(assign, key=lambda p: p.count(".")):
        v = assign[path]
        if v is MISSING:
            continue
        cur = ctx
        parts = path.split(".")
        okp = True
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                if p in cur:
                    okp = False
                    break
                cur[p] = {}
            cur = cur[p]
        if okp:
            cur[parts[-1]] = v
    return ctx


def _variant_name(v):
    if isinstance(v, str):
        return v
    return json.dumps(v)


def analyze_doc(raw):
    fdoc = FlagdDoc(raw)
    models = []
    for fk in sorted(fdoc.flags):
        f = fdoc.flags[fk]
        if not isinstance(f, dict):
            continue
        models.append(_flag_model(fdoc, fk, f))
    return fdoc, models


def _flag_model(fdoc, fk, f):
    variants = f.get("variants") if isinstance(f.get("variants"), dict) else {}
    targeting = f.get("targeting")
    has_t = targeting is not None and targeting != {}
    leaves, allocs = [], []
    cond_nodes = []
    fractionals = []
    boolexprs = {}

    def walk(node, path):
        if isinstance(node, dict) and len(node) == 1 and next(iter(node)) in ("if", "?:"):
            args = node[next(iter(node))]
            args = args if isinstance(args, list) else [args]
            n = len(args)
            for i in range(0, n - 1, 2):
                cond_nodes.append(args[i])
                walk(args[i + 1], path + "/if[%d]" % (i + 1))
            if n % 2 == 1:
                walk(args[-1], path + "/if[%d]" % (n - 1))
            else:
                leaves.append(Leaf(id=path + "/if[implicit-null]", label="no branch matched -> defaultVariant",
                                   explicit=False, kind="default"))
            return
        if isinstance(node, dict) and len(node) == 1 and next(iter(node)) == "fractional":
            aid = path + "/fractional"
            leaves.append(Leaf(id=path, label="fractional at %s" % (path or "/"), explicit=True, kind="alloc", alloc_id=aid))
            fractionals.append((aid, node, path))
            return
        if isinstance(node, str):
            leaves.append(Leaf(id=path, label="returns %r" % node, explicit=True, kind="variant", variant=node))
            return
        if node is None:
            leaves.append(Leaf(id=path, label="returns null -> defaultVariant", explicit=True, kind="default"))
            return
        if isinstance(node, (bool, int, float)):
            leaves.append(Leaf(id=path, label="returns %s" % json.dumps(node), explicit=True, kind="variant",
                               variant=_variant_name(node)))
            return
        if _is_boolexpr(node):
            # flagd stringifies the JSON result: true -> variant "true", false -> "false", null -> defaultVariant
            leaves.append(Leaf(id=path, label="boolean expression %s" % json.dumps(node, sort_keys=True)[:80],
                               explicit=True, kind="boolexpr"))
            boolexprs[path] = node
            for x in _find_fractionals(node, path):
                fractionals.append(x)
            return
        leaves.append(Leaf(id=path, label="computed result %s" % json.dumps(node, sort_keys=True)[:80],
                           explicit=True, kind="dynamic"))
        for x in _find_fractionals(node, path):
            fractionals.append(x)

    if has_t:
        walk(targeting, "")
        for c in cond_nodes:
            for x in _find_fractionals(c, "cond"):
                fractionals.append(x)
    else:
        leaves.append(Leaf(id="static", label="no targeting -> defaultVariant", explicit=False, kind="default"))

    default = f.get("defaultVariant")
    default = default if isinstance(default, str) and default != "" else None
    has_conditions = bool(cond_nodes)
    seen_alloc = set()
    result_aids = {l.alloc_id for l in leaves if l.kind == "alloc"}
    for aid, node, path in fractionals:
        if aid in seen_alloc:
            continue
        seen_alloc.add(aid)
        allocs.append(_alloc(fk, aid, node, path, default, variants if aid in result_aids else None))
    # DECISIONS P3-A-1: any targeting other than absent / null / {} is a mechanism (P1-B-1 (i)), including a bare
    # value such as "yes": flagd evaluates it for every context (json.go v0.19.0 L453-L473).
    has_mech = has_t
    m = FlagModel(key=fk, format="flagd", variants=list(variants), variant_values=variants, default_variant=default,
                  has_mechanism=has_mech, leaves=leaves, allocs=allocs, has_conditions=has_conditions)
    if f.get("state") == "DISABLED":
        m.disabled = "state: DISABLED (explicit)"
    m.f7_applicable = False
    m.f7_na_reason = "F7 catalog has no flagd entry (P1-B-2, P1-Z-1)"
    if has_t and (has_conditions or boolexprs):
        m.reach, m.f1_nj = _reach(fdoc, fk, targeting, cond_nodes + list(boolexprs.values()), leaves, boolexprs)
    elif has_t:
        m.reach = Reach(hits={l.id for l in leaves}, complete=True, reason=None, n_assignments=0)
    else:
        m.reach = Reach(hits={"static"}, complete=True, reason=None, n_assignments=0)
    return m


def _is_boolexpr(node):
    """Expressions whose JSONLogic value is always true/false/null (and/or return an operand, so they
    qualify only when every operand does)."""
    if not (isinstance(node, dict) and len(node) == 1):
        return False
    op, args = next(iter(node.items()))
    if op in BOOL_RESULT_OPS:
        return True
    if op in ("and", "or") and isinstance(args, list) and args:
        return all(_is_boolexpr(a) or isinstance(a, bool) for a in args)
    return False


def _find_fractionals(node, path):
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("fractional", "fractionalEvaluation"):
                out.append((path + "/" + k, {k: v}, path))
            out += _find_fractionals(v, path + "/" + k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _find_fractionals(v, "%s[%d]" % (path, i))
    return out


def _reach(fdoc, fk, targeting, cond_nodes, leaves, boolexprs=None):
    boolexprs = boolexprs or {}
    coll = Collector(mode="json")
    sc = _CondScan(coll)
    for c in cond_nodes:
        sc.scan(c)
    logic = JSONLogic({"fractional": S.get("flagd/G3").impl.fractional, "starts_with": op_starts_with,
                       "ends_with": op_ends_with, "sem_ver": op_sem_ver})
    hits = set()
    gen, complete, reason, n = coll.assignments()
    if sc.unsupported:
        complete = False
        reason = reason or sc.unsupported[0]
    paths = [a for a in coll.attrs]
    if any(p != q and q.startswith(p + ".") for p in paths for q in paths):
        complete = False
        reason = reason or "attribute is both a value and an object"
    errors = 0
    outputs = {}
    for assign in gen:
        ctx = _build_ctx(assign)
        ctx["$flagd"] = {"flagKey": fk, "timestamp": 0}
        lid = _descend(targeting, ctx, "", logic)
        if lid is None:
            errors += 1
            continue
        hits.add(lid)
        if lid in boolexprs:
            try:
                v = logic.apply(boolexprs[lid], ctx)
            except (JLError, TypeError, ValueError, ZeroDivisionError, RecursionError):
                continue
            outputs.setdefault(lid, set()).add(DEFAULT_MARK if v is None else _variant_name(v))
    return Reach(hits=hits, complete=complete, reason=reason, n_assignments=n, outputs=outputs), None


def _descend(node, data, path, logic):
    if isinstance(node, dict) and len(node) == 1 and next(iter(node)) in ("if", "?:"):
        args = node[next(iter(node))]
        args = args if isinstance(args, list) else [args]
        n = len(args)
        for i in range(0, n - 1, 2):
            try:
                c = logic.apply(args[i], data)
            except (JLError, TypeError, ValueError, ZeroDivisionError, RecursionError):
                return None
            if truthy(c):
                return _descend(args[i + 1], data, path + "/if[%d]" % (i + 1), logic)
        if n % 2 == 1:
            return _descend(args[-1], data, path + "/if[%d]" % (n - 1), logic)
        return path + "/if[implicit-null]"
    return path


def _outcome(v, default):
    if v is None:
        return "(null -> defaultVariant %s)" % (default if default else "unset: code default")
    if v == "":
        return "(no bucket -> error)"
    return v if isinstance(v, str) else json.dumps(v)


CODE_DEFAULT = "(code default: error / no defaultVariant)"


def _resolve(v, variants, default):
    """The variant the application receives for a targeting result v (DECISIONS P3-A-2; flagd v0.19.0 json.go
    L453-L473): null -> defaultVariant (none: FALLBACK); else JSON text without quotes, if it names a variant;
    otherwise an error. Error and FALLBACK both give the application its code default (one value)."""
    if v is None:
        # a defaultVariant missing from variants fails the value lookup (json.go L387: type mismatch error)
        return default if default and default in variants else CODE_DEFAULT
    text = _go_json_float(v) if isinstance(v, float) else json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    name = text.strip().replace('"', "")
    return name if name in variants else CODE_DEFAULT


def _alloc(fk, aid, node, path, default, resolve_in=None):
    """resolve_in: the flag's variants when the fractional is the targeting result (compare resolved variants,
    P3-A-2); None when its value feeds another expression (raw bucket values; owner item P3-A-3 B-1)."""
    op = next(iter(node))
    args = node[op]
    entries, f2, nj = [], [], None
    weights_literal = True
    if op == "fractionalEvaluation":
        a = Alloc(id=aid, label="fractionalEvaluation at %s" % (path or "/"), rule_path=path or "/", entries=[],
                  nj_reason="legacy 'fractionalEvaluation' operator (pre-#1266 syntax): outside the modelled versions")
        a.f2_nj = a.nj_reason
        return a
    al = args if isinstance(args, list) else [args]
    dists = al[1:] if al and not isinstance(al[0], list) else al
    positive = []
    total = 0
    null_positive = False
    for d in dists:
        if not isinstance(d, list) or not d:
            weights_literal = False
            continue
        name = d[0]
        w = d[1] if len(d) > 1 else 1
        if not isinstance(w, (int, float)) or isinstance(w, bool):
            weights_literal = False
            entries.append((_variant_name(name) if _literal(name) else "<computed>", None))
            continue
        entries.append(("<null -> defaultVariant>" if name is None else _variant_name(name) if _literal(name) else "<computed>", w))
        if w < 0:
            f2.append({"kind": "negative-weight", "variant": entries[-1][0], "weight": w,
                       "effect": "G2/G3 clamp to 0 silently; G1 subtracts it from the total"})
        if float(w) != int(w):
            f2.append({"kind": "non-integer-weight", "variant": entries[-1][0], "weight": w,
                       "effect": "G1 truncates to int; G2/G3 reject the fractional (null -> defaultVariant)"})
        if w > 0:
            total += w
            if name is None:
                null_positive = True
            elif isinstance(name, str):
                positive.append(name)
            elif _literal(name):
                positive.append(_variant_name(name))
    if weights_literal and dists and total == 0:
        f2.append({"kind": "zero-total-weight", "effect": "fractional returns null: 100%% fall to defaultVariant (%s)" % default})
    a = Alloc(id=aid, label="fractional at %s" % (path or "/"), rule_path=path or "/", entries=entries, f2=f2,
              positive=tuple(positive), default_on_some_semantics=("all",) if null_positive else ())
    if not weights_literal:
        a.f2_nj = "weight computed by an expression"
    refvars = [v for v in referenced_vars(args) if not v.startswith("$flagd")]
    if any(v.startswith("$flagd.timestamp") for v in referenced_vars(args)):
        a.nj_reason = "allocation reads $flagd.timestamp (evaluation time)"

    def compute(sem, tk, _args=args, _refvars=refvars):
        data = {"targetingKey": tk, "$flagd": {"flagKey": fk, "timestamp": 0}}
        for v in _refvars:
            if v == "targetingKey":
                continue
            cur = data
            parts = v.split(".")
            for p in parts[:-1]:
                if not isinstance(cur.get(p), dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = tk
        logic = make_logic(sem)
        try:
            vals = logic.apply(_args if isinstance(_args, list) else [_args], data)
        except (JLError, TypeError, ValueError, ZeroDivisionError, RecursionError) as e:
            raise ValueError("argument evaluation failed: %s" % e)
        v = sem.impl.fractional(vals, data)
        if resolve_in is not None:
            return _resolve(v, resolve_in, default)
        return _outcome(v, default)

    a.compute = compute
    # DECISIONS P3-Z-7: the fractional returns nil (-> defaultVariant) in some generation for some context when its
    # arguments do not parse for that generation, or when the bucketing input is missing: no targetingKey / empty /
    # not a string (v0.19.0 fractional.go L163-L176, b9c099cb L77-L79, v0.17.1 L85-L90), or an explicit bucketing
    # expression that evaluates to null (G3 L139-L141). Probe each generation with such contexts.
    nil_on = []
    for sem in S.for_format("flagd"):
        logic = make_logic(sem)
        for ctx in ({"targetingKey": "user-0000"}, {}, {"targetingKey": ""}, {"targetingKey": 0}):
            data = dict(ctx)
            data["$flagd"] = {"flagKey": fk, "timestamp": 0}
            try:
                vals = logic.apply(args if isinstance(args, list) else [args], data)
                v = sem.impl.fractional(vals, data)
            except (JLError, TypeError, ValueError, ZeroDivisionError, RecursionError):
                continue  # an evaluation error is the code default, not the defaultVariant
            if v is None:
                nil_on.append(sem.id)
                break
    if nil_on:
        a.default_on_some_semantics = tuple(sorted(set(a.default_on_some_semantics) | set(nil_on)))
    if resolve_in is None and a.nj_reason is None:
        # DECISIONS P3-Z-6 B-1: the value feeds another expression, so the received variant is not decided here
        a.nj_reason = ("fractional value feeds another expression (not the targeting result): the variant the "
                       "application receives is not decided by the allocation alone (DECISIONS P3-Z-6 B-1)")
    return a
