# code-rag PoC (claude-context + Milvus + Ollama, すべてローカル)

- **起動**: `docker compose -f milvus-standalone-docker-compose.yml up -d` と `docker start ollama-poc`(Ollama は Docker 版、ポート 11435)
- **停止**: `docker compose -f milvus-standalone-docker-compose.yml down`(データは `./volumes` に残る)
- **登録**: `./register-mcp.sh <repo> [model]`
- Milvus v3.0.6(公式 compose。ポートは 127.0.0.1 のみに公開に変更)
- 埋め込み: Ollama nomic-embed-text(768 次元)。モデルは `OLLAMA_MODEL` で替える
- CPU のみで測る場合: `docker compose -p ollama-cpu -f docker-compose.ollama-cpu.yml up -d`(ポート 11436、既定は 4 コア / 6GB)

---

## 使い方(詳細)

### 1. 環境を起動する
```bash
cd ~/poc/code-rag
docker compose -f milvus-standalone-docker-compose.yml up -d   # Milvus(127.0.0.1:19530)
docker start ollama-poc                                         # Ollama GPU版(127.0.0.1:11435)
# CPUのみで測るとき: docker compose -p ollama-cpu -f docker-compose.ollama-cpu.yml up -d  (127.0.0.1:11436)
```
確認: `curl -s http://127.0.0.1:19530/v2/vectordb/collections/list` と `curl -s http://127.0.0.1:11435/api/tags`。

埋め込みモデルは `ollama-poc` に入っている必要がある。
- `nomic-embed-text`
- `hf.co/ggml-org/embeddinggemma-2-GGUF:Q8_0`(EmbeddingGemma 2)

### 2. 対象リポジトリに MCP を登録する(任意・手動で使うとき)
```bash
./register-mcp.sh /home/tasuq/project/local-ai-tuber nomic-embed-text
```
- 登録はそのディレクトリのローカルスコープ。リポジトリ本体は変更しない。
- Claude Code を再起動し、`index_codebase` で索引化する。
- **注意**: `register-mcp.sh` の `OLLAMA_HOST` は既定で `11434`(ホストの Ollama 用)になっている。ホストの Ollama は停止中なので、`11435` に直すか、登録後に `claude mcp` で確認する。

### 3. 評価を回す(`eval/`)
すべて `eval/` で実行する。
```bash
cd ~/poc/code-rag/eval
./run_eval.py index --condition <名前> --embed-model <モデル>     # 索引化(完了と件数の安定まで待つ)
./run_eval.py run   --condition <名前> --mcp none                 # grep のみ
./run_eval.py run   --condition <名前> --mcp claude-context --embed-model <モデル> [--hint] [--ids C01 A03 ...] [--overwrite]
./run_eval.py report                                              # 集計
./run-chain.sh                                                    # 上の一連(nomic と gemma2、指示なしと促しの 4 条件)を通しで実行
```
| オプション | 意味 |
|---|---|
| `--condition` | 結果ファイルの名前(`results/<名前>.jsonl`) |
| `--embed-model` | 索引化と検索に使う Ollama モデル(既定 `nomic-embed-text`) |
| `--model` | 評価に使う Claude モデル(既定 `haiku`) |
| `--mcp` | `none`(grep のみ)か `claude-context` |
| `--hint` | 「search_code を使うように」と促す |
| `--ids` | 特定の質問だけ回す |
| `--overwrite` | 既存の結果を上書きする |
| `--stable-s` | 索引化で件数が安定したと見なす秒数(既定 30) |
| `--budget` | 1 問あたりの上限(USD、既定 0.5) |

- Ollama の接続先は環境変数 `EVAL_OLLAMA_HOST` で変える(既定 `http://127.0.0.1:11435`)。CPU 版は `EVAL_OLLAMA_HOST=http://127.0.0.1:11436`。
- 評価には Claude の API を使う(`claude -p`)。質問・回答・検索結果の断片が API に送られる。

### 4. 検索順位だけを測る(LLM なし)
```bash
cd ~/poc/code-rag/eval
./retrieval_eval.py --label <名前> --embed-model <モデル> [--query-prefix "..."] [--limit 10]
```
結果は `results/retrieval-<名前>.json` に出る。

### 5. 質問を追加・修正する
`eval/questions.json` に追加する。主な項目は次のとおり。
- `id`、`type`(intent / identifier / cross / rationale / negative)、`question`
- `must_find`: どれか 1 つ(cross の C01 は全部)が答えに出れば hit
- `also_relevant`: 関連するが正解ではないファイル

正解は必ず `git grep` で裏取りしてから入れる。

### 6. 結果の場所
- `eval/results/*.jsonl`: 問ごとの結果(回答、ツール呼び出し、hit)
- `eval/results/index-*.json`: 索引化の件数
- `eval/results/retrieval-*.json`: 検索順位
- `eval/run-all.log`、`eval/run-chain.log`: 実行ログ

### 7. 停止
```bash
docker stop ollama-poc            # 必要なら
docker compose -f milvus-standalone-docker-compose.yml down   # データは ./volumes に残る
```

### トラブル時の注意
- 索引化は `index` が完了するまで待つ。途中で閉じると MCP サーバが止まり、索引化が中断される。
- `status` が「完了」と出ても信用しない。Milvus の件数と追跡ファイル数を突き合わせる(`run_eval.py` の `index` は内部でそうしている)。
- `pkill -f run_eval.py` は自分のコマンドも巻き込むことがある。PID を指定して止める。
