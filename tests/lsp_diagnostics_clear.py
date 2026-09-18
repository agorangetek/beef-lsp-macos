#!/usr/bin/env python3
"""Probe v7: diagnostics must CLEAR when the buffer is fixed (didChange)."""
import json, os, subprocess, time, select
DIST="/tmp/BeefIDE/IDE/dist"; ROOT="/tmp/beef_example"; TARGET=os.path.join(ROOT,"src/Program.bf")
TT=["namespace","type","class","enum","interface","struct","typeParameter","parameter","variable",
    "property","enumMember","event","function","method","macro","keyword","modifier","comment",
    "string","number","regexp","operator","decorator"]
p=subprocess.Popen([os.path.join(DIST,"BeefLsp")],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE,cwd=DIST)
buf=b""
def send(m):
    d=json.dumps(m).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n"%len(d)+d); p.stdin.flush()
def read_one(t):
    global buf
    dl=time.time()+t
    while time.time()<dl:
        if b"\r\n\r\n" in buf:
            h,_,rest=buf.partition(b"\r\n\r\n"); n=None
            for line in h.split(b"\r\n"):
                k,_,v=line.partition(b":")
                if k.strip().lower()==b"content-length": n=int(v.strip())
            if n is not None and len(rest)>=n:
                body,buf=rest[:n],rest[n:]; return json.loads(body)
        r,_,_=select.select([p.stdout],[],[],0.3)
        if r:
            c=os.read(p.stdout.fileno(),65536)
            if not c: return None
            buf+=c
    return "TIMEOUT"
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"processId":os.getpid(),
  "rootUri":"file://"+ROOT,"capabilities":{"textDocument":{"semanticTokens":{"tokenTypes":TT}}}}})
while True:
    m=read_one(60)
    if isinstance(m,dict) and m.get("id")==1: break
    if m in (None,"TIMEOUT"): print("init failed"); raise SystemExit(1)
print("initialize ok")
send({"jsonrpc":"2.0","method":"initialized","params":{}})
time.sleep(4)
while read_one(1) not in ("TIMEOUT",None): pass

good=open(TARGET,encoding="utf-8").read()
broken=good+"\nclass B\n{\n\tpublic void F()\n\t{\n\t\tint x = \"nope\";\n\t}\n}\n"
uri="file://"+TARGET
send({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{
     "uri":uri,"languageId":"beef","version":1,"text":broken}}})
def wait_diags(t):
    dl=time.time()+t
    while time.time()<dl:
        m=read_one(max(1,dl-time.time()))
        if m in (None,"TIMEOUT"): return None
        if isinstance(m,dict) and m.get("method")=="textDocument/publishDiagnostics":
            return m["params"]
    return None
d1=wait_diags(150)
print("open broken -> diagnostics:", len(d1["diagnostics"]) if d1 else None,
      [x.get("message") for x in d1["diagnostics"]] if d1 else "")
# fix it
send({"jsonrpc":"2.0","method":"textDocument/didChange","params":{
  "textDocument":{"uri":uri,"version":2},
  "contentChanges":[{"text":good}]}})
d2=wait_diags(150)
if d2 is None:
    print("after fix  -> NO diagnostics notification")
else:
    print("after fix  -> diagnostics:", len(d2["diagnostics"]))
    print("RESULT:", "PASS (cleared)" if len(d2["diagnostics"])==0 else "FAIL (stale diagnostics remain)")
try: p.kill()
except Exception: pass
