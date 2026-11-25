# FlagParity

**FlagParity is an offline, deterministic verifier for feature-flag definition files.** It reads flagd JSON, Flipt
`features.yml` and GO Feature Flag (v1 format) YAML files. It reports rules that can never fire, allocations whose
declared weights are not what the engine applies, variants that no path produces, users whose assignment changes
between engine versions, and settings that the engine silently ignores. Every finding carries the evidence needed to
reproduce it. No network, no clock, no flag service: the output depends only on the file bytes.

> Status: v1.0, the first public release of this repository.
> **Licence: proprietary, all rights reserved.** Evaluation use is permitted as described in `LICENSE` and below;
> licensing and transfer are available (see `LICENSE`). Until Phase 3 the project used the working name
> *FlagBound*; recorded results from that period (for example `bench/results/gate1*.json`) still carry it.

## What it checks

| Class | Finding | Notes |
|---|---|---|
| F1 | A rule / branch that no context can reach in any modelled engine (an earlier rule captures everything it matches, or its condition is unsatisfiable) | Decided by exhaustive evaluation over a finite witness set. When the set is not provably complete for the operators used, the verdict is `not-judgeable`, never `clean`. A rule unreachable in only some engines is `clean` with an info `engine_note` naming them |
| F2 | An allocation whose declared weights do not mean what they say | Flipt rule distributions not summing to 100, GO Feature Flag percentages not summing to 100, flagd negative / non-integer / all-zero weights |
| F3 | A variant that no reachable rule, positive-weight allocation or default produces, on a flag that has targeting or an allocation | Plain toggles are out of scope (`not-applicable`). A rule or default naming an undeclared variant is also reported |
| F4 | Users whose assignment differs between two modelled engine versions / engines | 1000 synthetic contexts (`targetingKey` `user-0000`..`user-0999`). Compares the variant the application receives. Output: per pair flips, flip rate and old→new breakdown. A flagd `fractional` whose value feeds a condition or operator is `not-judgeable` |
| F7 | Configuration the engine loads without error but never evaluates | Catalog only: Flipt rules on boolean flags, rollouts on variant flags; GOFF percentage+variation, progressiveRollout+others, `disable` on `defaultRule` |
| F5 | Mixed variant value types | Informational only |

Each verdict per flag × class is `detected`, `clean`, `not-applicable` or `not-judgeable`, and every `not-judgeable`
has a reason. Each file is `judged` or `not-judgeable` with a reason. No file is dropped silently.

### Semantics modelled

| Semantics id | Behaviour | Fidelity (official vectors applicable / passed) |
|---|---|---|
| `flagd/G1` | flagd ≤ v0.14 (float percentage bucketing) | 206 / 206 ¹ |
| `flagd/G2` | flagd v0.15–v0.17 (integer `(h*W)>>32`, string input) | 253 / 253 |
| `flagd/G3` | flagd ≥ v0.18 (integer, CBOR input) | 354 / 354 |
| `flipt/server-legacy` | Flipt v1.x and v2 < v2.9.0 (no normalisation) | 96 / 96 |
| `flipt/server-v2.9+` | Flipt v2 ≥ v2.9.0 (normalised) | 92 / 92 |
| `flipt/rust-client` | Flipt client engine (Rust) | 38 / 38 |
| `goff/v1.32+` | GO Feature Flag ≥ v1.32.0 (normalised) | 176 / 176 ² |
| `goff/pre-v1.32` | GO Feature Flag < v1.32.0 | source-only: no vectors; F4 verdicts using it carry a `fidelity_caveat` |

¹ flagd-testbed examples tagged `@fractional-v1` or not exercising `fractional` (owner calibration, see below).
² GO Feature Flag's own unit-test cases (8) plus the rules-library query tests (168) (owner calibration, see below).

YAML is decoded the way the engines' Go decoder does it (gopkg.in/yaml.v3 v3.0.1, pinned by both Flipt and GO Feature
Flag). Map keys and string fields keep the source text, bool fields accept `yes`/`no`/`on`/`off`, numbers follow
yaml.v3 (`012` is 10), and duplicate keys are a load error. flagd conditions follow diegoholiveira/jsonlogic v3.10.2,
the version flagd v0.19.0 pins.

## Usage

```bash
python3 -m flagparity check path/to/flags.json path/to/features.yml --out verdicts.json
```

The output schema is `flagparity.verdict/v1`. A versioned request form (`python3 -m flagparity request REQUEST.json`,
schema `flagparity.request/v1`) takes the file contents inline.

## How it was evaluated — and what the numbers do and do not say

The project ran pre-registered gates. The criteria were written down before any measurement, and the results were
recorded as produced. Calibrations were made only by the owner, after the failing measurement was recorded. The
evaluation record is summarised here. The internal decision log is not part of this export.

### Gate 1 — development bench (Phase 1): PASS after three owner-approved calibrations

Criteria: official-vector fidelity 100% where vectors exist; recall ≥ 0.95 overall and ≥ 0.90 per class; 0 false
positives on a clean set; F4 attribution (which version pair diverges) ≥ 0.90; byte-identical reruns; no silent drops.

| Step | What changed | Result |
|---|---|---|
| First measurement | — | **FAIL** on fidelity: `flagd/G1` 223/241 (the 18 failing examples are untagged `fractional` scenarios written for current flagd). Recall 0.980 (97/99), F2 0.909 |
| Two fixes made after the first measurement | detector: F2 also checks distributions declared on Flipt boolean flags; scoring: a key repeated in several YAML documents counts as detected if any instance is | recall 1.000 (99/99); the first-run file is kept (`bench/results/gate1.first-run.json`) |
| Calibration A (owner) | `flagd/G1` vectors limited to `@fractional-v1` examples and non-`fractional` scenarios | `flagd/G1` 206/206 → **PASS** |
| Calibration B (owner) | GO Feature Flag v1.32+ unit tests counted as official vectors | `goff/v1.32+` 176/176; `goff/pre-v1.32` stays source-only → PASS |
| Calibration C (owner) | two F4 negative labels moved to positives after reading the pinned G1 source (single-entry and all-zero `fractional`) | recall 101/101, attribution 20/20, clean set (12 files) 0 false positives → PASS |

Read this with care: most real bench positives are test fixtures or sample files. 47 of the 101 positives are
constructed (one injected defect). The real F1 examples were found by the detector itself (circular), and one
reviewer, the same AI model as the author, labelled the bench.

### Gate 2 — sealed holdout (Phase 2): PASS within an explicitly limited scope

> **Gate 2 = PASS (scope: F3/F4 gated on real files, F3 n=54, F4 n=26; F1 reported at n=0; F2/F7 unmeasured — no
> real positives in the census scope (406 census files from non-bench repos + 25 never-fetched files); supplementary
> blind mutations F2 n=12, F7 n=12 not used for pass/fail; clean set 45 real files)**

| Criterion (same bars as Gate 1) | Measured |
|---|---|
| Recall, F3 + F4 pooled ≥ 0.95, each ≥ 0.90 | pooled 79/80 = 0.988 (95% Clopper–Pearson lower bound 0.932); F3 53/54 = 0.981 (0.901); F4 26/26 = 1.000 (0.868) |
| Clean-set false positives = 0 | 0 on 45 real files, all classes |
| F4 attribution ≥ 0.90 | 25/26 = 0.962 (lower bound 0.804) |
| Determinism | two separate runs, identical bytes |
| No silent drops | 148 inputs = 148 judged + 0 not-judgeable |

The scope matters:

- **Data source.** The pre-registered sources (unread GitHub files, other forges, commits after the build date) gave
  only 25 new flagd files, all plain toggles. The owner then decided to use census files from repositories that the
  dev bench did not use. Phase 1 had run the detector once on those files, for its file accounting check.
- **Classes gated.** Only F3 and F4 had enough real positives. F1 had 0 real positives after manual review. F2 and F7
  had none in scope: their supplementary blind mutations were 12/12 each and did not count toward pass/fail.
- **Composition.** 41 of the 54 F3 cases and 19 of the 26 F4 cases come from sample, tutorial or provider
  repositories. All F4 cases are flagd; Flipt and GO Feature Flag F4 were not measured on real files.
- **Labelling.** Labels came from a mechanical pass and a manual pass, by the same AI model as the detector author, in
  a separate session that saw neither the detector code nor its output. There was no human second reviewer.
- **Misses.** The two misses (a bare-string `"targeting": "yes"`, and a `fractional` returning numeric names that are
  not variants) came from applying the definitions to provider fixtures for invalid configurations. Phase 3 settled
  both definitions (below). Gate 2 stays as measured on the pinned detector commit `1b8f1b6` and is not re-scored.
- **Holdout material.** The sealed files and labels are not published. `holdout/PUBLIC_MANIFEST.json` lists the
  sha256 and source URL of each of the 148 inputs.

### Phase 3 — adversarial fuzz and fix round

Two definition boundaries from Gate 2 were settled first and fixed before fuzzing. (1) A flagd `targeting` that is
any value other than absent / `null` / `{}` counts as a rule for F3, including a bare value. A bare value names the
result for every context. (2) F4 compares the variant the application receives: errors and missing defaults count as
one value, the code default.

The fuzz used 1,800 generated files (600 per format, fixed seed). The generator is weighted toward the known weak
points: bare targeting, numeric / boolean / null `fractional` names, semver prerelease constants, several `contains`
on one attribute, string ordering, and YAML 1.1/1.2 spellings and keys. Each file was checked by the detector and by
the independent Phase 2 checker.

| | mismatches |
|---|---|
| Pre-fix detector vs. original Phase 2 checker | 671 |
| … after fixing checker-side defects (same detector) | 407 |
| … after the detector fixes below | 43 (open definition boundaries) |
| … after the owner's decisions on those boundaries | **0** |

Detector defects found and fixed (fuzz mismatches removed by each):

1. **YAML read without the Go decoder's field rules** (164). `enabled: no` / `disable: off` were read as true,
   `default: yes` was missed, `true:` keys became `"True"` and could collide with `1:`, duplicate keys were accepted,
   and `012` was read as 12. Effects: wrong disabled state, false F7 reports, wrong F2/F3/F4 inputs.
2. **A flagd `defaultVariant` naming an undeclared variant was not reported** under F3 (11).
3. **The semver witness set lacked prerelease successors** (1). This could report a reachable `sem_ver` rule as
   unreachable (a false F1).
4. **The witness set lacked numeric values for string constants** (2). jsonlogic coerces `"" == 0` and
   `{"in": [0, ["silver"]]}` to true, so this could also cause a false F1.
5. **JSONLogic comparison, equality, `in` and truthiness** were aligned with jsonlogic v3.10.2 (null vs. number in
   `<=`, whitespace number strings, array equality, three-argument `>` / `>=`). This came from reading the source;
   no fuzz mismatch is attributable to it alone.
6. **A `fractional` that returns nil for some context was not counted as producing the defaultVariant** (12). With no
   explicit bucketing value, every flagd generation returns nil when the context has no `targetingKey`, and flagd
   then serves the default. F3 wrongly reported such defaults as never produced. These 12 cases were first filed as
   a definition boundary, and were found to be a defect when re-read for the owner's decision.

The two definition fixes removed 92 (bare targeting) and 98 + 1 (resolved-variant F4) mismatches. After the round,
the dev bench is unchanged (0 of 140 case rows changed; clean set still 0 false positives; official vectors still
100%).

The owner then decided the remaining boundaries. (a) A `fractional` whose value feeds a condition or operator makes
F4 `not-judgeable`. (b) A defaultVariant that no path returns is "not produced". (c) A GO Feature Flag flag whose
targeting rules are all `disable: true`, and whose default is a single variation, is out of scope for F3. (d) A rule
reachable in some engines only (Flipt's Go servers trim whitespace for `empty`; the Rust engine does not) is F1
`clean`, with an engine note. With these applied, and defect 6 fixed, the fuzz has **0 mismatches**. The dev bench
and the official vectors are unchanged.

### Field audit (Phase 3): detector run on the public population

Population: the 634 files counted in the Phase 0 census plus 25 files found later but never fetched before (659
files: 375 flagd, 145 Flipt, 139 GO Feature Flag; all judged). These counts are **unverified detector candidates,
not labels**.

| Files with ≥ 1 detection | F1 | F2 | F3 | F4 | F7 |
|---|---|---|---|---|---|
| Sample / tutorial / provider-derived (356 files) | 14 | 11 | 125 | 47 | 0 |
| Everything else (303 files) | 4 | 4 | 37 | 22 | 3 |
| … of which not under a test/fixture path and not from a dev-bench source repo (130 files) | **0** | **0** | **15** | **7** | **0** |

All F1, F2 and F7 detections in files that look like real use are in repositories already used as dev-bench sources.
**The public population has given no new real-use F1, F2 or F7 instance**, and those classes remain unmeasured in
the wild. A hand reading of five non-sample representatives found all five detections correct under the
definitions: an F1 rule fully subsumed by an earlier rule, an F1 dead `else` branch, an F3 variant no path
returns, an F3 variant with weight 0, and an F4 10/90 `fractional` that diverges between flagd generations.

## Not claimed

- No measured real-world precision or recall for F1, F2 or F7 (see above). No F4 measurement on real Flipt or GO
  Feature Flag files.
- `goff/pre-v1.32` is reconstructed from source only.
- Flipt v2.0–v2.8 tags were not checked one by one; flagd operators other than `fractional` are modelled with one
  behaviour (v0.19.0) for all generations.
- F4 uses synthetic contexts: it shows that assignments *can* change for those users, not how many of your users are
  affected.

## Reproducing

```bash
python3 -I scripts/fetch_third_party.py          # third-party inputs listed in third_party_manifest.json
python3 bench/build.py && python3 bench/manual_cases.py   # rebuilds bench/files (byte-identical)
python3 -I vectors/run_vectors.py                # official vector suites -> vectors/fidelity.json
python3 bench/run_bench.py                       # Gate 1 measurement
python3 -I fuzz/gen.py fuzz/cases --seed 20261125 --per-format 600   # the Phase 3 fuzz inputs
python3 field/field_audit.py --detector . --out field/results/field.json
```

The vector suites need the Flipt sources and flagd-testbed files that the fetch script downloads. The fuzz
comparison itself needs the Phase 2 checker, which belongs to the sealed holdout and is not published; its results are
summarised in `fuzz/results/SUMMARY.json`.

## Licence and evaluation use

FlagParity is proprietary (all rights reserved); see `LICENSE`. You may read it, run it on your own machines and
reproduce the evaluation above, solely to assess it for a licence or transfer. Production use, redistribution and
publishing modified versions need a separate written licence. Licensing and transfer are available: contact via
the link in `LICENSE`. Third-party files keep their own licences (`THIRD_PARTY.md`).

## Third-party material

See `THIRD_PARTY.md`. Upstream sources under permissive licences (flagd Apache-2.0; GO Feature Flag, flipt-client-sdks,
nikunjy/rules, jsonlogic MIT; go-yaml MIT/Apache-2.0) are included with their licence files. Flipt server sources
(GPL-3.0 at v1.62.1, Fair Core License at v2.14.2), flagd-testbed (no licence found) and all third-party flag files
are not included. They are listed with URL, commit and sha256 so they can be fetched.

## Primary sources

`docs/primary-sources.md` lists every upstream page and file the semantics were read from, pinned to a commit or tag.
`docs/part-b-audit.md` audits what the three projects disclosed about recent assignment-changing releases.
