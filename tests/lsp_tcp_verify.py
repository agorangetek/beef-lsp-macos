#!/usr/bin/env python3
"""Verify the TCP transport the VS Code extension actually uses (--port=5556)."""
import json, os, socket, subprocess, time, sys
DIST="/tmp/BeefIDE/IDE/dist"; ROOT="/tmp/beef_example"; PORT=5556
TT=["namespace","type","class","enum","interface","struct","typeParameter","parameter","variable",
    "property","enumMember","event","function","method","macro","keyword","modifier","comment",
    "string","number","regexp","operator","decorator"]

srv = subprocess.Popen([os.path.join(DIST,"BeefLsp"), f"--port={PORT}"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=DIST)
time.sleep(1.5)
if srv.poll() is not None:
    print("server exited early, rc=", srv.returncode)
    print("stderr:", srv.stderr.read(2000).decode(errors="replace"))
    sys.exit(1)

s = socket.create_connection(("127.0.0.1", PORT), timeout=30)
s.settimeout(30)
buf = b""

def send(m):
    d = json.dumps(m).encode()
    s.sendall(b"Content-Length: %d\r\n\r\n" % len(d) + d)

def read_one(timeout=30):
    global buf
    dl = time.time() + timeout
    while time.time() < dl:
        if b"\r\n\r\n" in buf:
            h,_,rest = buf.partition(b"\r\n\r\n"); n=None
            for line in h.split(b"\r\n"):
                k,_,v = line.partition(b":")
                if k.strip().lower()==b"content-length": n=int(v.strip())
            if n is not None and len(rest)>=n:
                body,buf = rest[:n], rest[n:]
                return json.loads(body)
        s.settimeout(max(0.5, dl-time.time()))
        try: c = s.recv(65536)
        except socket.timeout: continue
        if not c: return None
        buf += c
    return "TIMEOUT"

print("==> connected to 127.0.0.1:%d" % PORT)
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "processId": os.getpid(), "rootUri":"file://"+ROOT,
    "clientInfo":{"name":"vscode","version":"1.90.0"},
    "capabilities":{"workspace":{"workspaceFolders":True},
        "textDocument":{"publishDiagnostics":{},
            "semanticTokens":{"requests":{"full":True},"tokenTypes":TT,
                              "tokenModifiers":["declaration","definition"],"formats":["relative"]}}},
    "workspaceFolders":[{"uri":"file://"+ROOT,"name":"beef_example"}]}})

ok=False
dl=time.time()+120
while time.time()<dl:
    m=read_one(max(1,dl-time.time()))
    if m in (None,"TIMEOUT"): break
    if isinstance(m,dict) and m.get("id")==1:
        print("PASS TCP initialize:", m.get("result",{}).get("serverInfo"),
              "| caps:", len(m.get("result",{}).get("capabilities",{})))
        ok=True; break
    if isinstance(m,dict) and m.get("method")=="window/logMessage":
        print("   <-", m["params"]["message"][:110])

# diagnostics over TCP
if ok:
    send({"jsonrpc":"2.0","method":"initialized","params":{}})
    time.sleep(3)
    while read_one(1) not in ("TIMEOUT",None): pass
    broken = open(os.path.join(ROOT,"src/Program.bf"),encoding="utf-8").read()+"\nclass B\n{\n\tpublic void F()\n\t{\n\t\tint x = \"nope\";\n\t}\n}\n"
    uri="file://"+os.path.join(ROOT,"src/Program.bf")
    send({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{
        "uri":uri,"languageId":"beef","version":1,"text":broken}}})
    dl=time.time()+180
    while time.time()<dl:
        m=read_one(max(1,dl-time.time()))
        if m in (None,"TIMEOUT"): break
        if isinstance(m,dict) and m.get("method")=="textDocument/publishDiagnostics":
            print("PASS TCP diagnostics:", len(m["params"]["diagnostics"]), "diagnostic(s)")
            break
try: s.close()
except Exception: pass
srv.kill()
print("TCP transport:", "WORKS" if ok else "FAILED")
