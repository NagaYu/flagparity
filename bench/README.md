# bench/ — Phase 1 dev bench (not sealed; meant to be publishable after a licence review)

| file | role |
|---|---|
| `cases.json` | frozen cases (class, label, origin real/constructed, route, source repo/path/commit/sha256, rationale; F4 positives carry `expected_pairs`) and the clean set |
| `files/real/` | copies of Phase 0 census files (third-party public files, sha256 names) |
| `files/constructed/` | real files with one injected defect (`mutation` and `derived_from` in the case) |
| `build.py`, `manual_cases.py` | deterministic builders (re-running reproduces `cases.json`) |
| `oracle.py` | independent F4 labeller = Phase 0 smoke code (not the verifier) |
| `census_run.py` | the verifier over all 634 census files (G1-5) |
| `run_bench.py` | Gate 1 measurement → `results/gate1.json` (+ `gate1.first-run.json`, the first measurement) |

```bash
python3 bench/run_bench.py
```

Routes and their independence from the verifier: `phase0-oracle` / `phase0-smoke` / `phase0-f3-scan` (Phase 0 code),
`declared` (facts readable from the file), `mutation` (label by construction), `detector+manual` (found by the
verifier, confirmed by reading — circular), `manual-negative` (read by hand). Results are broken down by route.
