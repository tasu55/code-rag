# 評価セット(質問 JSON と採点)

質問セットはリポジトリごとに用意する(既定は `questions.json`、`--questions` で差し替え)。
別のリポジトリで使うときは、同じ形式の JSON を作り、`EVAL_REPO` と `--questions` を指定する。

### 質問セットの形式

`questions.json` は次の形です。例は `questions.example.json` を参照してください。

```json
{"questions": [
  {"id": "E01", "type": "intent", "question": "…", "must_find": ["src/x.py"], "also_relevant": [], "note": ""}
]}
```

- `id`: 一意な ID。
- `type`: `intent`(識別子を使わず機能で聞く)、`identifier`(識別子で聞く)、`cross`(複数ファイルにまたがる)、`rationale`(設計判断)、`negative`(存在しない機能)のいずれか。
- `must_find`: 正解ファイルのリポジトリ相対パス。`cross` の質問は全件が必要で、それ以外はどれか 1 件で正解。`negative` は空にする。
- `also_relevant`: 関連するが採点には使わないファイル。
- `note`: メモ。採点には使わない。
- `negative` は「該当なし」と答えられれば正解。
- 正解ファイルは `git grep` で裏取りしてから入れる。

注意: `EVAL_REPO` には信頼できるリポジトリだけを指定する。`claude -p` は対象リポジトリの `.claude/settings.json`(フックや許可設定)を読み込むため、信頼できないリポジトリを指定すると、そこに書かれたコマンドが評価中に実行されるおそれがある。

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
