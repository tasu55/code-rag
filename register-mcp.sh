#!/usr/bin/env bash
# 使い方: ./register-mcp.sh <対象リポジトリの絶対パス> [埋め込みモデル(既定: nomic-embed-text)]
# 対象リポジトリのローカルスコープ(そのディレクトリ用。リポジトリには書き込まない)に claude-context を登録する。
set -euo pipefail
repo="${1:?対象リポジトリのパスを指定してください}"
model="${2:-nomic-embed-text}"
cd "$repo"
claude mcp add claude-context --scope local \
  -e EMBEDDING_PROVIDER=Ollama \
  -e OLLAMA_HOST=http://127.0.0.1:11434 \
  -e OLLAMA_MODEL="$model" \
  -e MILVUS_ADDRESS=127.0.0.1:19530 \
  -- npx @zilliz/claude-context-mcp@latest
echo "登録しました。Claude Code を再起動し、'index_codebase' で索引化してください。"
