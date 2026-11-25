# センサス検索式と寄与（2026-11-25）

| 経路 | 検索式 | API total_count | 取得ヒット（重複除く） | うち計数対象 |
|---|---|---|---|---|
| sourcegraph | `flagd.dev/schema/v0/flags.json count:all patterntype:keyword` | — | 73 | 8 |
| sourcegraph | `defaultVariant AND ENABLED AND variants file:\.json$ count:all patterntype:keyword` | — | 176 | 1 |
| sourcegraph | `defaultVariant AND DISABLED AND variants file:\.json$ count:all patterntype:keyword` | — | 159 | 0 |
| sourcegraph | `file:\.flagd\.json$ count:all` | — | 9 | 2 |
| sourcegraph | `VARIANT_FLAG_TYPE file:\.ya?ml$ count:all` | — | 29 | 7 |
| sourcegraph | `BOOLEAN_FLAG_TYPE file:\.ya?ml$ count:all` | — | 1 | 0 |
| sourcegraph | `distributions AND rollout AND variants file:\.ya?ml$ count:all patterntype:keyword` | — | 13 | 0 |
| sourcegraph | `namespace AND flags AND rollouts file:\.ya?ml$ count:all patterntype:keyword` | — | 74 | 0 |
| sourcegraph | `file:(^\|/)([^/]*\.)?features\.ya?ml$ count:all` | — | 991 | 0 |
| sourcegraph | `defaultRule AND variations file:\.ya?ml$ count:all patterntype:keyword` | — | 4 | 1 |
| sourcegraph | `defaultRule AND percentage file:\.ya?ml$ count:all patterntype:keyword` | — | 86 | 0 |
| github-code-search | `"flagd.dev/schema/v0/flags.json" extension:json` | 692 | 692 | 184 |
| github-code-search | `filename:.flagd.json` | 320 | 320 | 146 |
| github-code-search | `"fractional" "defaultVariant" extension:json` | None | 100 | 52 |
| github-code-search | `"targeting" "defaultVariant" "state" extension:json` | 503 | 503 | 209 |
| github-code-search | `"VARIANT_FLAG_TYPE" extension:yml` | 76 | 76 | 36 |
| github-code-search | `"VARIANT_FLAG_TYPE" extension:yaml` | 31 | 31 | 20 |
| github-code-search | `"BOOLEAN_FLAG_TYPE" extension:yml` | 125 | 124 | 77 |
| github-code-search | `"BOOLEAN_FLAG_TYPE" extension:yaml` | 51 | 51 | 37 |
| github-code-search | `filename:features.yml flags` | 318 | 318 | 55 |
| github-code-search | `filename:features.yaml flags` | 621 | 621 | 32 |
| github-code-search | `"distributions" "rollout" "variants" extension:yml` | 143 | 143 | 40 |
| github-code-search | `"distributions" "rollout" "variants" extension:yaml` | 324 | 324 | 35 |
| github-code-search | `"namespace" "flags" "rollouts" extension:yml` | 241 | 241 | 36 |
| github-code-search | `"defaultRule" "variations" extension:yaml` | 225 | 224 | 137 |
| github-code-search | `"defaultRule" "variations" extension:yml` | 3 | 3 | 2 |
| github-code-search | `"defaultRule" "percentage" extension:yaml` | 8224 | 655 | 25 |
| github-code-search | `"defaultRule" "percentage" extension:yml` | 44 | 44 | 0 |
| github-code-search | `filename:goff extension:yaml` | 415 | 415 | 57 |
| github-code-search | `"targeting" "query" "variation" "defaultRule" extension:yaml` | 123 | 122 | 75 |
| github-code-search | `"defaultVariant" "ENABLED" "variants" extension:json` | 1036 | 580 | 220 |
| github-code-search | `"defaultVariant" "DISABLED" "variants" extension:json` | 916 | 568 | 17 |

経路別の計数対象（重複あり）: sourcegraph=16, github-code-search=632; 両経路の和集合=634、GitHub のみ=618、Sourcegraph のみ=2
