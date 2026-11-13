#!/usr/bin/env python3
"""任意のリポジトリに対する評価質問セットを `claude -p`(ヘッドレス)で回して採点する。

対象リポジトリ・質問セット・結果の保存先は、オプションまたは環境変数で指定する。
  --repo / EVAL_REPO          対象リポジトリ(run・index で必須)
  --questions                 質問セット(既定: eval/questions.json)
  --results                   結果の保存先(既定: eval/results)
  EVAL_MILVUS                 Milvus のアドレス(既定 127.0.0.1:19530)
  EVAL_OLLAMA_HOST            Ollama のURL(既定 http://127.0.0.1:11435)

使い方:
  export EVAL_REPO=/path/to/repo
  # 条件A: MCPなし(grep/Read/Globのみ)
  ./run_eval.py run --condition grep-only --mcp none
  # 索引化(条件Bの前に1回)。所要時間を results/index-<cond>.json に記録
  ./run_eval.py index --condition nomic-text --embed-model nomic-embed-text
  # 条件B: claude-context あり
  ./run_eval.py run --condition nomic-text --mcp claude-context --embed-model nomic-embed-text
  ./run_eval.py run --condition nomic-text-hint --mcp claude-context --embed-model nomic-embed-text --hint
  # 集計
  ./run_eval.py report
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = None  # main() で設定
QUESTIONS = HERE / "questions.json"
RESULTS = HERE / "results"
MCP_DIR = HERE / "mcp"
MILVUS = os.environ.get("EVAL_MILVUS", "127.0.0.1:19530")
OLLAMA_HOST = os.environ.get("EVAL_OLLAMA_HOST", "http://127.0.0.1:11435")  # Docker版 ollama-poc
SEARCH_TOOL = "mcp__claude-context__search_code"
BASE_TOOLS = ["Read", "Grep", "Glob"]

PROMPT = (
    "このリポジトリのコードについての質問に答えてください。コードは変更しないこと。\n"
    "回答の末尾に、根拠にしたファイルのリポジトリ相対パスを箇条書きで挙げてください。"
    "該当する実装が存在しない場合は、推測せず「該当なし」と答えてください。\n\n質問: {q}"
)
HINT = "\nコード検索ツール(search_code)が使えるなら活用してください。"

PATH_RE = re.compile(r"[\w./@-]+\.(?:py|tsx|ts|cts|md|json|yaml|jsonl)")


def load_questions(ids=None):
    qs = json.load(open(QUESTIONS))["questions"]
    return [q for q in qs if not ids or q["id"] in ids]


def write_mcp(condition, mcp, embed_model):
    MCP_DIR.mkdir(exist_ok=True)
    p = MCP_DIR / f"{condition}.json"
    servers = {}
    if mcp == "claude-context":
        servers["claude-context"] = {
            "command": "npx",
            "args": ["@zilliz/claude-context-mcp@latest"],
            "env": {
                "EMBEDDING_PROVIDER": "Ollama",
                "OLLAMA_HOST": OLLAMA_HOST,
                "OLLAMA_MODEL": embed_model,
                "MILVUS_ADDRESS": MILVUS,
            },
        }
    json.dump({"mcpServers": servers}, open(p, "w"), indent=1)
    return p


def claude_cmd(prompt, mcp_path, model, tools, budget, extra_builtin=()):
    return [
        "claude", "-p", prompt, "--model", model,
        "--output-format", "stream-json", "--verbose",
        "--mcp-config", str(mcp_path), "--strict-mcp-config",
        "--tools", ",".join(list(BASE_TOOLS) + list(extra_builtin)),
        "--allowedTools", *tools,
        "--setting-sources", "project",
        "--disable-slash-commands", "--no-session-persistence",
        "--max-budget-usd", str(budget),
    ]


def run_claude(cmd, timeout):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        out, err, rc = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, err, rc = (e.stdout or ""), "timeout", -1
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
    return out, err, rc, time.time() - t0


def parse_stream(out):
    calls, results, final, meta = [], {}, "", {}
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    calls.append({"id": c["id"], "name": c["name"], "input": c["input"]})
        elif t == "user":
            content = ev["message"].get("content", [])
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result":
                        v = c.get("content", "")
                        if isinstance(v, list):
                            v = "\n".join(x.get("text", "") for x in v if isinstance(x, dict))
                        results[c["tool_use_id"]] = str(v)
        elif t == "result":
            final = ev.get("result", "") or ""
            meta = {k: ev.get(k) for k in ("total_cost_usd", "num_turns", "duration_ms", "is_error", "usage")}
    return calls, results, final, meta


def base(p):
    return os.path.basename(p)


def score(q, calls, results, final):
    must = q["must_find"]
    ans_hit = [m for m in must if base(m) in final]
    if q["type"] == "negative":
        hit = bool(re.search(r"該当なし|見当たりません|存在しません|ありません", final)) and not ans_hit
        hit_answer = hit
    elif q["id"] == "C01":
        hit_answer = len(ans_hit) == len(must)
    else:
        hit_answer = len(ans_hit) >= 1
    # search_code の結果での最初の正解順位
    rank = None
    for c in calls:
        if c["name"] == SEARCH_TOOL:
            seen = []
            for m in PATH_RE.findall(results.get(c["id"], "")):
                if base(m) not in [base(s) for s in seen]:
                    seen.append(m)
            for i, s in enumerate(seen, 1):
                if base(s) in [base(m) for m in must]:
                    rank = i
                    break
            if rank:
                break
    used_search = any(c["name"] == SEARCH_TOOL for c in calls)
    return {"hit": bool(hit_answer), "answer_hits": [base(m) for m in ans_hit],
            "search_rank": rank, "used_search": used_search}


def cmd_run(a):
    RESULTS.mkdir(exist_ok=True)
    mcp_path = write_mcp(a.condition, a.mcp, a.embed_model)
    tools = BASE_TOOLS + ([SEARCH_TOOL] if a.mcp == "claude-context" else [])
    outp = RESULTS / f"{a.condition}.jsonl"
    done = set()
    if outp.exists() and not a.overwrite:
        done = {json.loads(l)["id"] for l in open(outp)}
    elif outp.exists():
        outp.unlink()
    for q in load_questions(a.ids):
        if q["id"] in done:
            continue
        prompt = PROMPT.format(q=q["question"]) + (HINT if a.hint else "")
        out, err, rc, wall = run_claude(claude_cmd(prompt, mcp_path, a.model, tools, a.budget), a.timeout)
        calls, results, final, meta = parse_stream(out)
        s = score(q, calls, results, final)
        rec = {"condition": a.condition, "id": q["id"], "type": q["type"], "wall_s": round(wall, 1),
               "n_calls": len(calls), "tools": [c["name"] for c in calls], "rc": rc,
               "final": final, **meta, **s}
        if rc != 0 and not final:
            rec["stderr"] = err[-500:]
        with open(outp, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f'{a.condition} {q["id"]} hit={s["hit"]} calls={len(calls)} search={s["used_search"]} '
              f'rank={s["search_rank"]} {wall:.0f}s cost={meta.get("total_cost_usd")}', flush=True)


def milvus_stats():
    """Milvus REST から hybrid_code_chunks_* の件数・ファイル数・拡張子分布を取る。"""
    import urllib.request, collections
    def post(path, body):
        req = urllib.request.Request(f"http://{MILVUS}" + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=20))
    try:
        cols = [c for c in post("/v2/vectordb/collections/list", {}).get("data", []) if c.startswith("hybrid_code_chunks")]
        if not cols:
            return {"chunks": 0, "files": 0, "ext": {}}
        d = post("/v2/vectordb/entities/query", {"collectionName": cols[0], "filter": "",
                                                 "outputFields": ["relativePath"], "limit": 16384}).get("data", [])
        files = collections.Counter(x["relativePath"] for x in d)
        ext = collections.Counter(f.rsplit(".", 1)[-1] for f in files)
        return {"chunks": len(d), "files": len(files), "ext": dict(ext)}
    except Exception as e:
        return {"error": str(e)}


def ignore_patterns():
    """git が無視しているファイル/ディレクトリを、claude-context の ignorePatterns 形式にする。"""
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
                         cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    pats = []
    for line in out:
        line = line.strip()
        if not line:
            continue
        pats.append(line + "**" if line.endswith("/") else line)
    return sorted(set(pats + ["**/__pycache__/**", "**/node_modules/**", "**/.venv/**"]))


def cmd_index(a):
    """MCPサーバへ直接つないで索引化し、完了(statusがfully indexed)かつMilvusの件数が安定するまで待つ。"""
    sys.path.insert(0, str(HERE))
    from mcp_client import McpClient
    RESULTS.mkdir(exist_ok=True)
    c = McpClient("npx", ["@zilliz/claude-context-mcp@latest"], {
        "EMBEDDING_PROVIDER": "Ollama", "OLLAMA_HOST": OLLAMA_HOST,
        "OLLAMA_MODEL": a.embed_model, "MILVUS_ADDRESS": MILVUS})
    c.start()
    pats = ignore_patterns()
    t0 = time.time()
    first = c.call("index_codebase", {"path": REPO, "force": True, "splitter": "ast", "ignorePatterns": pats})
    start_msg = first["result"]["content"][0]["text"][:200]
    print("開始:", start_msg.replace("\n", " "), flush=True)
    last, last_change, trace, status = None, time.time(), [], ""
    while time.time() - t0 < a.timeout:
        time.sleep(5)
        st = milvus_stats()
        key = (st.get("chunks"), st.get("files"))
        status = c.call("get_indexing_status", {"path": REPO})["result"]["content"][0]["text"]
        trace.append([round(time.time() - t0), key[0], key[1]])
        if key != last:
            last, last_change = key, time.time()
            print(f"[{time.time()-t0:5.0f}s] chunks={key[0]} files={key[1]}", flush=True)
        done = "fully indexed" in status and key[0]
        if done and time.time() - last_change >= a.stable_s:
            break
    index_time = last_change - t0
    st = milvus_stats()
    c.close()
    rec = {"condition": a.condition, "embed_model": a.embed_model, "index_time_s": round(index_time, 1),
           "status_text": status[:300], "n_ignore_patterns": len(pats), **st, "trace": trace[-60:]}
    json.dump(rec, open(RESULTS / f"index-{a.condition}.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in rec.items() if k != "trace"}, ensure_ascii=False, indent=1))


def cmd_report(a):
    rows = {}
    for p in sorted(RESULTS.glob("*.jsonl")):
        rows[p.stem] = [json.loads(l) for l in open(p)]
    types = ["intent", "identifier", "cross", "rationale", "negative"]
    print(f'{"条件":<22}{"全体hit":>9}' + "".join(f"{t:>12}" for t in types)
          + f'{"平均calls":>10}{"search使用":>10}{"入力計(万)":>11}{"出力計(万)":>11}{"$合計":>8}')
    for cond, rs in rows.items():
        n = len(rs)
        hit = sum(r["hit"] for r in rs)
        per = []
        for t in types:
            sub = [r for r in rs if r["type"] == t]
            per.append(f'{sum(r["hit"] for r in sub)}/{len(sub)}' if sub else "-")
        calls = sum(r["n_calls"] for r in rs) / n
        used = sum(r["used_search"] for r in rs)
        cost = sum((r.get("total_cost_usd") or 0) for r in rs)
        u = [r.get("usage") or {} for r in rs]
        inp = sum((x.get("input_tokens") or 0) + (x.get("cache_creation_input_tokens") or 0)
                  + (x.get("cache_read_input_tokens") or 0) for x in u) / 1e4
        out = sum(x.get("output_tokens") or 0 for x in u) / 1e4
        print(f"{cond:<22}{f'{hit}/{n}':>9}" + "".join(f"{x:>12}" for x in per)
              + f"{calls:>10.1f}{used:>10}{inp:>11.1f}{out:>11.2f}{cost:>8.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=os.environ.get("EVAL_REPO"), help="対象リポジトリ(既定: 環境変数 EVAL_REPO)")
    common.add_argument("--questions", default=str(QUESTIONS), help="質問セットの JSON")
    common.add_argument("--results", default=str(RESULTS), help="結果の保存先")
    for name in ("run", "index"):
        p = sp.add_parser(name, parents=[common])
        p.add_argument("--condition", required=True)
        p.add_argument("--embed-model", default="nomic-embed-text")
        p.add_argument("--model", default="haiku")
        p.add_argument("--budget", type=float, default=0.5)
        p.add_argument("--timeout", type=int, default=1800 if name == "index" else 300)
        if name == "index":
            p.add_argument("--stable-s", type=int, default=30)
        if name == "run":
            p.add_argument("--mcp", choices=["none", "claude-context"], default="none")
            p.add_argument("--hint", action="store_true")
            p.add_argument("--ids", nargs="*")
            p.add_argument("--overwrite", action="store_true")
    sp.add_parser("report", parents=[common])
    a = ap.parse_args()
    if a.cmd != "report" and not a.repo:
        ap.error("--repo か環境変数 EVAL_REPO で対象リポジトリを指定してください")
    REPO = str(Path(a.repo).resolve()) if a.repo else None
    QUESTIONS = Path(a.questions)
    RESULTS = Path(a.results)
    {"run": cmd_run, "index": cmd_index, "report": cmd_report}[a.cmd](a)
