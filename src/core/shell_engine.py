"""Command parsing, built-in helpers, and sandboxed subprocess execution.

Design notes:
- No shell is ever invoked. Lines are split with shlex and run as argv lists.
- Shell operators (| ; & < > ` $ ( )) are rejected, not interpreted.
- File access (cd, ls, external cwd) is confined to the app's home directory,
  which the user sees as /home/kali.
- External binaries are looked up on PATH. Most Linux/Kali tools are absent or
  blocked on Android; that is reported as a clear message, never a crash.
- Output is streamed line by line from a worker thread through the `emit`
  callback. The caller must marshal events onto the UI thread (see main.py).
"""
import os
import platform
import shlex
import shutil
import stat
import subprocess
import threading
from datetime import datetime

# Event kinds passed to emit(kind, text)
OUT = "out"
ERR = "err"
INFO = "info"
CLEAR = "clear"

VIRTUAL_HOME = "/home/kali"
USER_NAME = "kali"
DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_LINES = 2000
MAX_HISTORY = 200
SYSTEM_PATH = [
    "/system/bin",
    "/system/xbin",
    "/vendor/bin",
    "/apex/com.android.runtime/bin",
]
FORBIDDEN_CHARS = set("|;&<>`$()\n")


class ShellError(Exception):
    """A user-facing error raised by a built-in helper."""


class CommandHistory:
    """In-memory command history with up/down navigation."""

    def __init__(self, limit=MAX_HISTORY):
        self._items = []
        self._limit = limit
        self._pos = None      # None means "not navigating"
        self._draft = ""      # text typed before navigation started

    def add(self, command):
        if not command:
            return
        if not self._items or self._items[-1] != command:
            self._items.append(command)
            if len(self._items) > self._limit:
                del self._items[0]
        self.reset()

    def reset(self):
        self._pos = None

    def older(self, current_text):
        """Return the previous entry, or None if there is nothing older."""
        if not self._items:
            return None
        if self._pos is None:
            self._draft = current_text
            self._pos = len(self._items)
        self._pos = max(0, self._pos - 1)
        return self._items[self._pos]

    def newer(self):
        """Return the next entry, the saved draft at the end, or None if idle."""
        if self._pos is None:
            return None
        self._pos += 1
        if self._pos >= len(self._items):
            self._pos = None
            return self._draft
        return self._items[self._pos]


class _Run:
    """State for one external process."""

    def __init__(self, proc, name):
        self.proc = proc
        self.name = name
        self.cancelled = False
        self.timed_out = False


class ShellEngine:
    BUILTINS = ("help", "clear", "whoami", "uname", "pwd", "ls", "cd", "echo", "date")

    def __init__(self, home_dir, emit, timeout=DEFAULT_TIMEOUT):
        self.home = os.path.realpath(home_dir)
        os.makedirs(self.home, exist_ok=True)
        self.cwd = self.home
        self._prev_cwd = self.home
        self._emit = emit
        self._timeout = timeout
        self._lock = threading.Lock()
        self._run = None
        self._handlers = {
            "help": self._cmd_help,
            "clear": self._cmd_clear,
            "whoami": self._cmd_whoami,
            "uname": self._cmd_uname,
            "pwd": self._cmd_pwd,
            "ls": self._cmd_ls,
            "cd": self._cmd_cd,
            "echo": self._cmd_echo,
            "date": self._cmd_date,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_running(self):
        with self._lock:
            return self._run is not None

    def virtual_cwd(self):
        return self._virtual(self.cwd)

    def run(self, line):
        """Execute one command line. Built-ins finish synchronously;
        external commands stream output from a background thread."""
        line = line.strip()
        if not line:
            return

        if self.is_running():
            self._emit(ERR, "a command is already running; press CTRL+C to stop it")
            return

        bad = sorted({ch for ch in line if ch in FORBIDDEN_CHARS})
        if bad:
            self._emit(ERR, "shell operators are not supported here (found: %s)" % " ".join(bad))
            return

        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            self._emit(ERR, "parse error: %s" % exc)
            return
        if not tokens:
            return

        name, args = tokens[0], tokens[1:]
        handler = self._handlers.get(name)
        if handler is not None:
            try:
                handler(args)
            except ShellError as exc:
                self._emit(ERR, "%s: %s" % (name, exc))
            return

        self._run_external(name, args)

    def cancel(self):
        """Stop the running external process, if any. Returns True if one was stopped."""
        with self._lock:
            run = self._run
        if run is None:
            return False
        run.cancelled = True
        self._kill(run.proc)
        return True

    def shutdown(self):
        self.cancel()

    # ------------------------------------------------------------------
    # External commands
    # ------------------------------------------------------------------
    def _search_path(self):
        return os.pathsep.join(SYSTEM_PATH + [os.environ.get("PATH", "")])

    def _env(self):
        return {
            "PATH": self._search_path(),
            "HOME": self.home,
            "PWD": self.cwd,
            "USER": USER_NAME,
            "LANG": "C.UTF-8",
            "TERM": "dumb",
        }

    def _run_external(self, name, args):
        binary = shutil.which(name, path=self._search_path())
        if binary is None:
            self._emit(
                ERR,
                "%s: command not found. It is not available in the Android app "
                "sandbox, and Kali tools cannot run on this device." % name,
            )
            return

        try:
            proc = subprocess.Popen(
                [binary] + args,
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._env(),
            )
        except PermissionError:
            self._emit(
                ERR,
                "%s: permission denied by Android. This binary cannot be executed "
                "in the app sandbox." % name,
            )
            return
        except OSError as exc:
            self._emit(
                ERR,
                "%s: cannot start (%s). This binary is unavailable in the app sandbox."
                % (name, exc.strerror or exc),
            )
            return

        run = _Run(proc, name)
        with self._lock:
            self._run = run

        timer = threading.Timer(self._timeout, self._on_timeout, args=(run,))
        timer.daemon = True
        timer.start()
        threading.Thread(target=self._pump, args=(run, timer), daemon=True).start()

    def _on_timeout(self, run):
        if run.proc.poll() is None:
            run.timed_out = True
            self._kill(run.proc)

    def _pump(self, run, timer):
        """Worker thread: stream stdout line by line, then report the outcome."""
        truncated = False
        code = None
        try:
            count = 0
            for raw in iter(run.proc.stdout.readline, b""):
                count += 1
                if count > MAX_OUTPUT_LINES:
                    truncated = True
                    self._kill(run.proc)
                    break
                self._emit(OUT, raw.decode("utf-8", "replace").rstrip("\r\n"))
            code = run.proc.wait()
        except Exception as exc:  # keep the worker from dying silently
            self._emit(ERR, "%s: output stream failed: %s" % (run.name, exc))
        finally:
            timer.cancel()
            try:
                run.proc.stdout.close()
            except OSError:
                pass
            with self._lock:
                self._run = None

        if truncated:
            self._emit(INFO, "output limit reached (%d lines); process stopped" % MAX_OUTPUT_LINES)
        elif run.cancelled:
            self._emit(INFO, "process stopped")
        elif run.timed_out:
            self._emit(ERR, "%s: timed out after %ss and was stopped" % (run.name, self._timeout))
        elif code:
            self._emit(ERR, "%s: exited with status %s" % (run.name, code))

    @staticmethod
    def _kill(proc):
        try:
            proc.kill()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Path handling (sandboxed)
    # ------------------------------------------------------------------
    def _virtual(self, real_path):
        rel = os.path.relpath(real_path, self.home)
        if rel == ".":
            return VIRTUAL_HOME
        return VIRTUAL_HOME + "/" + rel.replace(os.sep, "/")

    def _resolve(self, path):
        """Map a user path to a real path inside the sandbox, or raise ShellError."""
        if path in ("", "~"):
            path = VIRTUAL_HOME
        elif path.startswith("~/"):
            path = VIRTUAL_HOME + path[1:]

        if os.path.isabs(path):
            if path != VIRTUAL_HOME and not path.startswith(VIRTUAL_HOME + "/"):
                raise ShellError("%s: access denied outside the app sandbox" % path)
            full = os.path.join(self.home, path[len(VIRTUAL_HOME):].lstrip("/"))
        else:
            full = os.path.join(self.cwd, path)

        full = os.path.realpath(full)
        if full != self.home and not full.startswith(self.home + os.sep):
            raise ShellError("%s: access denied outside the app sandbox" % path)
        return full

    # ------------------------------------------------------------------
    # Built-in helpers
    # ------------------------------------------------------------------
    def _cmd_help(self, args):
        lines = [
            "Built-in commands:",
            "  help             show this list",
            "  clear            clear the output log",
            "  whoami           print the sandbox user",
            "  uname [-asnrvm]  print system information (default: -s)",
            "  pwd              print the working directory",
            "  ls [-al] [path]  list directory contents",
            "  cd [path]        change directory (sandboxed; 'cd -' goes back)",
            "  echo [text]      print text",
            "  date             print the current date and time",
            "",
            "Other commands run as external binaries if Android permits them.",
            "Shell operators (| ; & < > $ ` ( )) are not supported.",
        ]
        for line in lines:
            self._emit(OUT, line)

    def _cmd_clear(self, args):
        self._emit(CLEAR, "")

    def _cmd_whoami(self, args):
        self._emit(OUT, USER_NAME)

    def _cmd_echo(self, args):
        self._emit(OUT, " ".join(args))

    def _cmd_date(self, args):
        self._emit(OUT, datetime.now().strftime("%a %b %d %H:%M:%S %Y"))

    def _cmd_pwd(self, args):
        if args:
            raise ShellError("too many arguments")
        self._emit(OUT, self.virtual_cwd())

    def _cmd_uname(self, args):
        flags = set()
        for arg in args:
            if arg == "--all":
                flags.add("a")
            elif arg.startswith("-") and len(arg) > 1:
                for ch in arg[1:]:
                    if ch not in "asnrvm":
                        raise ShellError("invalid option -- '%s'" % ch)
                    flags.add(ch)
            else:
                raise ShellError("extra operand '%s'" % arg)
        if not flags:
            flags = {"s"}

        info = platform.uname()
        values = {
            "s": info.system or "Linux",
            "n": info.node,
            "r": info.release,
            "v": info.version,
            "m": info.machine,
        }
        keys = "snrvm" if "a" in flags else [k for k in "snrvm" if k in flags]
        parts = [values[k] for k in keys if values[k]]
        if "a" in flags:
            parts.append("Android")
        self._emit(OUT, " ".join(parts))

    def _cmd_cd(self, args):
        if len(args) > 1:
            raise ShellError("too many arguments")
        target = args[0] if args else "~"
        dest = self._prev_cwd if target == "-" else self._resolve(target)

        if not os.path.isdir(dest):
            if os.path.exists(dest):
                raise ShellError("%s: Not a directory" % target)
            raise ShellError("%s: No such file or directory" % target)

        self._prev_cwd = self.cwd
        self.cwd = dest

    def _cmd_ls(self, args):
        show_all = False
        long_format = False
        paths = []
        for arg in args:
            if arg.startswith("-") and len(arg) > 1:
                for ch in arg[1:]:
                    if ch == "a":
                        show_all = True
                    elif ch == "l":
                        long_format = True
                    elif ch == "1":
                        pass
                    else:
                        raise ShellError("invalid option -- '%s'" % ch)
            else:
                paths.append(arg)
        if not paths:
            paths = ["."]

        multi = len(paths) > 1
        for index, path in enumerate(paths):
            try:
                full = self._resolve(path)
            except ShellError as exc:
                self._emit(ERR, "ls: %s" % exc)
                continue

            if not os.path.exists(full):
                self._emit(ERR, "ls: cannot access '%s': No such file or directory" % path)
                continue

            if not os.path.isdir(full):
                self._emit(OUT, self._long_line(full, path) if long_format else path)
                continue

            try:
                names = sorted(os.listdir(full), key=str.lower)
            except OSError as exc:
                self._emit(ERR, "ls: cannot open '%s': %s" % (path, exc.strerror or exc))
                continue

            if not show_all:
                names = [n for n in names if not n.startswith(".")]
            else:
                names = [".", ".."] + names

            if multi:
                self._emit(OUT, "%s:" % path)
            if long_format:
                for name in names:
                    self._emit(OUT, self._long_line(os.path.join(full, name), name))
            elif names:
                self._emit(OUT, "  ".join(names))
            if multi and index < len(paths) - 1:
                self._emit(OUT, "")

    @staticmethod
    def _long_line(path, name):
        try:
            st = os.stat(path)
        except OSError:
            return "?????????  %s" % name
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%b %d %H:%M")
        return "%s %8d %s %s" % (stat.filemode(st.st_mode), st.st_size, mtime, name)