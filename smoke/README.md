# smoke/ — Phase 0 smoke と census の成果物（使い捨て。製品コードではない）

| パス | 内容 |
|---|---|
| `lib/engines.py` | 公開ソースからのバケット計算の再実装（flagd G1/G2/G3、Flipt legacy / v2.9+ / Rust、GOFF）。 |
| `lib/verify_testbed.py` | 再実装を flagd-testbed（37 件）と Flipt のテスト（5 件）の期待値で照合。`python3 -I smoke/lib/verify_testbed.py` |
| `census/scripts/collect.py` | 候補収集（GitHub コード検索、Sourcegraph）。→ `census/raw/candidates.jsonl` |
| `census/scripts/fetch_classify.py` | 本体取得、D-1 同定、D-2 重複排除、D-3／Z-2 由来判定。→ `census/inventory.csv`, `census/files/` |
| `census/scripts/summarize.py` | 集計。→ `census/summary.json` |
| `census/queries.md` | 検索式ごとの件数と寄与 |
| `census/inventory.csv` | 全取得ファイルの一覧（計数対象は `counted=True`） |
| `census/files/` | 同定に合致したファイルのバイト列（SHA-256 名）。第三者の公開ファイルで、ローカル保存のみ |
| `select_smoke_inputs.py` → `smoke_inputs.json` | D-7 による smoke 入力の機械選定 |
| `f2_flipt_smoke.py` | Smoke 1（F2） |
| `f4_flagd_smoke.py` | Smoke 2（F4） |
| `f3_static_scan.py` | Smoke 3 の補足（全センサスへの静的 F3 走査） |
| `results/` | smoke の出力 JSON |

再実行（ネットワークが要るのは collect と fetch_classify のみ）:

```bash
python3 -I smoke/lib/verify_testbed.py
python3 -I smoke/f4_flagd_smoke.py smoke/census/files/aaaf8ef930515f0270583945b1a27d79cc53646bfc9e2d9ff73fc9a35d1ffc3f.json
```
