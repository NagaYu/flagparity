"""Frozen copy of the Phase 1 YAML loader (git 1b8f1b6:flagbound/yaml12.py), used only by bench/build.py and
bench/manual_cases.py so that rebuilding the frozen dev bench reproduces its bytes. The detector uses
flagbound/yaml12.py (Phase 3: Go yaml.v3 field rules). Original docstring follows.

YAML loading with YAML 1.2 core-schema scalar resolution.

The engines (Flipt, GO Feature Flag) decode YAML with Go libraries that follow the YAML 1.2
core schema for untyped values (so `on`, `yes`, `off` stay strings) and keep the source text
for string-typed fields. PyYAML's default resolver is YAML 1.1 (`on` -> True), which would
silently rename variants such as `on:`. This loader resolves only 1.2 core booleans/nulls/numbers.
"""
import re

import yaml


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
    if s.startswith("0o"):
        return int(s[2:], 8)
    if s.startswith("0x"):
        return int(s[2:], 16)
    return int(s, 10)


def _construct_float(loader, node):
    s = loader.construct_scalar(node).lower()
    if s.endswith(".inf"):
        return float("-inf") if s.startswith("-") else float("inf")
    if s == ".nan":
        return float("nan")
    return float(s)


Loader12.add_constructor("tag:yaml.org,2002:bool", _construct_bool)
Loader12.add_constructor("tag:yaml.org,2002:int", _construct_int)
Loader12.add_constructor("tag:yaml.org,2002:float", _construct_float)


def load_all(text: str):
    return list(yaml.load_all(text, Loader=Loader12))
