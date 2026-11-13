"""最小のMCP stdioクライアント(改行区切りJSON-RPC)。索引化をLLMなしで直接駆動するために使う。"""
import json, os, subprocess, threading, queue


class McpClient:
    def __init__(self, command, args, env=None):
        self.p = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env={**os.environ, **(env or {})})
        self.q, self.n = queue.Queue(), 0
        threading.Thread(target=self._read, daemon=True).start()
        self.err = []
        threading.Thread(target=lambda: [self.err.append(l) for l in self.p.stderr], daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except Exception:
                pass

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def request(self, method, params=None, timeout=120):
        self.n += 1
        rid = self.n
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            msg = self.q.get(timeout=timeout)
            if msg.get("id") == rid:
                return msg

    def start(self):
        r = self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                        "clientInfo": {"name": "poc-eval", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r

    def call(self, name, arguments, timeout=120):
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout)

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(10)
        except Exception:
            self.p.kill()
