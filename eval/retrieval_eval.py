#!/usr/bin/env python3
"""LLMを介さず search_code の順位だけを測る。索引は事前に run_eval.py index で作っておく(モデルを合わせること)。
使い方: EVAL_REPO=<repo> ./retrieval_eval.py --label gemma2 --embed-model <model> [--query-prefix 'task: code retrieval | query: '] [--limit 10]
  --repo / --questions / --results は run_eval.py と同じ。Milvus は EVAL_MILVUS、Ollama は EVAL_OLLAMA_HOST で指定。
"""
import argparse, json, os, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcp_client import McpClient

LOC = re.compile(r"Location:\s*(.+?):\d+-\d+")

ap = argparse.ArgumentParser()
ap.add_argument("--label", required=True)
ap.add_argument("--embed-model", required=True)
ap.add_argument("--query-prefix", default="")
ap.add_argument("--limit", type=int, default=10)
ap.add_argument("--repo", default=os.environ.get("EVAL_REPO"), help="対象リポジトリ(既定: 環境変数 EVAL_REPO)")
ap.add_argument("--questions", default=str(HERE / "questions.json"))
ap.add_argument("--results", default=str(HERE / "results"))
ap.add_argument("--host", default=os.environ.get("EVAL_OLLAMA_HOST", "http://127.0.0.1:11435"))
ap.add_argument("--milvus", default=os.environ.get("EVAL_MILVUS", "127.0.0.1:19530"))
a = ap.parse_args()
if not a.repo:
    ap.error("--repo か環境変数 EVAL_REPO で対象リポジトリを指定してください")
REPO = str(Path(a.repo).resolve())

qs = [q for q in json.load(open(a.questions))["questions"] if q["type"] != "negative"]
c = McpClient("npx", ["@zilliz/claude-context-mcp@latest"], {
    "EMBEDDING_PROVIDER": "Ollama", "OLLAMA_HOST": a.host, "OLLAMA_MODEL": a.embed_model,
    "MILVUS_ADDRESS": a.milvus})
c.start()
rows = []
for q in qs:
    text = c.call("search_code", {"path": REPO, "query": a.query_prefix + q["question"], "limit": a.limit},
                  timeout=180)["result"]["content"][0]["text"]
    files = []
    for f in LOC.findall(text):
        if f not in files:
            files.append(f)
    must = q["must_find"]
    ranks = [files.index(m) + 1 for m in must if m in files]
    first = min(ranks) if ranks else None
    allfound = len(ranks) == len(must)
    rows.append({"id": q["id"], "type": q["type"], "first_rank": first, "all_found": allfound,
                 "n_files": len(files), "top3": files[:3]})
c.close()

def summ(rs):
    n = len(rs)
    return {"n": n,
            "hit@1": sum(1 for r in rs if r["first_rank"] == 1) / n,
            "hit@3": sum(1 for r in rs if r["first_rank"] and r["first_rank"] <= 3) / n,
            "hit@10": sum(1 for r in rs if r["first_rank"]) / n,
            "mrr": sum(1 / r["first_rank"] for r in rs if r["first_rank"]) / n}

out = {"label": a.label, "embed_model": a.embed_model, "query_prefix": a.query_prefix, "limit": a.limit,
       "all": summ(rows), "intent": summ([r for r in rows if r["type"] == "intent"]), "rows": rows}
Path(a.results).mkdir(parents=True, exist_ok=True)
json.dump(out, open(Path(a.results) / f"retrieval-{a.label}.json", "w"), ensure_ascii=False, indent=1)
print(a.label, "全体", {k: round(v, 3) for k, v in out["all"].items()}, "| intent", {k: round(v, 3) for k, v in out["intent"].items()})
print("  外れ(10位以内なし):", [r["id"] for r in rows if not r["first_rank"]])
