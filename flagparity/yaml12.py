"""YAML loading as the engines' Go decoder sees it (gopkg.in/yaml.v3 v3.0.1, pinned by Flipt v1.62.1 / v2.14.2 and
GO Feature Flag v1.31.2 / v1.59.1 — vectors/upstream/go.mod/; decoder source vectors/upstream/go-yaml@v3.0.1/).

Untyped scalars follow the YAML 1.2 core schema (so `on`, `yes`, `off` stay strings), but what a *field* receives
depends on its Go type (decode.go `scalar`, L565-L700):
- string fields and map[string]... keys keep the scalar's source text (L611-L617): `true:` is the key "true",
  `0x10:` is "0x10", `012:` is "012" — never Python's str(True) / str(16).
- bool fields accept YAML 1.1 spellings y/yes/on/n/no/off (L677-L693) besides true/false; anything else is a decode
  error (the engine rejects the file).
- numeric fields resolve the source text with yaml.v3's resolver (resolve.go L180-L250): underscores removed, then
  Go ParseInt base 0 (0x.., 0o.., 0b.., and legacy leading-zero octal: `012` = 10), else float.
- duplicate mapping keys (same source text, whatever the quoting) are a decode error (decode.go L769-L782).

The loader returns ordinary Python values, with plain-scalar numbers as YInt/YFloat (int/float subclasses that keep
`.src`) and strings as YStr (str subclass with `.plain`), so the helpers below can apply the Go field rules.
"""
import math
import re

import yaml
from yaml.nodes import MappingNode, ScalarNode


class DuplicateKeyError(yaml.YAMLError):
    pass


class GoDecodeError(ValueError):
    """The Go decoder would reject the file (type mismatch in a typed field)."""


class YInt(int):
    src = None


class YFloat(float):
    src = None


class YStr(str):
    plain = False


class Loader12(yaml.SafeLoader):
    pass


Loader12.yaml_implicit_resolvers = {}
_resolvers = [
    ("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")),
    ("tag:yaml.org,2002:null", re.compile(r"^(?:~|null|Null|NULL|)$"), ["~", "n", "N", ""]),
    ("tag:yaml.org,2002:int", re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"),
     list("-+0123456789")),
    ("tag:yaml.org,2002:float",
     re.compile(r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"),
     list("-+.0123456789")),
]
for tag, rx, first in _resolvers:
    Loader12.add_implicit_resolver(tag, rx, first)


def _construct_bool(loader, node):
    return loader.construct_scalar(node) in ("true", "True", "TRUE")


def _construct_int(loader, node):
    s = loader.construct_scalar(node)
    v = go_number(s)
    if not isinstance(v, int):  # cannot happen for the 1.2 int pattern, kept for safety
        v = int(s, 10)
    out = YInt(v)
    out.src = s
    return out


def _construct_float(loader, node):
    s = loader.construct_scalar(node)
    sl = s.lower()
    if sl.endswith(".inf"):
        v = float("-inf") if sl.startswith("-") else float("inf")
    elif sl == ".nan":
        v = float("nan")
    else:
        v = float(sl)
    out = YFloat(v)
    out.src = s
    return out


def _construct_str(loader, node):
    out = YStr(loader.construct_scalar(node))
    out.plain = node.style is None
    return out


def _key_text(loader, kn):
    """map[string]... key as yaml.v3 decodes it: the scalar's source text."""
    if isinstance(kn, ScalarNode):
        return kn.value
    return loader.construct_object(kn, deep=True)


def _construct_mapping(loader, node):
    loader.flatten_mapping(node)
    out = {}
    seen = {}
    for kn, vn in node.value:
        if isinstance(kn, ScalarNode):
            if kn.value in seen:
                raise DuplicateKeyError("mapping key %r already defined (line %d and line %d)"
                                        % (kn.value, seen[kn.value] + 1, kn.start_mark.line + 1))
            seen[kn.value] = kn.start_mark.line
        k = _key_text(loader, kn)
        try:
            hash(k)
        except TypeError:
            raise yaml.constructor.ConstructorError(None, None, "unhashable mapping key", kn.start_mark)
        out[k] = loader.construct_object(vn, deep=True)
    return out


Loader12.add_constructor("tag:yaml.org,2002:bool", _construct_bool)
Loader12.add_constructor("tag:yaml.org,2002:int", _construct_int)
Loader12.add_constructor("tag:yaml.org,2002:float", _construct_float)
Loader12.add_constructor("tag:yaml.org,2002:str", _construct_str)
Loader12.add_constructor("tag:yaml.org,2002:map", _construct_mapping)


def load_all(text: str):
    return list(yaml.load_all(text, Loader=Loader12))


# Dumping loaded data (bench/build.py writes mutated files): the subclasses are represented as their base types.
for _dumper in (yaml.SafeDumper, yaml.Dumper):
    _dumper.add_representer(YStr, yaml.representer.SafeRepresenter.represent_str)
    _dumper.add_representer(YInt, lambda d, v: d.represent_int(int(v)))
    _dumper.add_representer(YFloat, lambda d, v: d.represent_float(float(v)))


# ---------------------------------------------------------------- Go field rules (yaml.v3 decode.go / resolve.go)
_GO_FLOAT = re.compile(r"^[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?$")  # resolve.go yamlStyleFloat


def _go_parse_int0(s):
    """strconv.ParseInt(s, 0, 64) (after yaml.v3 removed underscores). Returns int or None."""
    m = re.fullmatch(r"([+-]?)(0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|0[0-7]*|[1-9][0-9]*)", s)
    if not m:
        return None
    sign, body = m.groups()
    b = body.lower()
    if b.startswith("0x"):
        v = int(b[2:], 16)
    elif b.startswith("0o"):
        v = int(b[2:], 8)
    elif b.startswith("0b"):
        v = int(b[2:], 2)
    elif len(b) > 1 and b.startswith("0"):
        v = int(b[1:], 8)  # legacy octal: 012 == 10
    else:
        v = int(b, 10)
    v = -v if sign == "-" else v
    if not (-(2 ** 63) <= v < 2 ** 64):
        return None
    return v


def go_number(src):
    """yaml.v3 resolve() of an untagged plain scalar that starts like a number (resolve.go L180-L250):
    int, float, or None when it resolves to a string."""
    if src is None:
        return None
    s = str(src)
    sl = s
    if sl in (".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF"):
        return float("inf")
    if sl in ("-.inf", "-.Inf", "-.INF"):
        return float("-inf")
    if sl in (".nan", ".NaN", ".NAN"):
        return float("nan")
    if not s or s[0] not in "+-.0123456789":
        return None
    plain = s.replace("_", "")
    v = _go_parse_int0(plain)
    if v is not None:
        return v
    if _GO_FLOAT.match(plain):
        try:
            return float(plain)
        except ValueError:
            return None
    return None


def go_str(v):
    """What a Go `string` field receives. Raises GoDecodeError for collections."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"  # limitation: the source case (True/TRUE) is not kept for booleans
    if isinstance(v, (YInt, YFloat)) and v.src is not None:
        return v.src
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return str(v)
    raise GoDecodeError("a %s where the engine expects a string" % type(v).__name__)


_TRUE11 = ("y", "Y", "yes", "Yes", "YES", "on", "On", "ON")
_FALSE11 = ("n", "N", "no", "No", "NO", "off", "Off", "OFF")


def go_bool(v, default=False):
    """What a Go `bool` field receives (absent/null -> default). Raises GoDecodeError when yaml.v3 would."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v in _TRUE11:
            return True
        if v in _FALSE11:
            return False
        raise GoDecodeError("%r is not a boolean for the engine's YAML decoder" % str(v))
    raise GoDecodeError("a %s where the engine expects a boolean" % type(v).__name__)


def go_float(v, default=0.0):
    """What a Go float32/float64 field receives (absent/null -> default). Raises GoDecodeError when yaml.v3 would."""
    if v is None:
        return default
    if isinstance(v, bool):
        raise GoDecodeError("a boolean where the engine expects a number")
    if isinstance(v, (YInt, YFloat)) and v.src is not None:
        n = go_number(v.src)
        if n is None:
            raise GoDecodeError("%r is not a number for the engine's YAML decoder" % v.src)
        return float(n)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, YStr) and v.plain:
        n = go_number(str(v))
        if n is not None:
            return float(n)
    raise GoDecodeError("%r is not a number for the engine's YAML decoder" % (v,))


def is_go_number(v):
    try:
        go_float(v)
    except GoDecodeError:
        return False
    return v is not None
