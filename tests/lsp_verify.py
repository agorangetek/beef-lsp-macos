#!/usr/bin/env python3
"""Probe v6: verification suite for rootUri support, capability hardening, and diagnostics.

Cases:
  A. rootUri only (no rootPath)          -> workspace must load from rootUri
  B. minimal capabilities (no semanticTokens) -> initialize must still respond (no stall)
  C. workspaceFolders only               -> workspace must load from the folder
  D. broken buffer                       -> diagnostics must be published
"""
import json, os, subprocess, sys, time, select

DIST = "/tmp/BeefIDE/IDE/dist"
ROOT = "/tmp/beef_example"
EXE = os.path.join(DIST, os.environ.get("BEEFLSP", "BeefLsp"))
TARGET = os.path.join(ROOT, "src/Program.bf")
TT = ["namespace","type","class","enum","interface","struct","typeParameter","parameter",
      "variable","property","enumMember","event","function","method","macro","keyword",
      "modifier","comment","string","number","regexp","operator","decorator"]

FULL_CAPS = {
    "workspace": {"workspaceFolders": True, "configuration": True},
    "textDocument": {
        "synchronization": {"dynamicRegistration": True},
        "publishDiagnostics": {"relatedInformation": True},
        "hover": {"contentFormat": ["markdown"]},
        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
        "semanticTokens": {"requests": {"full": True}, "tokenTypes": TT,
                           "tokenModifiers": ["declaration","definition","readonly","static"],
                           "formats": ["relative"]},
    },
}

class Server:
    def __init__(self):
        self.p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, cwd=DIST)
        self.buf = b""
        self.logs = []

    def send(self, m):
        d = json.dumps(m).encode()
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(d) + d); self.p.stdin.flush()

    def read_one(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if b"\r\n\r\n" in self.buf:
                head, _, rest = self.buf.partition(b"\r\n\r\n")
                n = None
                for line in head.split(b"\r\n"):
                    k, _, v = line.partition(b":")
                    if k.strip().lower() == b"content-length":
                        n = int(v.strip())
                if n is not None and len(rest) >= n:
                    body, self.buf = rest[:n], rest[n:]
                    return json.loads(body)
            r, _, _ = select.select([self.p.stdout], [], [], 0.3)
            if r:
                c = os.read(self.p.stdout.fileno(), 65536)
                if not c: return None
                self.buf += c
        return "TIMEOUT"

    def initialize(self, params, timeout=120):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.read_one(max(1, deadline - time.time()))
            if m is None: return None, self.logs
            if m == "TIMEOUT": return "TIMEOUT", self.logs
            if isinstance(m, dict):
                if m.get("id") == 1: return m, self.logs
                if m.get("method") == "window/logMessage":
                    self.logs.append(m["params"]["message"])

    def kill(self):
        try: self.p.kill()
        except Exception: pass

def base_params():
    return {"processId": os.getpid(), "clientInfo": {"name": "vscode", "version": "1.90.0"}}

results = []

# ---- Case A: rootUri only ----
srv = Server()
params = base_params(); params["rootUri"] = "file://" + ROOT; params["capabilities"] = FULL_CAPS
r, logs = srv.initialize(params)
ok = isinstance(r, dict) and "result" in r and any("Loaded workspace at " + ROOT in l for l in logs)
results.append(("A. rootUri only", ok, "loaded=%s" % any(ROOT in l for l in logs)))
srv.kill()

# ---- Case B: minimal capabilities (regression for the stall) ----
srv = Server()
params = base_params(); params["rootUri"] = "file://" + ROOT; params["capabilities"] = {}
t0 = time.time()
r, logs = srv.initialize(params, timeout=60)
ok = isinstance(r, dict) and "result" in r
results.append(("B. minimal capabilities (no semanticTokens)", ok,
                "responded in %.1fs" % (time.time() - t0) if ok else "NO RESPONSE (stalled)"))
srv.kill()

# ---- Case C: workspaceFolders only ----
srv = Server()
params = base_params(); params["capabilities"] = FULL_CAPS
params["workspaceFolders"] = [{"uri": "file://" + ROOT, "name": "beef_example"}]
r, logs = srv.initialize(params)
ok = isinstance(r, dict) and "result" in r and any(ROOT in l for l in logs)
results.append(("C. workspaceFolders only", ok, "loaded=%s" % any(ROOT in l for l in logs)))
srv.kill()

# ---- Case D: diagnostics on a broken buffer ----
srv = Server()
params = base_params(); params["rootUri"] = "file://" + ROOT; params["capabilities"] = FULL_CAPS
r, logs = srv.initialize(params)
diag_ok = False; diag_msg = "no response to initialize"
if isinstance(r, dict) and "result" in r:
    srv.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    time.sleep(3)
    while True:
        m = srv.read_one(1)
        if m == "TIMEOUT" or m is None: break
    broken = open(TARGET, encoding="utf-8").read() + """
class Broken
{
	public void F()
	{
		int x = "this is not an int";
		UndefinedType y;
		y = 1
	}
}
"""
    srv.send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
        "textDocument": {"uri": "file://" + TARGET, "languageId": "beef", "version": 1, "text": broken}}})
    deadline = time.time() + 180
    while time.time() < deadline:
        m = srv.read_one(max(1, deadline - time.time()))
        if m == "TIMEOUT" or m is None: break
        if isinstance(m, dict) and m.get("method") == "textDocument/publishDiagnostics":
            ds = m["params"].get("diagnostics", [])
            diag_ok = len(ds) > 0
            diag_msg = "%d diagnostic(s): %s" % (len(ds), str([d.get("message") for d in ds[:3]])[:150])
            break
    else:
        diag_msg = "no diagnostics before timeout"
results.append(("D. diagnostics on broken buffer", diag_ok, diag_msg))
srv.kill()

print()
print("=" * 62)
for name, ok, detail in results:
    print("%-42s %s   %s" % (name, "PASS" if ok else "FAIL", detail))
print("=" * 62)
print("ALL PASS" if all(o for _, o, _ in results) else "SOME FAILED")
