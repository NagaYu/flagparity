"""GO Feature Flag YAML (v1+ format): flag model and concrete rule evaluation (v1.59.1 rule.go order).

Rule evaluation order (rule.go L86-L123): query must match (defaultRule always applies); a disabled
targeting rule never applies (defaultRule ignores `disable`); then progressiveRollout, else percentage,
else variation. Targeting rules are tried in order; the first that applies wins (internal_flag.go L169).
"""
from . import nikunjy
from ..yaml12 import GoDecodeError, go_bool, go_float, go_str


def _gbool(errs, v, what):
    try:
        return go_bool(v, False)
    except GoDecodeError as e:
        errs.append("%s: %s" % (what, e))
        return False


class GoffRule:
    def __init__(self, raw, index, is_default, errs=None):
        self.errs = errs if errs is not None else []
        self.raw = raw if isinstance(raw, dict) else {}
        self.index = index
        self.is_default = is_default
        r = self.raw
        self.name = r.get("name")
        q = r.get("query")
        self.query_text = q.strip() if isinstance(q, str) else ("" if q is None else None)
        self.query = None
        self.query_error = None
        self.query_format = "nikunjy"
        if self.query_text and not is_default:
            if self.query_text.startswith("{"):
                self.query_format = "jsonlogic"
            else:
                try:
                    self.query = nikunjy.parse(self.query_text)
                except nikunjy.QueryParseError as e:
                    self.query_error = str(e)
        elif self.query_text is None:
            self.query_error = "query is not a string"
        self.variation = r.get("variation")
        if self.variation is not None:
            try:
                self.variation = go_str(self.variation)  # *string field: the scalar's source text
            except GoDecodeError as e:
                self.errs.append("rule variation: %s" % e)
        pc = r.get("percentage")
        self.percentage = None
        self.percentage_malformed = False
        if pc is not None:
            try:
                if not isinstance(pc, dict):
                    raise GoDecodeError("percentage is not a map")
                self.percentage = {str(k): go_float(v, 0.0) for k, v in pc.items()}  # map[string]float64
            except GoDecodeError as e:
                self.errs.append("rule percentage: %s" % e)
                self.percentage = None
                self.percentage_malformed = True
        self.progressive = r.get("progressiveRollout") if isinstance(r.get("progressiveRollout"), dict) else None
        self.disable = _gbool(self.errs, r.get("disable"), "rule disable")

    def applies(self, ctx):
        if self.is_default:
            return True
        if self.disable:
            return False
        if not self.query_text:
            return True
        if self.query is None:
            return False
        return nikunjy.evaluate(self.query, ctx)

    def outcome_kind(self):
        if self.progressive is not None:
            return "progressive"
        if self.percentage:
            return "percentage"
        if self.variation is not None:
            return "variation"
        return "none"


class GoffFlag:
    def __init__(self, name, raw):
        self.name = name
        self.raw = raw
        self.load_errors = []
        v = raw.get("variations")
        self.variations = v if isinstance(v, dict) else {}
        self.variation_names = [str(k) for k in self.variations]
        self.rules = [GoffRule(r, i, False, self.load_errors) for i, r in enumerate(raw.get("targeting") or []) if isinstance(r, dict)]
        self.default_rule = GoffRule(raw.get("defaultRule"), None, True, self.load_errors) if isinstance(raw.get("defaultRule"), dict) else None
        self.disable = _gbool(self.load_errors, raw.get("disable"), "flag disable")
        self.bucketing_key = raw.get("bucketingKey")
        self.time_dependent = bool(raw.get("scheduledRollout")) or bool(raw.get("experimentation")) or \
            any(r.progressive for r in self.rules) or bool(self.default_rule and self.default_rule.progressive)


class GoffDoc:
    def __init__(self, docs):
        self.flags = []
        self.load_errors = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            for k, f in d.items():
                if isinstance(f, dict) and isinstance(f.get("variations"), dict) and isinstance(f.get("defaultRule"), dict):
                    self.flags.append(GoffFlag(str(k), f))
        # internal/cache/cache_manager.go L69: one yaml.Unmarshal of the whole file; a decode error rejects it
        for fl in self.flags:
            self.load_errors.extend("flag %s %s" % (fl.name, e) for e in fl.load_errors)


def evaluate_rule(rule, flag_name, key, ctx, sem):
    """Returns variation name, None for 'rule does not apply', or 'ERROR'."""
    if not rule.applies(ctx):
        return None
    kind = rule.outcome_kind()
    if kind == "progressive":
        return "ERROR"  # time-dependent; not modelled concretely
    if kind == "percentage":
        v = sem.impl.percentage(flag_name, key, rule.percentage)
        return "ERROR" if v is None else v
    if kind == "variation":
        return rule.variation
    return "ERROR"


def evaluate(flag, key, ctx, sem):
    if flag.disable:
        return "SDK_DEFAULT", "DISABLED"
    c = dict(ctx)
    c["key"] = key
    for r in flag.rules:
        v = evaluate_rule(r, flag.name, key, c, sem)
        if v is None:
            continue
        return (v, "TARGETING_MATCH") if v != "ERROR" else ("SDK_DEFAULT", "ERROR")
    if flag.default_rule is None:
        return "SDK_DEFAULT", "ERROR"
    v = evaluate_rule(flag.default_rule, flag.name, key, c, sem)
    return (v, "DEFAULT") if v not in (None, "ERROR") else ("SDK_DEFAULT", "ERROR")
