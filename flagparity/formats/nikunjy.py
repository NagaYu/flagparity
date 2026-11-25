"""GO Feature Flag targeting query language (nikunjy/rules, go-feature-flag fork @e9704fa7).

Grammar (parser/JsonQuery.g4): query := NOT? '(' query ')' | query SP ('and'|'or') SP query
                                       | attrPath SP 'pr' | attrPath SP op SP value
`and`/`or` share one precedence level and associate to the left (ANTLR left recursion).
Operation semantics follow parser/*_operation.go:
- the right-hand literal's type picks the operation (string/int/double/version/bool/null/list);
- string eq/ne/gt/lt/ge/le/co/sw/ew compare lower-cased; `in` on string lists is case-sensitive;
- a missing attribute or a wrongly typed operand makes that comparison false (non-fatal);
- an operation invalid for the literal type (e.g. gt null) is fatal: the whole query is false.
"""
import re


class QueryParseError(Exception):
    pass


class _Fatal(Exception):
    pass


TOK = re.compile(r'''\s*(?:
    (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<lp>\() | (?P<rp>\)) | (?P<lb>\[) | (?P<rb>\]) | (?P<comma>,)
  | (?P<sym>==|!=|>=|<=|>|<)
  | (?P<ver>v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)
  | (?P<num>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?(?:0|[1-9]\d*))?)
  | (?P<word>[A-Za-z][A-Za-z0-9_:\-]*(?:\.[A-Za-z][A-Za-z0-9_:\-]*)*)
)''', re.X)

OPS = {"eq": "EQ", "==": "EQ", "ne": "NE", "!=": "NE", "gt": "GT", ">": "GT", "lt": "LT", "<": "LT",
       "ge": "GE", ">=": "GE", "le": "LE", "<=": "LE", "co": "CO", "sw": "SW", "ew": "EW", "in": "IN"}


def tokenize(s):
    pos, out = 0, []
    s = s.strip()
    while pos < len(s):
        m = TOK.match(s, pos)
        if not m or m.end() == pos:
            raise QueryParseError("unexpected input at %d: %r" % (pos, s[pos:pos + 20]))
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class Parser:
    def __init__(self, text):
        self.t = tokenize(text)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.query()
        if self.i != len(self.t):
            raise QueryParseError("trailing tokens")
        return node

    def query(self):
        left = self.primary()
        while True:
            k, v = self.peek()
            if k == "word" and v in ("and", "or"):
                self.take()
                right = self.primary()
                left = ("logic", v, left, right)
            else:
                return left

    def primary(self):
        k, v = self.peek()
        neg = False
        if k == "word" and v in ("not", "NOT"):
            self.take()
            neg = True
            k, v = self.peek()
            if k != "lp":
                raise QueryParseError("not must precede (")
        if k == "lp":
            self.take()
            q = self.query()
            if self.take()[0] != "rp":
                raise QueryParseError("missing )")
            return ("not", q) if neg else ("paren", q)
        if k != "word":
            raise QueryParseError("expected attribute")
        attr = self.take()[1]
        k, v = self.peek()
        if k == "word" and v == "pr":
            self.take()
            return ("pr", attr)
        if (k == "word" and v.lower() in OPS and v in (v.lower(), v.upper())) or k == "sym":
            op = OPS[v.lower()] if k == "word" else OPS[v]
            self.take()
            return ("cmp", attr, op, self.value())
        raise QueryParseError("expected operator after %s" % attr)

    def value(self):
        k, v = self.take()
        if k == "str":
            return ("string", _unq(v))
        if k == "ver":
            return ("version", v)
        if k == "num":
            if re.fullmatch(r"-?\d+", v):
                return ("int", int(v))
            if "." in v:
                return ("double", float(v))
            return ("int", int(float(v)))
        if k == "word" and v in ("true", "false"):
            return ("bool", v == "true")
        if k == "word" and v == "null":
            return ("null", None)
        if k == "lb":
            items = []
            while True:
                kk, vv = self.take()
                if kk == "str":
                    items.append(("s", _unq(vv)))
                elif kk == "num":
                    items.append(("d" if "." in vv else "i", float(vv) if "." in vv else int(vv)))
                else:
                    raise QueryParseError("bad list element")
                kk, _ = self.take()
                if kk == "rb":
                    break
                if kk != "comma":
                    raise QueryParseError("bad list")
            kinds = {x[0] for x in items}
            if len(kinds) != 1:
                raise QueryParseError("mixed list")
            kind = {"s": "list_string", "i": "list_int", "d": "list_double"}[kinds.pop()]
            return (kind, [x[1] for x in items])
        raise QueryParseError("expected value")


def _unq(v):
    import json
    return json.loads(v)


def parse(text):
    return Parser(text).parse()


def _get(ctx, path):
    cur = ctx
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _semver(s):
    m = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", s or "")
    if not m:
        return None
    pre = m.group(4).split(".") if m.group(4) else []
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre)


def _ver_cmp(a, b):
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    pa, pb = a[3], b[3]
    if not pa and not pb:
        return 0
    if not pa:
        return 1
    if not pb:
        return -1
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return -1 if int(x) < int(y) else 1
        if x.isdigit():
            return -1
        if y.isdigit():
            return 1
        return -1 if x < y else 1
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def _cmpres(op, c):
    return {"EQ": c == 0, "NE": c != 0, "GT": c > 0, "LT": c < 0, "GE": c >= 0, "LE": c <= 0}[op]


def _compare(left, op, rtype, rval):
    """Returns bool; raises _Fatal for ErrInvalidOperation."""
    if rtype == "null":
        if op == "EQ":
            return left is None
        if op == "NE":
            return left is not None
        raise _Fatal()
    if rtype in ("string", "list_string"):
        if op == "IN":
            if not isinstance(left, str) or rtype != "list_string":
                return False
            return left in rval
        if left is None or not isinstance(left, str) or rtype != "string":
            return False
        l, r = left.lower(), rval.lower()
        if op in ("EQ", "NE", "GT", "LT", "GE", "LE"):
            return _cmpres(op, (l > r) - (l < r))
        return {"CO": r in l, "SW": l.startswith(r), "EW": l.endswith(r)}[op]
    if rtype in ("int", "list_int"):
        if op == "IN":
            if not (isinstance(left, int) and not isinstance(left, bool)) or rtype != "list_int":
                return False
            return left in rval
        if op in ("CO", "SW", "EW"):
            raise _Fatal()
        if left is None or isinstance(left, bool) or not isinstance(left, (int, float)) or rtype != "int":
            return False
        lv = int(left)
        return _cmpres(op, (lv > rval) - (lv < rval))
    if rtype in ("double", "list_double"):
        if op == "IN":
            if isinstance(left, bool) or not isinstance(left, (int, float)) or rtype != "list_double":
                return False
            return float(left) in [float(x) for x in rval]
        if op in ("CO", "SW", "EW"):
            raise _Fatal()
        if left is None or isinstance(left, bool) or not isinstance(left, (int, float)) or rtype != "double":
            return False
        lv = float(left)
        return _cmpres(op, (lv > rval) - (lv < rval))
    if rtype == "bool":
        if op not in ("EQ", "NE"):
            raise _Fatal()
        if left is None or not isinstance(left, bool):
            return False
        return (left == rval) if op == "EQ" else (left != rval)
    if rtype == "version":
        if op in ("CO", "SW", "EW", "IN"):
            raise _Fatal()
        if not isinstance(left, str):
            return False
        a, b = _semver(left), _semver(rval.lstrip("v"))
        if a is None or b is None:
            return False
        return _cmpres(op, _ver_cmp(a, b))
    raise _Fatal()


def _eval(node, ctx):
    k = node[0]
    if k == "logic":
        left = _eval(node[2], ctx)
        if node[1] == "or":
            return left or _eval(node[3], ctx)
        return left and _eval(node[3], ctx)
    if k == "paren":
        return _eval(node[1], ctx)
    if k == "not":
        return not _eval(node[1], ctx)
    if k == "pr":
        return _get(ctx, node[1]) is not None
    if k == "cmp":
        _, attr, op, (rtype, rval) = node
        return _compare(_get(ctx, attr), op, rtype, rval)
    raise _Fatal()


def evaluate(node, ctx):
    try:
        return bool(_eval(node, ctx))
    except _Fatal:
        return False


def attributes(node, out=None):
    out = [] if out is None else out
    if node[0] in ("logic",):
        attributes(node[2], out)
        attributes(node[3], out)
    elif node[0] in ("paren", "not"):
        attributes(node[1], out)
    elif node[0] in ("pr", "cmp"):
        if node[1] not in out:
            out.append(node[1])
    return out


def constants(node, out=None):
    """(attr, rtype, value) for every comparison."""
    out = [] if out is None else out
    if node[0] == "logic":
        constants(node[2], out)
        constants(node[3], out)
    elif node[0] in ("paren", "not"):
        constants(node[1], out)
    elif node[0] == "cmp":
        out.append((node[1], node[3][0], node[3][1], node[2]))
    elif node[0] == "pr":
        out.append((node[1], "pr", None, "PR"))
    return out
