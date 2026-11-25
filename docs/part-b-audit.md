# Part B — what the projects disclosed about assignment-changing releases

Audit date: 2026-11-25 (Phase 1; numbers re-checked with the current detector, after the Phase 3 fixes and the
owner's boundary decisions, where marked ✓). Sources are pinned
to a commit or tag. Source files, changelogs and doc sources were saved under `vectors/upstream/`; see the note at the
end for one page that was read but not saved. Web pages (release pages, docs.flipt.io, gofeatureflag.org, flagd.dev)
were read on the audit date.

"Assignment" means which variant a given user receives. All counts use FlagParity's fixed synthetic context set: 1000
contexts, `targetingKey` `user-0000`..`user-0999`.

## B-1 Three evaluation changes in the last 12 months and their disclosure

| # | Change | Release | Measured effect on assignments | What was disclosed | Verdict |
|---|---|---|---|---|---|
| 1 | flagd `fractional` G1 → G2 (integer bucketing, open-feature/flagd#1909) | flagd v0.15.0, 2026-04-01 | A 50/50 flag: 509/1000 contexts change variant. In the 634-file census, 144 of the 147 flagd flags with an F4 finding include the G1↔G2 pair ✓ (153 F4 findings across formats ✓; 18 further flagd flags, whose `fractional` feeds a condition or operator, are F4 not-judgeable by the owner's decision B-1 — Phase 1 counted them: 165 / 162 / 171) | The flagd changelog entry for 0.15.0 says assignments change and all providers must be updated; an ADR explains the precision change. **The `fractional` reference page does not mention v0.15.0**: it only has an undated sentence about earlier percentage weights | Disclosed in the changelog; **not on the reference page** |
| 2 | flagd `fractional` G2 → G3 (CBOR bucketing input, open-feature/flagd#2011) | flagd v0.18.0, 2026-10-15 | Same 50/50 flag: 521/1000 (52.1%) change variant | Changelog 0.18.0 mentions fractional re-assignment; the reference page says hashing changed in v0.18.0 and assignments may differ; the ADR describes re-bucketing all users | **Disclosed** |
| 3 | Flipt rollout normalisation (flipt-io/flipt#5581) | Flipt v2.9.0, 2026-04-22 | Changes assignments only for rules whose distributions do not sum to 100. Example: flipt-io/flipt-test-corpus `venus/features.yml` flag `flag_no_distribution` (rollouts 10/20): 904/1000 contexts change between the legacy servers and v2.9+ ✓. Rules summing to 100 are unchanged | The v2.9.0 changelog lists it under "Changed" as a normalisation for more consistent rollouts. The PR describes the boundary computation. Neither says that assignments change, or that the remainder used to fall to the default before. No breaking-change label; nothing on the release page; the v2 concepts docs do not discuss sums other than 100 | **Not disclosed** |

- Outside the 12-month window, for reference: GO Feature Flag v1.32.0 (2024-07-25, thomaspoignant/go-feature-flag#2136)
  normalises percentages. Its current docs (percentage rollout page, v1.59.1) say percentages need not sum to 100.
  The earlier behaviour was an evaluation error for sums other than 100 (v1.31.2 source); whether the docs recorded
  that change was not checked.
- Terminology: the flagd ADR's "100% of users are re-bucketed" means every user's hash input changes. It does **not**
  mean every user gets a different variant. For two variants at 50/50 the measured change is 52.1%; in general it is
  about 1 − Σ pᵢ².

## B-2 Documented evaluation semantics vs. measured behaviour

| # | What the documentation says | Measured (against the official test vectors) | Gap |
|---|---|---|---|
| 1 | flagd "Fractional Operation Specification" page (flagd/v0.19.0). The text specifies integer weights, negative weights as 0, and CBOR input since v0.18. The page's flowchart and its Go reference code each describe a different algorithm (different default bucketing value, a different divisor, string-only input, integer division of `weight / sumOfWeights`) | The printed reference code, completed only where identifiers did not compile, was run against flagd-testbed. It fails 50/241 G1-applicable, 56/253 G2 and 158/354 G3 vectors. That is only 6 more passes than a `fractional` that always returns null (56/62/164). FlagParity's own G2/G3 implementations pass 253/253 and 354/354 | **Large**: text, diagram and reference code disagree. The reference code matches no generation, and its integer division makes almost every multi-variant split return null (`vectors/partb_spec_reference.py`, `.json`; re-run in Phase 3 with identical output ✓) |
| 2 | flagd ADR (CBOR): all users are re-bucketed | 52.1% change variant at 50/50; median 47.3% over the Phase 0 sample | Wording (see B-1) |
| 3 | flagd `fractional` page: earlier versions used percentage weights summing to 100 | The G1 source (b9c099cb) normalises by the total (`100*w/total`) and does not require 100; it truncates weights with `int()`, and a single-entry `fractional` returns nil | The page does not match the G1 implementation |
| 4 | Flipt docs (v2 concepts): nothing on sums other than 100 | Legacy: the remainder falls to the default (or the excess is dropped). v2.9+ and the Rust engine normalise; Rust rounds bucket edges with `round()`, Go truncates. 33.33/33.33/33.34 gives a 1-in-1000 Rust↔Go difference (one context in a public file) | Docs silent; assignments differ by version and engine |
| 5 | GO Feature Flag docs: sums need not be 100; normalised | The v1.32+ implementation matches GO Feature Flag's own unit tests (8 cases) and its rules library tests (168) | No gap for v1.32+ |
| 6 | Flipt: `rules` on a boolean flag, `rollouts` on a variant flag | No version or engine evaluates them (FlagParity F7-a / F7-e) | Whether the docs say they are ignored: not checked |
| 7 | GO Feature Flag: `percentage` and `variation` in one rule | `variation` is never evaluated (GO Feature Flag's own unit test asserts this) | Whether the docs say so: not checked |

## Notes and limits

- The GO Feature Flag documentation page cited in B-1 was read on the audit date, but its source was not saved under
  `vectors/upstream/`. That one item is not pinned locally.
- The Flipt v2.9.0 release page was read only in part: the fetch stopped at about 40k of 52k characters.
- Flipt v2.0–v2.8 were not checked tag by tag. The legacy behaviour is taken from v1.62.1, and v2 < v2.9.0 is assumed
  to share it.
