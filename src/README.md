# mahjong-meme (Python)

Launches a Chromium-family browser with a clean profile + remote debug port,
attaches via CDP, navigates to Mahjong Soul, injects the observer scripts,
and streams live state. When the game asks for your input, the full state is
printed to stdout as JSON.

## Install

```powershell
cd src
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

> If `python` isn't on PATH, use the full path to a Python 3.10+ install.
> Playwright bundles its own browser drivers but we DO NOT use them — we
> attach to your real Chrome/Edge/Brave install via CDP. No need to run
> `playwright install`.

## Run

The venv's `python.exe` and the entry-point shim `mahjong-meme.exe` work
without activating the venv:

```powershell
# Default: Chrome
.\.venv\Scripts\mahjong-meme.exe

# Or pick another browser
.\.venv\Scripts\mahjong-meme.exe --browser edge
.\.venv\Scripts\mahjong-meme.exe --browser brave
.\.venv\Scripts\mahjong-meme.exe --browser path/to/chrome.exe

# Different debug port, extra flags, etc.
.\.venv\Scripts\mahjong-meme.exe --port 9333 --extra-arg=--window-size=1600,900
```

If you'd rather activate the venv first (so you can just type
`mahjong-meme`), see the troubleshooting note at the bottom.

What happens:

1. The chosen browser is launched as a child process with
   `--remote-debugging-port=<port>` and a fresh `--user-data-dir` in a temp
   directory (so it doesn't touch your normal profile). The Mahjong Soul URL
   is opened in the first tab.
2. The script attaches via CDP (`http://127.0.0.1:<port>`), grabs the page,
   and waits for Laya (`window.Laya.stage`) to finish booting.
3. The three observer scripts (`init.js` → `hook_events.js` → `state.js`)
   are injected. Re-injected automatically if the page is reloaded.
4. If you're not logged in yet, the script polls until `GameMgr.Inst.logined`
   is true. Log in normally in the browser window.
5. From that point on, `__mj.computeState()` is polled ~once per second.
   Every time `needs_my_action` flips from false to true (your turn,
   chi/pon prompt, modal, lobby decision), the full state is pretty-printed.
   Whenever `event_seq` advances, the new wire events are printed too.

## Project layout

```
src/
├── pyproject.toml
├── README.md
└── mahjong_meme/
    ├── __init__.py
    ├── __main__.py          CLI entry point (`mahjong-meme` / `python -m mahjong_meme`)
    ├── browser.py           find Chrome/Edge/Brave, launch with --remote-debugging-port
    ├── observer.py          CDP attach, script injection, state polling loop
    └── scripts/             observer scripts (self-contained copies)
        ├── init.js          installs window.__mj
        ├── hook_events.js   patches network transports, decodes ActionPrototype
        └── state.js         installs window.__mj.computeState
```

The `scripts/*.js` files are bundled as package data. The Python code does
NOT reference `skills/mahjong-soul/` — those copies are independent.

## Notes

- An "empty profile" means a fresh temp directory passed as
  `--user-data-dir`. Cookies, extensions, and sign-ins from your normal
  browser are not touched, but you'll need to log into Mahjong Soul once
  per run.
- The script does NOT close the browser on exit — Ctrl-C the script,
  close the browser yourself when done. Temp profile directories
  accumulate; clean periodically.
- This is a read-only observer. It does not click, discard, or send any
  packets. Strategy / play is up to you.

## Troubleshooting: `Activate.ps1` is blocked

On a fresh Windows install the PowerShell execution policy is `Restricted`,
which blocks `.\.venv\Scripts\Activate.ps1` with `cannot be loaded because
running scripts is disabled on this system`. Three fixes:

```powershell
# A) Just this shell session — no permanent change:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# B) Recommended — user-only, persistent, signed-only:
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

# C) Don't activate at all — call the venv's python directly:
.\.venv\Scripts\python.exe -m mahjong_meme
# or
.\.venv\Scripts\mahjong-meme.exe
```

cmd.exe / Windows Terminal users can also run the batch activator:
`.\.venv\Scripts\activate.bat`.
