# Building beef-lsp-macos

Two things get built: the **language server** (Beef, compiled with the Beef compiler) and the **VS Code
extension** (TypeScript).

## Prerequisites

1. **A Beef toolchain built on macOS.** The server drives the real Beef compiler, so build it first:
   ```bash
   git clone https://github.com/agorangetek/beef-macos && cd beef-macos
   bash setup-beef-macos.sh
   ```
   That gives you `<Beef>/IDE/dist/BeefBuild`, plus the corlib socket fixes the server needs (see
   *Troubleshooting*). Homebrew `llvm@22` (22.1.x) comes with it.

2. **Node 18+** (tested on 24) and **python3** — the latter only to run the verification clients.

Throughout, `<Beef>` means the Beef checkout that `beef-macos` produced (its `Beef/` directory), and
`<Beef>/IDE/dist` is where its CLI tools live:

```bash
BEEF_DIST=<Beef>/IDE/dist     # the toolchain's bin/lib directory
```

**A macOS build contains no IDE** — `IDE/` is only the repository's layout, and `BeefBuild`/`BeefLsp` are
written there. If `IDE/dist` reads oddly, read it as "the toolchain's binary and library directory".

## 1. Build the language server

The project has to sit **inside** the Beef tree, because its workspace reaches for siblings by relative
path (`../BeefLibs/corlib`, `../IDEHelper`, `../BeefySysLib`, `../Debugger64`).

```bash
cp -R src BeefProj.toml BeefSpace.toml <Beef>/BeefLsp/
cd <Beef>/IDE/dist
./BeefBuild -workspace=<Beef>/BeefLsp -config=Release -platform=macOS
```

The result is `<Beef>/IDE/dist/BeefLsp`. A Debug build (`-config=Debug`) produces `BeefLsp_d` and is
useful for debugging the server itself.

Sanity check:

```bash
<Beef>/IDE/dist/BeefLsp --version      # -> Beef LSP v0.1.1
```

Two notes about the macOS link config, which is already in `BeefProj.toml`:

- `-L/opt/homebrew/opt/llvm@22/lib -L/usr/local/opt/llvm@22/lib` — both Apple-Silicon and Intel Homebrew
  prefixes, so the generated `-lLLVM-22` from `IDEHelper_libs.txt` resolves.
- `PreprocessorMacros = ["CLI"]` — this is why the server does **not** need corlib's file-dialog types:
  the IDE's dialog code is behind `#if !CLI` and is skipped entirely.

## 2. Build the VS Code extension

```bash
cd vscode-extension
npm install
npm run compile          # esbuild -> out/extension.js + out/settings.js
npx @vscode/vsce package --out beeflang.vsix
```

`prebuilt/beeflang-0.1.1.vsix` in this repository is that output, ready to install. Note the extension is
a workspace-extension: `npm install` pulls esbuild 0.15 and svelte tooling, all of which build fine on
Node 24.

## 3. Install

```bash
# make the launcher findable, and point it at your Beef tree
mkdir -p ~/bin
cp bin/BeefLsp ~/bin/ && chmod +x ~/bin/BeefLsp
export BEEF_DIST=<Beef>/IDE/dist          # or edit the default inside the launcher
```

The launcher matters: the server links `@rpath/libhunspell.dylib` and resolves corlib relative to its own
directory, so it must run with the toolchain's dist directory (`<Beef>/IDE/dist`) as its working directory. The launcher `cd`s there.

Then install the extension — VS Code / VSCodium → Extensions → `...` → **Install from VSIX…** →
`prebuilt/beeflang-0.1.1.vsix`.

Finally, tell the extension where the launcher is. **macOS GUI apps do not inherit your shell `PATH`**, so
`execFile("BeefLsp")` will not find `~/bin` on its own. Add to your editor `settings.json`:

```json
"beeflang.serverPath": "/Users/you/bin/BeefLsp"
```

Open a **folder** containing `BeefSpace.toml`, then a `.bf` file. Opening only a file gives the server no
workspace root, and it will report `No workspace path given` — that is expected, not a bug.

You should see a `Beef LSP` output channel reporting:

```
[INFO   ] Connected
[INFO   ] Loaded workspace at /path/to/your/workspace
[INFO   ] Refreshing workspace
```

## 4. Verify

The Python LSP clients in `tests/` are what we used to verify the server. Point them at your build:

```bash
BEEFLSP=BeefLsp python3 tests/lsp_verify.py            # rootUri / capabilities / diagnostics
python3 tests/lsp_tcp_verify.py                        # the TCP transport the extension uses
python3 tests/lsp_diagnostics_clear.py                 # diagnostics appear, then clear
```

They expect the server on `PATH` (or in `/tmp/BeefIDE/IDE/dist` — set `BEEFLSP` and edit `DIST` at the top
if your layout differs).

## Troubleshooting

**The server exits immediately / `Failed to start connection with the client`**
Beef's corlib could not listen on IPv6 on macOS (`AF_INET6` was hardcoded to the Windows value 23; the
`sockaddr` structs lacked the BSD length byte; `addrinfo` used the glibc field order; socket-option values
came from Linux). Build Beef with [`beef-macos`](https://github.com/agorangetek/beef-macos), which fixes
all four. The server binds IPv4 loopback either way.

**`ld: library 'LLVM-22' not found`**
`IDEHelper_libs.txt` contains `-lLLVM-22`; the LLVM lib directory must be on the link line. Both Homebrew
prefixes are already listed in `BeefProj.toml` — check that `brew --prefix llvm@22` matches one of them.

**The extension errors with "connection to server is erroring" and restarts five times**
That is the stock extension's behaviour: it waits a fixed 1 s after spawning the server and never retries,
and it hardcodes port 5556 so two windows collide. Both are fixed in this repository's extension (free
port per window + connect retry); make sure you installed `prebuilt/beeflang-0.1.1.vsix` from here rather
than an older build.

**`Error: EPERM: operation not permitted` from `npm install`**
Only seen in sandboxed environments where the default npm cache (`~/.npm`) is not writable. Use
`npm install --cache /tmp/npm-cache`.

**No diagnostics in the editor**
Check, in order: a folder (not just a file) is open; the `Beef LSP` output channel says `Connected`; and
`beeflang.serverPath` points at an executable launcher. Diagnostics only appear for files that are part
of the workspace's project.

## What we changed, and upstreaming

`patches/` contains our changes as patches against the upstream fork
([`MineGame159/Beef`](https://github.com/MineGame159/Beef), branch `lsp`, last touched 2023):

| Patch | |
|---|---|
| `0001-lsp-api-drift-rooturi-tcp.patch` | compiler API drift, `rootUri` support, JSON capability hardening, IPv4 bind + port |
| `0002-vscode-extension-macos.patch` | configurable server path, free port per window, connect retry, explicit loopback |
| `0003-lsp-build-configs.patch` | macOS build configs |

The sources in `src/` and `vscode-extension/` already include them. The patches are kept so the fixes can
be offered back upstream.
