# 評価セット(質問 JSON と採点)

質問セットはリポジトリごとに用意する(既定は `questions.json`、`--questions` で差し替え)。
現在の `questions.json` は local-ai-tuber(21 問)向けで、正解ファイルは git grep で裏取り済み。
別のリポジトリで使うときは、同じ形式の JSON を作り、`EVAL_REPO` と `--questions` を指定する。

```bash
export EVAL_REPO=/path/to/target-repo
./run_eval.py index --condition <名前> --embed-model nomic-embed-text
./run_eval.py run --condition <名前> --mcp claude-context --embed-model nomic-embed-text --questions /path/to/questions.json --results /path/to/results
```

| 種別 | 問数 | 狙い |
|---|---|---|
| intent (A) | 12 | 識別子を使わず意図で聞く。**埋め込みが効くかの本命** |
| identifier (B) | 2 | 識別子で聞く統制。grep で足りるはず |
| cross (C) | 4 | 複数ファイル横断 |
| rationale (D) | 2 | コメント/docsに答えがある設計判断 |
| negative (E) | 1 | 存在しない機能。「なし」と答えられるか(幻覚の検出) |

## 採点
- 条件ごとに、各問の結果を results.csv に記録する。
- hit: 回答/検索結果の上位に must_find のどれか(cross の C01 は全部)があるか。
- calls: 正解に着くまでのツール呼び出し回数。
- 条件: A=grepのみ(MCPなし) / B=claude-context ありの nomic-embed-text / 以降は埋め込みモデル別。
- 注意: コメントの多くが日本語。nomic-embed-text は英語中心なので、不利に出る可能性がある。多言語モデルも試すこと。
