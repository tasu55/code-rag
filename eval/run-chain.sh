#!/usr/bin/env bash
# Docker版Ollama(11435)で、モデルごとに 索引化 → 評価(指示なし / search_code利用を促す)を回す
set -u
cd "$(dirname "$0")"
: "${EVAL_REPO:?EVAL_REPO に対象リポジトリのパスを設定してください}"
GEMMA='hf.co/ggml-org/embeddinggemma-2-GGUF:Q8_0'
./run_eval.py index --condition nomic-text --embed-model nomic-embed-text
./run_eval.py run --condition nomic-text --mcp claude-context --embed-model nomic-embed-text --overwrite
./run_eval.py run --condition nomic-text-hint --mcp claude-context --embed-model nomic-embed-text --hint --overwrite
./run_eval.py index --condition gemma2 --embed-model "$GEMMA"
./run_eval.py run --condition gemma2 --mcp claude-context --embed-model "$GEMMA" --overwrite
./run_eval.py run --condition gemma2-hint --mcp claude-context --embed-model "$GEMMA" --hint --overwrite
./run_eval.py report
