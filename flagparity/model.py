"""Format-neutral flag model consumed by the class checks (flagparity/classes.py)."""
from dataclasses import dataclass, field
from typing import Callable, Optional


class NotJudgeable(Exception):
    pass


@dataclass
class Leaf:
    id: str
    label: str
    explicit: bool            # an authored rule/branch (F1 candidates); False = implicit fall-through
    kind: str                 # variant | alloc | default | dynamic | multi | boolexpr | error
    variant: Optional[str] = None
    alloc_id: Optional[str] = None
    produces: tuple = ()      # for kind == multi (e.g. GOFF progressive rollout: initial/end)


@dataclass
class Alloc:
    id: str
    label: str
    rule_path: str
    entries: list              # [(variant name or raw value, declared weight or None)]
    compute: Optional[Callable] = None   # compute(sem, targeting_key) -> outcome label (str)
    nj_reason: Optional[str] = None      # set when assignment cannot be computed
    f2: list = field(default_factory=list)
    f2_nj: Optional[str] = None
    positive: tuple = ()       # variant names with positive weight (for F3)
    default_on_some_semantics: tuple = ()  # semantics ids where some buckets fall to the flag default
    evaluated: bool = True     # False: declared where the engine never evaluates it (F2 still checks the declaration)


@dataclass
class Reach:
    hits: set
    complete: bool
    reason: Optional[str]
    n_assignments: int
    outputs: dict = field(default_factory=dict)   # leaf id -> set of produced names (boolexpr leaves)
    engine_unreached: dict = field(default_factory=dict)  # engine -> explicit leaf ids no context reaches there (P3-Z-6 B-3b)


@dataclass
class FlagModel:
    key: str
    format: str
    variants: list
    variant_values: dict
    default_variant: Optional[str]
    has_mechanism: bool
    leaves: list
    allocs: list
    has_conditions: bool
    reach: Optional[Reach] = None
    disabled: Optional[str] = None
    time_dependent: Optional[str] = None
    f1_nj: Optional[str] = None
    f3_nj: Optional[str] = None
    f7: list = field(default_factory=list)
    f7_applicable: bool = True
    f7_na_reason: Optional[str] = None
    notes: list = field(default_factory=list)
    location: dict = field(default_factory=dict)
