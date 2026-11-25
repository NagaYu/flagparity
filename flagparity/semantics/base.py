"""Semantics registry primitives.

A *semantics* is one (format, version/engine) evaluation behaviour reconstructed from pinned public
source. The verifier core never names a concrete version: it asks the registry for every semantics of
a format and compares them pairwise. Adding a version = adding one module that appends a Semantics
instance to SEMANTICS, plus its vector suite under vectors/ (see vectors/README.md).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Semantics:
    id: str                 # stable id, e.g. "flagd/G3"
    format: str             # "flagd" | "flipt" | "goff"
    label: str              # human label with version range
    order: int              # chronological order within the format (for transition naming)
    kind: str               # "version" (same engine, different release) | "engine"
    sources: tuple          # pinned public sources the behaviour was read from
    vector_suites: tuple = field(default=())   # suite ids that verify this semantics
    vectors_declared_official: bool = True     # False => fidelity is source-only by pre-registration
    impl: object = None     # format-specific implementation object


_REGISTRY = []


def register(sem: Semantics):
    if any(s.id == sem.id for s in _REGISTRY):
        raise ValueError("duplicate semantics id %s" % sem.id)
    _REGISTRY.append(sem)
    return sem


def all_semantics():
    return sorted(_REGISTRY, key=lambda s: (s.format, s.order, s.id))


def for_format(fmt):
    return [s for s in all_semantics() if s.format == fmt]


def get(sem_id):
    for s in _REGISTRY:
        if s.id == sem_id:
            return s
    raise KeyError(sem_id)
