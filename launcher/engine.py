"""
DeepSeek Harness Engine Manager
Manages the Node.js subprocess, port detection, log capture, and browser open.
Pure logic, no GUI dependencies - easy to test.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


# ---- Path helpers ----------------------------------------------------------

def _app_root() -> Path:
    """Resolve the offline package root from env or launcher location."""
    from_env = os.environ.get("DSH_APP_ROOT")
    if from_env:
        return Path(from_env).resolve()
    # launcher/app.py lives in <root>/launcher/, so parent is <root>/
    return Path(__file__).resolve().parent.parent


def _node_exe() -> Path:
    return _app_root() / "runtime" / "node" / "node.exe"


def _dsh_cli() -> Path:
    """Resolve the dsh CLI entry (apps/cli/lib/bin.js, produced by build).

    The DSH monorepo places the compiled CLI under apps/cli/lib/bin.js.
    A .cmd shim also exists in node_modules/.bin/dsh.cmd, but invoking the
    JS file directly via node.exe avoids shell/cmd wrapping issues.
    """
    root = _app_root()
    # 1) Preferred: the bundled offline dsh-core (copy of built repo, minus .git)
    # 2) Fallback: sibling deepseek-harness-official (for dev convenience)
    roots = [
        root / "dsh-core",
        root.parent / "deepseek-harness-official",
    ]
    candidates: list[Path] = []
    for r in roots:
        candidates.append(r / "apps" / "cli" / "lib" / "bin.js")     # built CLI entry
        candidates.append(r / "apps" / "cli" / "lib" / "bin.mjs")    # alt ESM build
        candidates.append(r / "node_modules" / ".bin" / "dsh.cmd")   # cmd shim
        candidates.append(r / "node_modules" / ".bin" / "dsh")       # Cygwin/Git Bash shim
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Cannot find dsh CLI entry. Has 'pnpm run build' been executed?\n"
        "Expected one of:\n  - "
        + "\n  - ".join(str(c) for c in candidates)
    )


# ---- Port utilities --------------------------------------------------------

def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return False  # something is listening -> not free
        except OSError:
            return True


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    return not _port_free(port, host)


def find_free_port(start: int = 3080, max_tries: int = 10) -> int:
    for p in range(start, start + max_tries):
        if _port_free(p):
            return p
    raise RuntimeError(f"No free port found in range {start}-{start + max_tries - 1}")


# ---- Engine ----------------------------------------------------------------

class EngineState:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# Regexes to extract the per-session auth token printed by `dsh web`.
# Example line:
#   dsh web: http://127.0.0.1:3080/?token=69VgjsQTuoWf_BJNtIDYKLL0Lb4EaNeXVIt_aufC88I
# Some builds may also emit with a profile name prefix: "dsh web <profile>: URL"
_TOKEN_URL_RE = re.compile(
    r"(?P<header>dsh\s+web(?:\s+\S+)?\s*:\s*)"
    r"https?://(?P<host>[^/\s:]+)(?::(?P<port>\d+))?"
    r"(?:/\S*)?\?token=(?P<token>[A-Za-z0-9_\-]+)"
)

# Back-up: bare "?token=..." occurrences (e.g. log lines that contain a clickable URL
# without the "dsh web:" prefix)
_BARE_TOKEN_RE = re.compile(r"[\?&]token=([A-Za-z0-9_\-]+)")


class DSHEngine:
    """Lifecycle manager for the DeepSeek Harness Node process."""

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_ready: Optional[Callable[[int, str], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None
        self.token: Optional[str] = None          # per-session auth token from `dsh web:` line
        self.state: str = EngineState.STOPPED
        self._token_ready_evt = threading.Event()  # signalled once self.token is populated
        self._log_file_path: Optional[Path] = None
        self._log_fp = None
        self._reader_thread: Optional[threading.Thread] = None
        self._waiter_thread: Optional[threading.Thread] = None
        # Callbacks (expected to be thread-safe / use queue in GUI)
        self.on_log = on_log or (lambda _line: None)
        # on_ready signature: (port, full_url_with_token_or_fallback)
        self.on_ready = on_ready or (lambda _port, _url: None)
        self.on_state_change = on_state_change or (lambda _s: None)

    # -- state --
    def _set_state(self, s: str) -> None:
        self.state = s
        try:
            self.on_state_change(s)
        except Exception:
            pass

    # -- token capture --
    def _capture_token_from_line(self, line: str) -> None:
        """Extract and remember the per-session web auth token.

        The DSH CLI prints a line similar to:
            dsh web: http://127.0.0.1:3080/?token=ABCXYZ
        The token regenerates every run, so we MUST read it from stdout and
        append ?token=... to every URL we pass to the browser, otherwise
        users see "dsh web authentication required" (HTTP 401) on a bare URL.
        """
        if self.token:
            return  # already captured for this session
        m = _TOKEN_URL_RE.search(line)
        if m:
            self.token = m.group("token")
            self._token_ready_evt.set()
            return
        # Fallback: any "?token=XYZ" or "&token=XYZ" fragment
        b = _BARE_TOKEN_RE.search(line)
        if b:
            self.token = b.group(1)
            self._token_ready_evt.set()

    def web_url(self) -> str:
        """Return the browseable Web UI URL WITH the auth ?token= query.

        Falls back to the bare http://...:port/ URL if the token hasn't been
        captured yet (consumer should retry a moment later, or the user will
        see a 401 and be told by DSH to use the URL printed by `dsh web`).
        """
        if not self.port:
            return ""
        base = f"http://127.0.0.1:{self.port}/"
        if self.token:
            return f"{base}?token={self.token}"
        return base

    # -- logging helpers --
    def _write_log(self, line: str) -> None:
        stamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}"
        try:
            self.on_log(stamped)
        except Exception:
            pass
        if self._log_fp:
            try:
                self._log_fp.write(stamped + "\n")
                self._log_fp.flush()
            except Exception:
                pass

    def _open_log_file(self) -> None:
        log_dir = _app_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fname = datetime.now().strftime("dsh-engine-%Y%m%d.log")
        self._log_file_path = log_dir / fname
        self._log_fp = self._log_file_path.open("a", encoding="utf-8")

    # -- lifecycle --
    def start(self) -> tuple[bool, str]:
        if self.state in (EngineState.STARTING, EngineState.RUNNING):
            return False, f"Already {self.state}."

        # Reset per-session auth state from previous runs (stop/start cycle)
        self.token = None
        self._token_ready_evt.clear()

        self._set_state(EngineState.STARTING)
        self._open_log_file()
        self._write_log("=== Engine start requested ===")

        # Validate files
        node = _node_exe()
        try:
            cli = _dsh_cli()
        except FileNotFoundError as e:
            msg = str(e)
            self._write_log(f"[ERROR] {msg}")
            self._set_state(EngineState.ERROR)
            return False, msg
        if not node.exists():
            msg = f"Node executable missing: {node}"
            self._write_log(f"[ERROR] {msg}")
            self._set_state(EngineState.ERROR)
            return False, msg

        # Pick port
        try:
            self.port = find_free_port(3080)
            self._write_log(f"Selected port: {self.port}")
        except RuntimeError as e:
            msg = str(e)
            self._write_log(f"[ERROR] {msg}")
            self._set_state(EngineState.ERROR)
            return False, msg

        # Compose args. The dsh CLI is a JS file invoked via node.
        if cli.suffix in (".cmd", ".bat"):
            # Shell launcher - use cmd /c for .cmd/.bat
            args = ["cmd", "/c", str(cli), "web", "--port", str(self.port), "--no-open"]
            shell_kw: dict = {"shell": False}
        else:
            args = [str(node), str(cli), "web", "--port", str(self.port), "--no-open"]
            shell_kw = {"shell": False}

        app_root = _app_root()
        dsh_home = app_root / ".dsh-home"
        dsh_home.mkdir(parents=True, exist_ok=True)
        # Redirect all caches and DSH user data into the offline folder so the
        # whole distribution is "portable" when copied to another PC or drive.
        local_cache = app_root / ".cache"
        local_cache.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        # --- Portable directory overrides (never touch C:\Users\...) ---
        env["DSH_HOME"] = str(dsh_home)                   # user API keys, sessions
        env["USERPROFILE"] = str(dsh_home)                # fallback (some libs read this)
        env["npm_config_cache"] = str(local_cache / "npm")
        env["pnpm_home"] = str(local_cache / "pnpm")
        env["pnpm_store_dir"] = str(local_cache / "pnpm-store")
        env["NODE_PATH"] = str(app_root / "dsh-core" / "node_modules")
        env["TMP"] = str(local_cache / "tmp")
        env["TEMP"] = str(local_cache / "tmp")
        (local_cache / "tmp").mkdir(parents=True, exist_ok=True)

        # Ensure our portable Node is on PATH for any child process dsh might spawn
        node_dir = str(node.parent)
        existing_path = env.get("PATH", "")
        if node_dir not in existing_path:
            env["PATH"] = node_dir + os.pathsep + existing_path

        self._write_log(f"DSH_HOME: {dsh_home}")
        self._write_log(f"Command: {' '.join(args)}")
        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                cwd=str(app_root / "dsh-core"),
                **shell_kw,
            )
        except OSError as e:
            msg = f"Failed to launch process: {e}"
            self._write_log(f"[ERROR] {msg}")
            self.proc = None
            self._set_state(EngineState.ERROR)
            return False, msg

        # Start log reader thread
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # Start waiter thread (detect ready -> open browser)
        self._waiter_thread = threading.Thread(target=self._wait_and_notify, daemon=True)
        self._waiter_thread.start()

        return True, f"Starting on port {self.port}..."

    def stop(self, timeout: float = 5.0) -> tuple[bool, str]:
        if self.proc is None:
            self._set_state(EngineState.STOPPED)
            return True, "Not running."

        self._write_log("=== Engine stop requested ===")

        # Try graceful terminate first
        try:
            self.proc.terminate()
        except OSError:
            pass

        deadline = time.time() + timeout
        while time.time() < deadline and self.proc.poll() is None:
            time.sleep(0.1)

        if self.proc.poll() is None:
            # Force kill
            self._write_log("[WARN] Graceful stop timed out, killing process...")
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        code = self.proc.returncode
        self.proc = None
        self._write_log(f"Engine stopped (exit code {code})")
        self._set_state(EngineState.STOPPED)

        # Close log file handle to release it
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None

        return True, f"Stopped (exit {code})."

    # -- background threads --
    def _reader_loop(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for raw in self.proc.stdout:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                # Capture the per-session auth token BEFORE writing the log line
                # (we want to have the URL handy the instant the log reveals it).
                try:
                    self._capture_token_from_line(line)
                except Exception:
                    pass
                try:
                    self._write_log(line)
                except Exception:
                    pass
        except Exception as e:
            try:
                self._write_log(f"[READER ERROR] {e}")
            except Exception:
                pass
        finally:
            # Process exited
            if self.state != EngineState.STOPPED:
                self._write_log("Process exited unexpectedly.")
                self._set_state(EngineState.ERROR)
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None

    def _wait_and_notify(self) -> None:
        assert self.port is not None
        # 1) Wait up to 90 s for the HTTP listener to start accepting TCP.
        deadline = time.time() + 90
        port_up = False
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return  # died
            if _port_in_use(self.port):
                port_up = True
                break
            time.sleep(0.5)
        if not port_up:
            self._write_log("[WARN] Timed out waiting for port to open.")
            if self.state == EngineState.STARTING:
                self._set_state(EngineState.ERROR)
            return

        # 2) The listener is up but DSH may not have printed `dsh web: ...?token=`
        #    yet. The token is required or users see HTTP 401 "authentication
        #    required". Give it a few more seconds (dsh usually prints it within
        #    ~500 ms of "Web UI is ready", but we wait gracefully just in case).
        if not self.token:
            self._write_log("Port up, waiting briefly for DSH auth token line...")
            self._token_ready_evt.wait(timeout=15)

        url = self.web_url()
        # Be explicit in logs about whether the token was captured - helps
        # users troubleshoot "why does my browser show 401?" in the future.
        if self.token:
            self._write_log(f"Web UI is ready at {url}")
        else:
            self._write_log(
                "Web UI port is UP but the auth token line was not captured. "
                "Use the `dsh web:` URL printed above, or ?token=... from logs."
            )
            self._write_log(f"Web UI (no token): {url}")
        self._set_state(EngineState.RUNNING)
        try:
            self.on_ready(self.port, url)
        except Exception:
            pass
        # Auto-open the browser the FIRST time the engine transitions to RUNNING.
        # This is the behavior the GUI advertises ("...启动成功后会自动打开浏览器").
        try:
            webbrowser.open(url, new=2)
            self._write_log(f"Opened browser: {url}")
        except Exception as e:
            self._write_log(f"[ERROR] Failed to auto-open browser: {e}")

    # -- public helpers --
    def open_browser(self) -> bool:
        if self.state != EngineState.RUNNING or not self.port:
            return False
        # If the token somehow wasn't captured during this session, do one
        # last wait before falling back to a bare URL.
        if not self.token:
            self._token_ready_evt.wait(timeout=3)
        url = self.web_url()
        try:
            webbrowser.open(url, new=2)
            if self.token:
                self._write_log(f"Opened browser: {url}")
            else:
                self._write_log(
                    f"Opened browser WITHOUT auth token (HTTP 401 likely). "
                    f"Use the `dsh web:` URL printed in logs. {url}"
                )
            return True
        except Exception as e:
            self._write_log(f"[ERROR] Failed to open browser: {e}")
            return False

    def log_file_path(self) -> Optional[Path]:
        return self._log_file_path

    def is_running_or_starting(self) -> bool:
        return self.state in (EngineState.STARTING, EngineState.RUNNING)


# ---- Convenience: open folders --------------------------------------------

def open_folder_in_explorer(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def open_logs_folder() -> None:
    open_folder_in_explorer(_app_root() / "logs")


def open_workspace_folder() -> None:
    open_folder_in_explorer(_app_root())
