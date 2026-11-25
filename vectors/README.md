# vectors/ — semantics fidelity (G1-1)

| file | role |
|---|---|
| `upstream/` | pinned third-party public sources, tests and docs (read as data; never executed). Licences were not checked in Phase 1 and differ per project — review before publishing this directory |
| `flagd_testbed.py` | runs the official flagd-testbed Gherkin scenarios (applicability rule DECISIONS P1-Z-2) |
| `flipt_vectors.py` | Flipt Go/Rust test tables (extracted mechanically) + hand-transcribed evaluator vectors (file:line each) |
| `goff_vectors.py` | GOFF unit-test cases and rules-library query tests — supplementary only; GOFF stays `source-only` |
| `run_vectors.py` | writes `fidelity.json`, which the verifier attaches to every verdict |
| `partb_spec_reference.py` | Part B: the flagd spec page's printed reference code run against the testbed |

```bash
python3 -I vectors/run_vectors.py
```

## Adding a semantics version

1. Add a module in `flagparity/semantics/` (or an instance in an existing one) that calls `register(Semantics(...))`
   with a new `id`, `order`, pinned `sources`, `vector_suites`, and an `impl` exposing the format's hook
   (`fractional(values, data)` for flagd, `edges()/variant_index()/threshold_hit()` for Flipt,
   `percentage(name, key, pcts)` for GOFF). The registry auto-discovers modules.
2. Add its vector suite to the format's runner and re-run `run_vectors.py`.
3. Nothing in `classes.py` changes: F4 compares every registered pair of the format. (Phase 1 added
   `goff/pre-v1.32` this way.) Known seams that do name a version: flagd condition scanning evaluates a
   fractional inside a *condition* with G3 (such conditions are marked not-judgeable anyway), and the F2
   evidence text for Flipt quotes the legacy shares.
