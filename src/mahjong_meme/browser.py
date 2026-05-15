"""Locate and launch a Chromium-family browser with remote debugging enabled."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# Per-OS install-location hints. shutil.which() is checked first so a binary
# on PATH always wins.
_WINDOWS_HINTS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "chromium": [
        r"C:\Program Files\Chromium\Application\chrome.exe",
    ],
}

_POSIX_HINTS = {
    "chrome": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/snap/bin/google-chrome",
    ],
    "edge": [
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
    ],
    "brave": [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
    ],
    "chromium": [
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ],
}

_PATH_CANDIDATES = {
    "chrome": ["chrome", "google-chrome", "google-chrome-stable"],
    "edge": ["msedge", "microsoft-edge"],
    "brave": ["brave", "brave-browser"],
    "chromium": ["chromium", "chromium-browser"],
}


def resolve_executable(browser: str) -> str:
    """Resolve a browser name (or path) to an executable path.

    Accepts either:
    - a known alias: 'chrome' (default), 'edge', 'brave', 'chromium'
    - an absolute or relative path to a Chromium-family binary
    """
    b = browser.strip()
    p = Path(b)
    if p.is_file():
        return str(p.resolve())

    key = b.lower()
    if key not in _PATH_CANDIDATES:
        raise SystemExit(
            f"Unknown browser '{browser}'. Use one of "
            f"{sorted(_PATH_CANDIDATES)} or pass an executable path."
        )

    for name in _PATH_CANDIDATES[key]:
        found = shutil.which(name)
        if found:
            return found

    hints = _WINDOWS_HINTS if sys.platform == "win32" else _POSIX_HINTS
    for candidate in hints.get(key, []):
        if Path(candidate).is_file():
            return candidate

    raise SystemExit(
        f"Could not locate '{browser}'. Install it or pass --browser "
        f"<absolute-path>."
    )


@dataclass
class LaunchedBrowser:
    """Handle to a launched browser child process and its temp profile."""

    executable: str
    port: int
    user_data_dir: Path
    process: subprocess.Popen
    cdp_url: str
    extra_args: list[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def wait(self) -> int:
        return self.process.wait()


def default_profile_dir(browser_alias: str = "chrome") -> Path:
    """Return a stable per-user profile directory for the given browser.

    Profile is kept under the OS-standard local-application-data area so
    cookies / login persist across runs:
      Windows: %LOCALAPPDATA%\\mahjong-meme\\profiles\\<browser>
      macOS:   ~/Library/Application Support/mahjong-meme/profiles/<browser>
      Linux:   ~/.local/share/mahjong-meme/profiles/<browser>
    """
    safe = "".join(c for c in browser_alias.lower() if c.isalnum() or c in "-_") or "browser"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "mahjong-meme" / "profiles" / safe


DEFAULT_WINDOW_SIZE = "1280,720"


def launch_browser(
    browser: str = "chrome",
    *,
    port: int = 9222,
    initial_url: str = "about:blank",
    extra_args: list[str] | None = None,
    user_data_dir: Path | str | None = None,
    window_size: str | None = DEFAULT_WINDOW_SIZE,
) -> LaunchedBrowser:
    """Launch the chosen browser with a (persistent) profile + remote debugging.

    By default uses `default_profile_dir(browser)` so cookies, login state,
    and any per-site settings persist across runs. Pass `user_data_dir=None`
    explicitly via the CLI `--temp-profile` flag to opt into a fresh
    throwaway profile.

    `window_size` is passed as `--window-size=W,H` and only takes effect
    when the user's profile doesn't already have a saved window geometry.
    Pass `window_size=None` to leave it unset.

    The browser process is detached so it survives Ctrl-C of the agent.
    """
    exe = resolve_executable(browser)
    if user_data_dir is None:
        # Sentinel value "TEMP" requests a throwaway profile; otherwise
        # callers pass an explicit Path / str (or omit the kwarg to get
        # the persistent default).
        profile = default_profile_dir(browser)
    elif isinstance(user_data_dir, str) and user_data_dir.upper() == "TEMP":
        profile = Path(tempfile.mkdtemp(prefix="mahjong-meme-profile-"))
    else:
        profile = Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)

    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=ChromeWhatsNewUI,Translate",
        # CDP allowlist: required by Chrome 111+ when attaching from a different origin.
        # 'http://localhost:<port>/json' works without it, but we set it for safety.
        "--remote-allow-origins=*",
    ]
    if window_size:
        args.append(f"--window-size={window_size}")
    if extra_args:
        args.extend(extra_args)
    # Open URL last so it lands in the first tab Playwright sees on attach.
    args.append(initial_url)

    # Detach the child so it survives Ctrl-C of the Python script if the
    # user wants to keep playing. Stdout/stderr go nowhere to avoid noise.
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(args, **kwargs)
    return LaunchedBrowser(
        executable=exe,
        port=port,
        user_data_dir=profile,
        process=proc,
        cdp_url=f"http://127.0.0.1:{port}",
        extra_args=list(extra_args or []),
    )
