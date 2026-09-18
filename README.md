# beef-lsp-macos

A working [Beef](https://www.beeflang.org/) **language server** and **VS Code extension** for macOS.

Beef ships no editor integration of its own — upstream's IDE is Windows-only. This is a macOS build of a
community language server, with the fixes needed to make it compile and run against the current Beef
compiler.

```
completion · hover · go to definition · find references · rename
document symbols · signature help · semantic tokens · folding ranges
formatting · workspace symbols · diagnostics
```

## Install

You need a Beef toolchain first (the server drives the real compiler):

```bash
git clone https://github.com/agorangetek/beef-macos && cd beef-macos
bash setup-beef-macos.sh
```

Then build the server from this repository and install the extension — see **[BUILDING.md](BUILDING.md)**.
Short version:

```bash
# 1. put the server sources inside the Beef checkout and build them
cp -R src BeefProj.toml BeefSpace.toml <Beef>/BeefLsp/
cd <Beef>/IDE/dist && ./BeefBuild -workspace=<Beef>/BeefLsp -config=Release -platform=macOS

# 2. make the launcher visible to the editor
mkdir -p ~/bin && cp bin/BeefLsp ~/bin/ && chmod +x ~/bin/BeefLsp

# 3. install the extension
#    VS Code / VSCodium -> Extensions -> "..." -> Install from VSIX...
#    -> prebuilt/beeflang-0.1.1.vsix
#    then set "beeflang.serverPath": "~/bin/BeefLsp" (absolute path) in settings
```

Open a folder containing `BeefSpace.toml`, then a `.bf` file. Note that a **folder** must be open — the
server needs a workspace root, and with only a file open it reports `No workspace path given`.

## What's in here

| Path | |
|---|---|
| `src/` | The language server (24 Beef sources) |
| `BeefProj.toml`, `BeefSpace.toml` | Its Beef project/workspace, including the macOS build configs |
| `vscode-extension/` | The VS Code extension sources (TypeScript + Svelte settings UI) |
| `prebuilt/beeflang-0.1.1.vsix` | Ready-to-install extension |
| `bin/BeefLsp` | Launcher (wraps the server, which needs a Beef dist tree as its working directory) |
| `patches/` | Our changes as patches against the upstream fork, for upstreaming |
| `tests/` | Python LSP clients used to verify the server |

## Status

Verified on macOS 27.0 (Apple Silicon), Xcode 26, against the Beef commit pinned by
[`beef-macos`](https://github.com/agorangetek/beef-macos).

**Server, driven by a Python LSP client:**

| Check | Result |
|---|---|
| `initialize` (VS Code-style capabilities) | PASS |
| `rootUri` only / `workspaceFolders` only / minimal capabilities | PASS |
| Diagnostics for a broken buffer, and clearing them when fixed | PASS — 4 diagnostics, then 0 |
| `documentSymbol` | PASS — real symbols from the workspace |
| TCP transport (`--port=N`), which the extension uses | PASS |
| `shutdown` / `exit` | PASS |

**In VSCodium, end to end:** the extension activates on `onLanguage:bf`, spawns the server, connects over
TCP, and loads the workspace — confirmed from the editor's own `Beef LSP` output channel:

```
[INFO   ] Connected
[INFO   ] Loaded workspace at /tmp/beef_example
[INFO   ] Refreshing workspace
```

### Known gaps

- Only the first entry of `workspaceFolders` is used — no multi-root support.
- URI decoding handles `%3A` and `%20` only.
- Interactive features (completion/hover popups) are exercised at the protocol level, not clicked
  through in the editor.

## Where this came from

The server is not ours: it is [MineGame159](https://github.com/MineGame159/Beef)'s `lsp` branch, an
alpha-stage community language server that had gone unmaintained since 2023. We ported it onto the
current Beef compiler and fixed the macOS problems:

- **API drift** — three compiler-output overrides now take `StringView`; `RemoveChild` gained a
  parameter; the socket calls return payload `Result`s, so `== .Err` became `case .Err`.
- **`rootUri` support** — it read only the deprecated `rootPath`, so editors that send just `rootUri`
  (Zed, Neovim, multi-root) loaded an empty workspace.
- **A handshake stall** — `OnInitialize` indexed
  `args["capabilities"]["textDocument"]["semanticTokens"]["tokenTypes"]`, and this JSON type reads
  uninitialized memory when you index into a non-object. A client that did not advertise
  `semanticTokens` made the server go silent mid-handshake.
- **A crash loop in the extension** — a fixed 1-second wait before connecting with no retry (fail five
  times, then give up permanently), and a hardcoded port 5556 that stopped two windows coexisting.
- **Noisy output** — `documentSymbol` logged a warning per unrecognised navigation entry, flooding the
  output channel.
- **`beeflang.serverPath` setting** — macOS GUI apps do not inherit the shell `PATH`, so
  `execFile("BeefLsp")` could never find a launcher in `~/bin` without it.

The socket layer also needed fixing, but that lives in Beef itself and is carried by
[`beef-macos`](https://github.com/agorangetek/beef-macos): IPv6 was broken on macOS (`AF_INET6` was
hardcoded to the Windows value, `sockaddr` lacked the BSD length byte, `addrinfo` used the glibc field
order, and socket-option values came from Linux).

## License and attribution

Two MIT-licensed works are combined here:

- **Beef** — Copyright © 2019 BeefyTech LLC — see `LICENSE-Beef.txt`
- **The language server and VS Code extension** — Copyright © 2022 MineGame159 — see
  `LICENSE-vscode-extension.txt`

Our changes are offered under the same terms.
