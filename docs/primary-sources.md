# 一次資料（Phase 0, 2026-11-25 取得）

ソースコードは GitHub API（`gh api .../contents?ref=`）で取得したタグ／コミット固定の版を読んだ。URL は `https://github.com/<owner>/<repo>/blob/<ref>/<path>` 形式で記す。

## S1. flagd — fractional（KT-4, F4）

| ID | 資料 | 要点 |
|---|---|---|
| S1-1 | https://flagd.dev/reference/custom-operations/fractional-operation/ | 「Hashing changed in flagd v0.18.0」と明記。既定バケット値は配列 `[flagKey, targetingKey]`、murmur3、整数演算、重み合計上限 MaxInt32。「Previous versions … percentage-based weights that had to sum to 100 … 1% precision」。 |
| S1-2 | https://flagd.dev/reference/specifications/custom-operations/fractional-operation-spec/ | 本文は CBOR 符号化＋[flagKey,targetingKey] を規定。**同ページのフローチャートと Go 参照実装は旧（G1）意味論のまま**（`int(hashRatio*100)`、文字列のみ、整数除算 `(dist.weight / sumOfWeights) * 100`）。公称仕様ページ内部で新旧が混在 = Part B 監査の実例候補。 |
| S1-3 | https://github.com/open-feature/flagd/blob/main/docs/architecture-decisions/fractional-non-string-rand-units.md | ADR（accepted, 2025-08-21 作成／2025-12-03 更新）。CBOR（RFC 8949 §4.2.1 Core Deterministic）で符号化、数値正規化規則、既定入力は `[flagKey, targetingKey]` の CBOR 配列（文字列連結ではない）。「breaking behavioral change for 100% of the users due to rebucketing」。 |
| S1-4 | https://github.com/open-feature/flagd/blob/main/docs/architecture-decisions/high-precision-fractional-bucketing.md | `bucket = (uint64(hash) * totalWeight) >> 32`、重み合計 ≤ MaxInt32。各言語の符号なし扱い表。 |
| S1-5 | https://github.com/open-feature/flagd/blob/b9c099cb7fa002a509a82c81b467f5e784c27e82/core/pkg/evaluator/fractional.go | **G1**（flagd ≤ v0.14.x）: `int32(murmur3.StringSum32(flagKey+targetingKey))` → `abs/MaxInt32*100` の浮動小数バケット、重みは百分率に換算して累積。 |
| S1-6 | https://github.com/open-feature/flagd/blob/0c5b766d365676e413ff31044a9d02ad83b356cc/core/pkg/evaluator/fractional.go （tag flagd/v0.17.1） | **G2**（v0.15.0〜v0.17.x）: 文字列連結 `flagKey+targetingKey` の murmur3、整数バケット `(h*W)>>32`。G1→G2 は commit 7190878fd0「feat!: fractional bucketing improvements (#1909)」2026-04-01。 |
| S1-7 | https://github.com/open-feature/flagd/blob/ac826d8e9cf3f5b14ad56f6e9eeeb981f45321eb/core/pkg/evaluator/fractional.go （tag flagd/v0.18.0） | **G3**（v0.18.0〜）: `fxamacker/cbor` CoreDetEncOptions で符号化し `murmur3.Sum32`。commit 0e344d2d49「feat!: bucket on any context type; (fractional re-assignment) (#2011)」2026-10-15。 |
| S1-8 | https://github.com/open-feature/flagd-testbed/blob/7690b5485760314d33b0e505754c1d1788fc3dd6/gherkin/targeting.feature ＋ flags/custom-ops.json | 公式適合テスト。`@fractional-v1`/`-v2`/`-v3` タグ付き期待値（v1=G1, v2=G2, v3=G3）。本 Phase の再実装は **37/37 件一致**（`smoke/lib/verify_testbed.py`）。 |
| S1-9 | https://github.com/open-feature/flagd/releases | flagd/v0.15.0 2026-04-01、v0.17.1 2026-10-15、v0.18.0 2026-10-15、v0.19.0 2026-11-17。 |

## S2. Flipt — distributions / rollouts（KT-4, F2, F4）

| ID | 資料 | 要点 |
|---|---|---|
| S2-1 | https://github.com/flipt-io/flipt/blob/v1.62.1/internal/server/evaluation/legacy_evaluator.go | v1 系: `crc32.ChecksumIEEE(flagKey+entityId) % 1000`、累積バケットは `int(rollout*10)` を**正規化せず**加算。バケットが累積外なら `Match=false` で**後続規則を見ずに return**（残余は既定へ）。 |
| S2-2 | https://github.com/flipt-io/flipt/blob/v2.14.2/internal/server/evaluation/evaluation.go | v2 系（≥ v2.9.0）: `normalizedRollout = rollout/totalRollout*100`、最終バケットを 1000 に固定（＝合計≠100 を暗黙に正規化）。boolean の threshold は `crc32(entityId+flagKey) % 100 < percentage`（連結順が variant と逆）。 |
| S2-3 | https://github.com/flipt-io/flipt/pull/5581 | 「fix: normalize rollout distribution buckets」2026-03-19 merge。「Port rollout bucket logic from Rust client」。v2.8.0 には含まれず v2.9.0（2026-04-22）から。→ **Flipt サーバ v1.x／v2 < 2.9 と v2 ≥ 2.9 で、合計≠100 の規則の実効割当が異なる**。 |
| S2-4 | https://github.com/flipt-io/flipt-client-sdks/blob/19e546523ed82a49123b681d086fadbe07833e78/flipt-evaluation/src/lib.rs | クライアント側 Rust エンジン: 正規化あり、ただしバケット境界を `.round()`（Go サーバは `int()` 切り捨て）。3分割等で境界が 1/1000 ずれる＝エンジン間乖離。 |
| S2-5 | https://github.com/flipt-io/flipt/blob/v2.14.2/core/validation/flipt.cue ＋ extended.cue ＋ validate.go | `flipt validate` は CUE スキーマ検証（`rollout: >=0 & <=100` 等）。合計・到達可能性の検査なし。 |
| S2-6 | https://github.com/flipt-io/flipt/blob/v2.14.2/internal/storage/fs/snapshot.go （L421, L455, L550） | ロード時に「rule references unknown segment」「rule references unknown variant」で拒否（F3 の下位ケース＝未定義バリアント参照）。 |
| S2-7 | https://github.com/flipt-io/flipt/blob/v1.62.1/internal/server/evaluation/legacy_evaluator_test.go, …/v2.14.2/internal/server/evaluation/evaluation_test.go | 再実装の照合に使ったテスト期待値 5 件（**5/5 一致**）。 |
| S2-8 | https://github.com/flipt-io/validate-action | Flipt 公式 GitHub Action。`flipt validate` のラッパ（スキーマ検証）。 |

## S3. GO Feature Flag（KT-1, KT-4）

| ID | 資料 | 要点 |
|---|---|---|
| S3-1 | https://github.com/thomaspoignant/go-feature-flag/blob/v1.59.1/modules/core/utils/hash.go | `BuildHash = fnv1a32(flagName+bucketingKey) % maxPercentage`。 |
| S3-2 | https://github.com/thomaspoignant/go-feature-flag/blob/v1.59.1/modules/core/flag/rule.go | `maxPercentage = uint32(sum*1000)`（合計≠100 は暗黙正規化）、バリエーション名をソートし**逆順**に累積（「legacy format … True before False」のための HACK とコメント）。 |
| S3-3 | https://github.com/thomaspoignant/go-feature-flag/blob/v1.59.1/modules/core/flag/internal_flag.go （`IsValid`） | ロード時検証: 全バリエーション同型（**F5 そのもの**）、default rule 必須、規則名重複。 |
| S3-4 | https://github.com/thomaspoignant/go-feature-flag/blob/v1.59.1/modules/core/flag/rule_validation.go | 未定義バリエーション参照を拒否（F3 下位ケース）。百分率は「空でない・負でない・合計 0 でない・合計×1000 が uint32 に収まる」のみ。**合計≠100 は拒否しない**。 |
| S3-5 | https://pkg.go.dev/github.com/thomaspoignant/go-feature-flag/cmd/lint ／ https://pkg.go.dev/github.com/thomaspoignant/go-feature-flag/examples/lint_flag_programmatically | 公式 linter（`go-feature-flag-lint`、現在は `go-feature-flag-cli lint`）。中身は DTO 変換＋`IsValid()`。 |
| S3-6 | https://github.com/thomaspoignant/go-feature-flag/blob/main/website/docs/concepts/retriever.mdx | 複数 retriever は指定順に適用、同名フラグは後勝ちで上書き（F6 の意味論、検出なし）。 |
| S3-7 | https://github.com/sarvsav/go-feature-flag-lint-action | 第三者 Action。GOFF linter のラッパ。 |

## S4. flagd — 検証・複数ソース（KT-1, F6）

| ID | 資料 | 要点 |
|---|---|---|
| S4-1 | https://github.com/open-feature/flagd/blob/flagd/v0.19.0/core/pkg/evaluator/json.go （L533–L615） | ロード時: JSON Schema 検証（flagd-schemas）＋ `validateDefaultVariants`（defaultVariant が variants に存在するか。F3 下位ケース）。 |
| S4-2 | https://github.com/open-feature/flagd-schemas/blob/b65e5403fc5fa96f5f026cd6b04f1165d275be36/json/flags.json | `anyFlag` = boolean/string/number/objectFlag の oneOf → 型混在はスキーマで不合格（スキーマ検証なので KT-1 では数えない）。`flagsArray` 形式も定義。 |
| S4-3 | https://flagd.dev/concepts/syncs/ | 複数ソースは定義順で後勝ちマージ（「the latest defined source taking precedence」）。 |
| S4-4 | https://github.com/open-feature/flagd/blob/main/docs/architecture-decisions/duplicate-flag-keys.md | `flags` の配列形式と `(flagKey, flagSetId)` 複合キー。 |
| S4-5 | https://github.com/open-feature/cli （internal/manifest/validate.go） | OpenFeature 公式 CLI。対象は OpenFeature **マニフェスト**形式（flagd 定義ではない）。JSON Schema＋ファイル内重複キー検出のみ。 |

## S5. KT-1/KT-3 探索記録（ツールが見つからなかったことの記録）

- WebSearch（2026-11-25）: "flagd flag definition linter validate semantic unreachable targeting rule"／"go-feature-flag-lint CLI validate flag configuration file"／"feature flag config linter open source OpenFeature flagd Flipt GO Feature Flag cross-format lint"／"LaunchDarkly OR Harness free tool lint flagd OR Flipt OR \"GO Feature Flag\" flag configuration files semantic validation"／"feature flag configuration static analysis tool detect unreachable rules percentage rollout not summing to 100"。横断形式の意味論 lint は検出されず。近いもの: Datadog Evaluation Tester（https://docs.datadoghq.com/feature_flags/concepts/evaluation_tester/ — Datadog 自社フラグの UI 上で後段規則を skipped 表示。対象3形式ではない）、Labelbox の LaunchDarkly policy linter（タグ・説明の有無）、Uber Piranha（コード側の stale flag 削除）。
- `gh search repos`: "flagd lint" "flagd validate" "flipt lint" "flipt validator" "go-feature-flag lint" "feature flag lint" "feature flag linter" "featureflag linter" "openfeature lint" "flag definition validator" → 該当は flipt-io/validate-action（スキーマ）、sarvsav/go-feature-flag-lint-action（GOFF linter ラッパ）のみ。

## S6. 買い手・コンプ（Step 4）

| ID | 資料 | 要点 |
|---|---|---|
| S6-1 | https://openai.com/index/vijaye-raji-to-become-cto-of-applications-with-acquisition-of-statsig/ | OpenAI 公式発表（2025-09-02）。Statsig 買収、Vijaye Raji が CTO of Applications。 |
| S6-2 | https://www.bloomberg.com/news/articles/2025-09-02/openai-to-buy-product-testing-startup-statsig-for-1-1-billion | 約 $1.1B、全株式。 |
| S6-3 | https://techcrunch.com/2025/09/02/openai-acquires-product-testing-startup-statsig-and-shakes-up-its-leadership-team/ | 同上。規制当局承認を含むクローズ条件。約 150 名が OpenAI へ。**クローズ完了の報道は今回の検索では見つからず**。 |
| S6-4 | https://www.datadoghq.com/about/latest-news/press-releases/datadog-acquires-eppo-to-expand-its-ai/ | Datadog 公式（2025-05-05）。条件非開示。 |
| S6-5 | https://techcrunch.com/?p=3002720 | Upstarts Media の「約 $220M」報道を引用。 |
| S6-6 | https://seekingalpha.com/news/4439188-datadog-buying-startup-eppo-for-220m-report | 「$220M - report」。 |
| S6-7 | https://www.dynatrace.com/news/blog/dynatrace-acquires-devcycle-to-strengthen-feature-delivery/ ／ https://blog.devcycle.com/devcycle-is-now-part-of-dynatrace/ ／ https://www.techtarget.com/searchitoperations/news/366637355/Dynatrace-DevCycle-buy-continues-observability-consolidation | Dynatrace が DevCycle を買収（2026-01 クローズ、条件非開示）。DevCycle は OpenFeature ベース。 |
| S6-8 | 同 TechTarget 記事 | 「OpenFeature, the CNCF standard for feature flagging, which Dynatrace helped establish」。 |
| S6-9 | https://techcrunch.com/2024/05/29/harness-snags-split-io-as-it-goes-all-in-on-feature-flags-and-experiments | Harness → Split.io（2024-05、非開示）。 |
| S6-10 | https://launchdarkly.com/blog/welcome-highlight-to-launchdarkly/ ／ https://www.techtarget.com/it-infrastructure/news/366619085/Users-eye-LaunchDarkly-experiments-boost-with-Houseware-buy | LaunchDarkly → Highlight（2025-04, 可観測性）、→ Houseware（2025-02, 倉庫ネイティブ分析）。いずれも非開示。 |
| S6-11 | https://github.com/open-feature/openfeature.dev/tree/6af08953512280585d36a33468d50661d60a65af/src/datasets/providers | OpenFeature エコシステムの provider 一覧（vendorOfficial フラグつき）。 |
| S6-12 | https://docs.flagsmith.com/integrations/importers/launchdarkly ／ https://configcat.com/docs/advanced/migration-from-launchdarkly/ ／ https://www.getunleash.io/blog/migrate-from-launchdarkly-to-unleash | 各社の取り込み導線は LaunchDarkly からのみ。flagd/Flipt/GOFF ファイルの取り込みは見つからず。 |

## S7. 名称（Step 5）

- GitHub: https://github.com/thisisajaikumar/Flagbound（Unity プロジェクト、説明なし）
- PyPI: https://pypi.org/pypi/flagbound/json → 404 ／ npm: https://registry.npmjs.org/flagbound → 404 ／ crates.io: https://crates.io/api/v1/crates/flagbound → 404
- https://flagbound.com → 「Launching Soon」(© 2026 flagbound.com)

## S8. Phase 1 で追加した一次資料（固定版を `vectors/upstream/` に保存）

| ID | 資料 | 用途 |
|---|---|---|
| S8-1 | open-feature/flagd-testbed@7690b548（v3.11.0）`gherkin/`, `evaluator/gherkin/`, `flags/`, `evaluator/flags/` | flagd G1–G3 の公式ベクタ（G1-1） |
| S8-2 | open-feature/flagd@flagd/v0.19.0 `core/pkg/evaluator/{json,semver,string_comparison,fractional}.go` | 変種解決・演算子の挙動 |
| S8-3 | flipt-io/flipt@v2.14.2 `internal/storage/fs/snapshot.go`, `core/validation/flipt.cue`, evaluation_test.go；@v1.62.1 evaluation.go, legacy_evaluator_test.go | Flipt のロード・評価・テスト表 |
| S8-4 | flipt-io/flipt-client-sdks@19e54652 `flipt-evaluation/src/lib.rs`（テスト含む） | Rust エンジンとテスト |
| S8-5 | thomaspoignant/go-feature-flag@v1.59.1 `modules/core/flag/{rule,rule_test,rule_validation,internal_flag,internal_flag_test}.go`；@v1.31.2 `internal/flag/{rule,internal_flag}.go` | GOFF v1.32 前後の意味論、F7-b/c/d |
| S8-6 | go-feature-flag/rules@e9704fa7（GOFF v1.59.1 の replace 先） `parser/` | nikunjy クエリ言語の文法・演算とテスト |
| S8-7 | flagd@flagd/v0.19.0 `docs/reference/...fractional-operation{,-spec}.md`, ADR 2 件, `flagd/CHANGELOG.md`；flipt@v2.14.2 `CHANGELOG.md` | Part B |
| S8-8 | https://github.com/flipt-io/flipt/pull/5581, https://github.com/flipt-io/flipt/releases/tag/v2.9.0, https://docs.flipt.io/v2/concepts, https://gofeatureflag.org/docs/configure_flag/rollout-strategies/percentage, https://flagd.dev/reference/custom-operations/fractional-operation/ （2026-11-25 閲覧） | Part B |
