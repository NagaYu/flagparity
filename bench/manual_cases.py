"""Manually reviewed real cases (read flag-by-flag during Phase 1 bench construction, 2026-11-25).
Appended to the cases produced by bench/build.py; then bench/cases.json is frozen (P1-C-5)."""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import build  # noqa: E402
import oracle  # noqa: E402
# Phase 3: the frozen Phase 1 loader (git 1b8f1b6:flagbound/yaml12.py), so rebuilding reproduces the frozen bench bytes
import yaml12_phase1 as yaml12  # noqa: E402

INV = build.INV

# (class, label, repo, path, flag, route, rationale)
MANUAL = [
    # ---- F1 positives (detector+manual: surfaced by the Phase 1 detector, confirmed by reading) ----
    ("F1", "positive", "EconGraph/econ-graph", "scripts/check-flags/test/fixtures/build-with-targeting/flags.flagd.json", "build_canary",
     "detector+manual", "targeting if[true, 'on', 'off']: the else branch can never be taken"),
    ("F1", "positive", "kyma-project/cloud-manager", "pkg/feature/ff_ga.yaml", "apiDisabled", "detector+manual",
     "rule 9 (feature == rediscluster and provider == alicloud) is subsumed by rule 3 (feature == rediscluster), which comes first"),
    ("F1", "positive", "jordanwallwork/flagon", "tests/Jorrk.Flagon.Tests/FlagdParity/testbed/flags/custom-ops.json",
     "equal-greater-lesser-version-flag", "detector+manual",
     "last branch compares with '2.0.0.0', not a valid semver: sem_ver returns null for every context, so 'fail' is never returned"),
    ("F1", "positive", "jordanwallwork/flagon", "tests/Jorrk.Flagon.Tests/FlagdParity/testbed/flags/edge-case-flags.json",
     "missing-variant-targeting-flag", "detector+manual", "if[true, 'three', 'one']: else unreachable"),
    ("F1", "positive", "jordanwallwork/flagon", "tests/Jorrk.Flagon.Tests/FlagdParity/testbed/flags/edge-case-flags.json",
     "non-string-variant-targeting-flag", "detector+manual", "if[true, true, false]: else unreachable"),
    ("F1", "positive", "blitzy-showcase/flipt", "internal/ext/testdata/export.yml", "flag1", "detector+manual",
     "rule 2 requires segment1 AND segment2; rule 1 already matches every segment1 context"),
    ("F1", "positive", "blitzy-showcase/flipt", "core/validation/testdata/valid_zero_values.yaml", "test_boolean_flag",
     "detector+manual", "threshold rollouts at 0% and 0.0%: crc32 % 100 < 0 never holds"),
    ("F1", "positive", "gitbito/flipt", "internal/oci/testdata/default.yml", "flag_boolean", "detector+manual",
     "threshold rollouts 6 and 7 at 0% / 0.0%: never match"),
    # ---- F1 negatives ----
    ("F1", "negative", "1fanwang/airflow-provider-openfeature", "system_tests/flags/flags.json", "airflow.task.pool",
     "manual-negative", "Phase 0 hand check: dag_id in list -> canary, otherwise default; both branches reachable"),
    ("F1", "negative", "1fanwang/airflow-provider-openfeature", "system_tests/flags/flags.json", "airflow.rollout.ready",
     "manual-negative", "same shape: both branches reachable"),
    ("F1", "negative", "BenAychh/ff-test", "flags.goff.yaml", "test-flag-1", "manual-negative", "firstname eq \"Giang\" is satisfiable"),
    ("F1", "negative", "quarkiverse/quarkus-openfeature", "integration-tests/flipt/src/main/resources/features.yaml",
     "targeted-flag", "manual-negative", "single rule on segment test-users (userType eq tester): reachable"),
    ("F1", "negative", "ministryofjustice/hmpps-feature-flags", "tests/fixtures/flags/test/smoke-test/features.yml",
     "template-version", "manual-negative", "single rule on smoke-testers (team eq smoke): reachable"),
    ("F1", "negative", "eccentricnode/landan_mymove", "config/flipt/storage/development.features.yaml", "multi_variant",
     "manual-negative", "rule 1 mil-app (applicationName eq mil), rule 2 all-entities: rule 2 reachable for other applications"),
    ("F1", "negative", "aliykh/docker-kubernetes", "features/feature.yaml", "local-feature-flag", "manual-negative",
     "env eq production / env eq local: both satisfiable, disjoint"),
    ("F1", "negative", "TencentBlueKing/bkmonitor-datalink", "pkg/unify-query/featureFlag.yaml", "new-query", "manual-negative",
     "name in [...] is satisfiable"),
    # ---- F3 positives (Phase 0 f3_static_scan route, confirmed under the P1-B-1 definition) ----
    ("F3", "positive", "agardnerIT/OddFiles", "flagd.flags.json", "fibAlgo", "phase0-f3-scan",
     "targeting if[$ref emailWithFaas, 'binet', null]: 'memo' and 'loop' are never produced"),
    ("F3", "positive", "davidaparicio/microsvcs", "color/demo-flags.goff.yaml", "color-box", "phase0-f3-scan",
     "defaultRule percentage over green/red/default only: 8 other variations never produced"),
    ("F3", "positive", "davidaparicio/microsvcs", "projects/blue/demo-flags.goff.yaml", "color-box", "phase0-f3-scan",
     "percentage blue/default only: the other variations never produced"),
    ("F3", "positive", "eccentricnode/landan_mymove", "config/flipt/storage/development.features.yaml", "multi_variant",
     "phase0-f3-scan", "rules produce 'one' and 'two'; 'three' is never produced (no default variant)"),
    ("F3", "positive", "feliperromao/flipt-scm", "default/features.yaml", "email_v2", "phase0-f3-scan",
     "rule without distributions and no default variant: the only variant 'default' is never returned"),
    ("F3", "positive", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json", "ends-with-wrong-args-flag",
     "phase0-f3-scan", "ends_with with one argument always yields null -> 'fallback'; 'true'/'false' never produced"),
    ("F3", "positive", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json", "semver-invalid-operator-flag",
     "phase0-f3-scan", "operator '===' is not a sem_ver operator: always null -> 'fallback'"),
    ("F3", "positive", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json",
     "no-default-flag-null-targeting-variant", "phase0-f3-scan", "returns 'special' or null with no defaultVariant: 'normal' never produced"),
    ("F3", "positive", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json", "boolean-targeted-zero-flag",
     "phase0-f3-scan", "if[is_ballmer, 'zero'] with default 'zero': 'non-zero' never produced"),
    ("F3", "positive", "quarkiverse/quarkus-openfeature", "integration-tests/flipt/src/main/resources/features.yaml",
     "string-flag", "manual-negative-review", "rule everyone -> greeting 100%, no default: 'parting' never produced (found while reviewing a clean-set candidate)"),
    # ---- F3 negatives ----
    ("F3", "negative", "alexandrainst/plana-app-flags", "default_flags.flagd.json", "allowDebug", "manual-negative",
     "targeting is a boolean expression: result true -> variant 'true', false -> 'false' (Phase 0 scan mislabelled it a ghost)"),
    ("F3", "negative", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json", "ends-with-non-string-flag",
     "manual-negative", "ends_with on a string attribute yields true/false; absent/non-string -> null -> fallback: all three produced"),
    ("F3", "negative", "fireflyframework/fireflyframework-php",
     "packages/feature-flags/tests/Conformance/testbed/evaluator/flags/testkit-flags.json", "starts-with-non-string-flag",
     "manual-negative", "same as ends-with: all three produced"),
    ("F3", "negative", "1fanwang/airflow-provider-openfeature", "system_tests/flags/flags.json", "airflow.task.pool",
     "manual-negative", "canary via the branch, default via else"),
    ("F3", "negative", "quarkiverse/quarkus-openfeature", "integration-tests/flipt/src/main/resources/features.yaml",
     "targeted-flag", "manual-negative", "targeted-value via rule, default-value as default"),
    ("F3", "negative", "ministryofjustice/hmpps-feature-flags", "tests/fixtures/flags/test/smoke-test/features.yml",
     "template-version", "manual-negative", "v2 via rule, v1 default"),
    ("F3", "negative", "BenAychh/ff-test", "flags.goff.yaml", "test-flag-1", "manual-negative", "enabled via rule, disabled default"),
    ("F3", "negative", "aliykh/docker-kubernetes", "features/feature.yaml", "local-feature-flag", "manual-negative",
     "both variations produced by rules and default percentage"),
    # ---- F7 ----
    ("F7", "positive", "defnotalexrios/mmd", "flipt/features.yaml", "enable-redis-cache-rollout", "phase0-smoke",
     "Phase 0 example: BOOLEAN_FLAG_TYPE with rules (on: 10) that no Flipt engine evaluates"),
    ("F7", "positive", "dev-alxv/openfeature-flipt-angular", "flipt/features.yml", "newHomeUI", "detector+manual",
     "BOOLEAN_FLAG_TYPE flag carrying rules"),
    ("F7", "positive", "dev-alxv/openfeature-flipt-angular", "flipt/features.yml", "newRevenueChart", "detector+manual",
     "BOOLEAN_FLAG_TYPE flag carrying rules"),
    ("F7", "negative", "tadoku/tadoku", "k8s/dev/base/flipt/features.yaml", "release-webv3", "manual-negative",
     "boolean flag with rollouts only"),
    ("F7", "negative", "ministryofjustice/hmpps-feature-flags", "tests/fixtures/flags/test/smoke-test/features.yml",
     "segmented-flag", "manual-negative", "boolean flag with rollouts only"),
    ("F7", "negative", "aliykh/docker-kubernetes", "features/feature.yaml", "local-feature-flag", "manual-negative",
     "GOFF rules use either percentage or variation, never both; defaultRule not disabled"),
    ("F7", "negative", "TencentBlueKing/bkmonitor-datalink", "pkg/unify-query/featureFlag.yaml", "new-query", "manual-negative",
     "percentage-only rules"),
    ("F7", "negative", "quarkiverse/quarkus-openfeature", "integration-tests/flipt/src/main/resources/features.yaml",
     "targeted-flag", "manual-negative", "variant flag with rules only"),
]

CLEAN_SET = [
    ("1fanwang/airflow-provider-openfeature", "system_tests/flags/flags.json", "Phase 0 hand check (smoke 3)"),
    ("1fanwang/airflow-provider-openfeature", "system_tests/flags/gates_flags.json", "3 flags, dag_id/cluster_id in list -> on/off, both reachable, all variants used"),
    ("BenAychh/ff-test", "flags.goff.yaml", "one rule + default, both variations used"),
    ("alexcardell/openfeature-scala", "docker/flipt/features.yaml", "single-variant flags, each produced by its 100% rule; boolean toggle"),
    ("ministryofjustice/hmpps-feature-flags", "tests/fixtures/flags/test/smoke-test/features.yml", "toggles, one segment rollout, one rule v2 + default v1"),
    ("DE0CH/yyc-code", "news-stream/deploy/apps/flags/flags.json", "host in list -> on/off; other flags toggles"),
    ("Dynatrace/openfeature-provider-dotnet", "test/Dynatrace.OpenFeature.Tests/Resources/flag-config.json", "toggles + one email == rule with on/off"),
    ("EconGraph/econ-graph", "scripts/check-flags/test/fixtures/bad-key/flags.flagd.json", "toggles + roles contains preview:access -> on/off"),
    ("GeorgeT7/advanced-waitlist", "apps/backend/flags.flagd.json", "two emailDomain == rules with on/off"),
    ("MichaelKohler/flags", "tv-tracker-staging/default/features.yaml", "boolean toggles and 100% threshold rollouts"),
    ("TencentBlueKing/bkmonitor-datalink", "pkg/unify-query/featureFlag.yaml", "one rule (percentage 100/0) + default (0/100), sums 100"),
    ("aliykh/docker-kubernetes", "features/feature.yaml", "two disjoint rules + default percentage, sums 100"),
]


def find(repo, path):
    rs = [r for r in INV if r["repo"] == repo and r["path"] == path]
    if len(rs) != 1:
        raise SystemExit("not found uniquely: %s %s (%d)" % (repo, path, len(rs)))
    return rs[0]


def _assert_f7(r, flag):
    for d in yaml12.load_all(build.text(r)):
        for f in (d or {}).get("flags") or []:
            if f.get("key") == flag:
                assert f.get("type") == "BOOLEAN_FLAG_TYPE" and f.get("rules"), flag
                return
    raise AssertionError(flag)


def main():
    build.build_f4()
    build.build_f2()
    build.build_constructed()
    have = {(c["class"], c["source"]["sha256"] if c["origin"] == "real" else c["file"], c["flag"]) for c in build.CASES}
    # Phase 0 named examples
    p0 = [("F4", "positive", "1fanwang/airflow-provider-openfeature", "system_tests/flags/ab_flags.json", "ml.ranking_model",
           "Phase 0 smoke 2 (52.1% G2->G3 flips)"),
          ("F2", "positive", "blitzy-showcase/flipt", "core/validation/testdata/invalid.yaml", "flipt", "Phase 0 smoke 1 (rollout 110%)")]
    for cls, label, repo, path, flag, why in p0:
        r = find(repo, path)
        if (cls, r["sha256"], flag) not in have:
            pairs = oracle.flagd_pairs(build.census_path(r), flag) if cls == "F4" else None
            build.add_real(r, cls, label, flag, "phase0-smoke", why, pairs)
            have.add((cls, r["sha256"], flag))
        else:
            for c in build.CASES:
                if c["class"] == cls and c["origin"] == "real" and c["source"]["sha256"] == r["sha256"] and c["flag"] == flag:
                    c["route"] = "phase0-smoke"
                    c["rationale"] = why + "; " + c["rationale"]
    for cls, label, repo, path, flag, route, why in MANUAL:
        r = find(repo, path)
        if cls == "F7" and label == "positive" and repo != "defnotalexrios/mmd":
            _assert_f7(r, flag)
        if (cls, r["sha256"], flag) in have:
            continue
        build.add_real(r, cls, label, flag, route, why)
        have.add((cls, r["sha256"], flag))
    # DECISIONS P1-Z-7 (owner decision C): two oracle-labelled negatives were wrong; relabelled from source reading
    relabel = {"F4-neg-002": ("F4-pos-019", "G1 (flagd@b9c099cb fractional.go L55-L56) rejects a one-entry fractional "
                              "('length under 2') -> nil -> defaultVariant; G2/G3 return 'single'"),
               "F4-neg-003": ("F4-pos-020", "all weights 0: G1 returns \"\" (L147), not a variant -> error; "
                              "G2/G3 return nil (totalWeight 0) -> defaultVariant")}
    for c in build.CASES:
        if c["id"] in relabel:
            new_id, why = relabel[c["id"]]
            c.update(former_id=c["id"], id=new_id, label="positive", route="source-reading",
                     expected_pairs=["flagd/G1 ~ flagd/G2", "flagd/G1 ~ flagd/G3"],
                     rationale=why + " (relabelled by owner decision P1-Z-7; Phase 0 oracle simplified G1)")
    clean = []
    for repo, path, why in CLEAN_SET:
        r = find(repo, path)
        build.REAL_FILES[r["sha256"]] = r
        clean.append({"file": "files/real/%s%s" % (r["sha256"], build.ext(r)), "source": build.src_of(r), "rationale": why})
    build.write()
    out = {"schema": "flagbound.devbench/v1", "frozen": "2026-11-25 (before the Gate 1 measurement run); two labels corrected by owner decision P1-Z-7",
           "contexts": "D-6", "cases": build.CASES, "clean_set": clean}
    with open(os.path.join(build.B, "cases.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    from collections import Counter
    print(sorted(Counter((c["class"], c["label"], c["origin"]) for c in build.CASES).items()))
    print("clean set", len(clean))


if __name__ == "__main__":
    main()
