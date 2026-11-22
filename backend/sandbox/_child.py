"""Child-process entry point that executes LLM-generated code.

Started by ``SubprocessSandbox`` as ``python -I -S -B _child.py <config.json>``
with an empty environment and a throw-away working directory. It must stay
self-contained: it never imports the ``backend`` package.

Order matters:
1. resource limits (CPU, memory, file size) are applied first, soft = hard,
   so the generated code cannot raise them again;
2. pandas / matplotlib are imported and warmed up while the process is still
   trusted (they read their own files and the font cache);
3. no new processes or threads may be created (RLIMIT_NPROC);
4. an audit hook is installed: from then on files can only be read from the
   working directory and the Python installation, written only in the working
   directory, and sockets, subprocesses, ``os.system``, ``ctypes`` etc. are refused;
5. the generated code runs with a restricted set of builtins (defense in depth).
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback

_MAX_STDOUT_CHARS = 200_000
_MAX_FIGURES = 5
_MAX_LABELS = 50
_MAX_INDICATORS = 20
_CODE_FILENAME = "<generated>"

_BLOCKED_EVENT_PREFIXES = (
    "socket.",
    "subprocess.",
    "os.system",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.fork",
    "os.forkpty",
    "os.kill",
    "os.killpg",
    "os.startfile",
    "os.putenv",
    "os.unsetenv",
    "os.chmod",
    "os.chown",
    "os.chflags",
    "os.lchown",
    "os.link",
    "os.symlink",
    "os.add_dll_directory",
    "ctypes.",
    "winreg.",
    "_winapi.",
    "gc.get_objects",
    "gc.get_referrers",
    "gc.get_referents",
    "resource.setrlimit",
    "resource.prlimit",
    "urllib.Request",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "telnetlib.",
    "webbrowser.",
    "pty.",
    "mmap.",
)

# Events whose arguments are paths that are *modified*.
_WRITE_PATH_EVENTS = {
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.rename": (0, 1),
    "os.truncate": (0,),
    "os.utime": (0,),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.make_archive": (0,),
    "shutil.unpack_archive": (1,),
}
# Events whose arguments are paths that are *read*.
_READ_PATH_EVENTS = {
    "os.listdir": (0,),
    "os.scandir": (0,),
    "os.chdir": (0,),
    "glob.glob": (0,),
    "shutil.copyfile": (0,),
    "shutil.copytree": (0,),
    "shutil.unpack_archive": (0,),
}


def main(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

    sys.dont_write_bytecode = True
    sys.path.extend(config["site_paths"])
    _apply_resource_limits(config["limits"])

    # Opened before lock-down; the result is written through this handle.
    result_file = open(config["result_path"], "w", encoding="utf-8")  # noqa: SIM115
    try:
        result = _run(config)
    except BaseException as exc:  # noqa: BLE001 - report every failure
        result = _error_result(exc)
    try:
        payload = json.dumps(result)
    except Exception:  # noqa: BLE001
        payload = json.dumps({"ok": False, "error": "Result could not be serialized."})
    result_file.write(payload)
    result_file.flush()
    # Skip interpreter shutdown: atexit handlers or finalizers registered by the
    # generated code never run.
    os._exit(0)


def _apply_resource_limits(limits: dict[str, int]) -> None:
    try:
        import resource
    except ImportError:  # Windows: no setrlimit (see README "Security model")
        return

    def cap(name: str, value: int | None) -> None:
        kind = getattr(resource, name, None)
        if kind is None or not value:
            return
        _soft, hard = resource.getrlimit(kind)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(kind, (value, value))

    cap("RLIMIT_CPU", limits.get("cpu_seconds"))
    cap("RLIMIT_AS", limits.get("memory_bytes"))
    cap("RLIMIT_FSIZE", limits.get("file_bytes"))
    cap("RLIMIT_CORE", 0)


def _forbid_new_processes() -> None:
    try:
        import resource
    except ImportError:
        return
    if hasattr(resource, "RLIMIT_NPROC"):
        # 0 extra processes/threads for this user (ignored when running as root,
        # which is why the Docker image runs as an unprivileged user).
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def _run(config: dict) -> dict:
    import math
    import re
    import statistics

    import numpy as np
    import pandas as pd
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _apply_chart_style(matplotlib)

    # Warm-up: trigger lazy imports and font loading while we are still trusted.
    figure = plt.figure()
    plt.plot([0, 1], [0, 1])
    plt.title("warm-up")
    figure.savefig(io.BytesIO(), format="png")
    plt.close("all")
    pd.DataFrame({"a": [1]}).to_csv(io.StringIO())

    file_data = config.get("file_data") or {}
    rows = file_data.get("rows") or []
    columns = file_data.get("columns") or []
    df = pd.DataFrame(rows, columns=columns) if rows and columns else pd.DataFrame()

    modules = {
        "math": math,
        "numpy": np,
        "pandas": pd,
        "re": re,
        "statistics": statistics,
        "matplotlib": matplotlib,
    }

    workdir = config["workdir"]
    compiled = compile(config["code"], _CODE_FILENAME, "exec")

    _forbid_new_processes()
    _install_audit_hook(workdir=workdir, read_roots=config["read_roots"])

    # Tell the parent the trusted start-up is over: its execution timeout starts now.
    os.write(1, b"READY\n")
    os.close(1)

    stdout = _BoundedStringIO(_MAX_STDOUT_CHARS)
    builtins_for_code = _safe_builtins(_make_safe_import(modules, plt))
    printed: list[object] = []
    plain_print = builtins_for_code["print"]

    def recording_print(*args: object, **kwargs: object) -> None:
        # pandas objects shown to the user are the facts the report may rely on.
        printed.extend(arg for arg in args if isinstance(arg, (pd.Series, pd.DataFrame)))
        plain_print(*args, **kwargs)  # type: ignore[operator]

    builtins_for_code["print"] = recording_print
    exec_globals = {
        "__builtins__": builtins_for_code,
        "__name__": "__agentflow__",
        "file_data": file_data,
        "df": df,
        "math": math,
        "np": np,
        "pd": pd,
        "pandas": pd,
        "plt": plt,
        "re": re,
        "statistics": statistics,
    }
    plt.show = lambda *args, **kwargs: None  # charts are collected below
    provided = set(exec_globals)

    error: BaseException | None = None
    real_stdout = sys.stdout
    sys.stdout = stdout
    try:
        exec(compiled, exec_globals)
    except BaseException as exc:  # noqa: BLE001
        error = exc
    finally:
        sys.stdout = real_stdout

    _save_open_figures(plt, workdir)

    if error is not None:
        result = _error_result(error)
        result["stdout"] = stdout.getvalue().strip()
        return result
    variables = [(name, value) for name, value in exec_globals.items() if name not in provided and not name.startswith("_")]
    return {
        "ok": True,
        "stdout": stdout.getvalue().strip(),
        "indicators": _extract_indicators(pd, printed, variables),
    }


def _extract_indicators(pd: object, printed: list[object], variables: list[tuple[str, object]]) -> dict:
    """Per-category numbers the code computed: {indicator: {category: value}}.

    Taken from printed Series/DataFrames, then from variables. Only objects
    indexed by text labels count (a groupby result), not raw rows.
    """

    import math as _math

    found: dict[str, dict[str, float]] = {}

    def labelled(index: object) -> list[str] | None:
        if isinstance(index, pd.MultiIndex) or not 2 <= len(index) <= _MAX_LABELS:  # type: ignore[attr-defined, arg-type]
            return None
        values = list(index)  # type: ignore[call-overload]
        if not all(isinstance(value, str) for value in values):
            return None
        return values

    def add(name: str, labels: list[str], numbers: object) -> None:
        clean: dict[str, float] = {}
        for label, value in zip(labels, list(numbers)):  # type: ignore[call-overload]
            try:
                number = float(value)
            except (TypeError, ValueError):
                return
            if not _math.isfinite(number):
                return
            clean[label] = number
        if clean in found.values():
            return  # same numbers already recorded (printed, then kept in a variable)
        key, suffix = name, 2
        while key in found:
            key, suffix = f"{name}_{suffix}", suffix + 1
        found[key] = clean

    def by_dimension(measure: str, index: object) -> str:
        # "revenue" grouped by "region" -> "revenue_by_region": several breakdowns of
        # the same measure stay distinguishable.
        dimension = getattr(index, "name", None)
        if dimension is None or str(dimension).lower() in measure.lower():
            return measure
        return f"{measure}_by_{dimension}"

    def collect(obj: object, fallback: str, variable: bool = False) -> None:
        if isinstance(obj, pd.Series):  # type: ignore[attr-defined]
            labels = labelled(obj.index)
            if labels and pd.api.types.is_numeric_dtype(obj.dtype):  # type: ignore[attr-defined]
                # A variable name ("avg_price") says more than the column it came from ("price").
                if variable or obj.name is None:
                    name = fallback
                else:
                    name = by_dimension(str(obj.name), obj.index)
                add(name, labels, obj.values)
        elif isinstance(obj, pd.DataFrame):  # type: ignore[attr-defined]
            labels = labelled(obj.index)
            if labels:
                for column in obj.columns:
                    if pd.api.types.is_numeric_dtype(obj[column].dtype):  # type: ignore[attr-defined]
                        add(by_dimension(str(column), obj.index), labels, obj[column].values)

    for obj in printed:
        collect(obj, "value")
    for name, obj in variables:
        collect(obj, name, variable=True)
        if len(found) >= _MAX_INDICATORS:
            break
    return dict(list(found.items())[:_MAX_INDICATORS])


def _apply_chart_style(matplotlib: object) -> None:
    """Charts match the dark interface: panel background, blue-grey text, amber first."""

    surface, line, ink, soft = "#151b23", "#262f3b", "#e6edf3", "#9aa6b6"
    matplotlib.rcParams.update(  # type: ignore[attr-defined]
        {
            "figure.facecolor": surface,
            "savefig.facecolor": surface,
            "axes.facecolor": surface,
            "axes.edgecolor": line,
            "axes.labelcolor": soft,
            "axes.titlecolor": ink,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "figure.autolayout": True,
            "savefig.bbox": "tight",
            "grid.color": line,
            "grid.linewidth": 0.6,
            "xtick.color": soft,
            "ytick.color": soft,
            "text.color": ink,
            "legend.facecolor": surface,
            "legend.edgecolor": line,
            "axes.prop_cycle": matplotlib.cycler(  # type: ignore[attr-defined]
                color=["#F59E0B", "#58a6ff", "#3fb950", "#d2a8ff", "#f78166", "#9aa6b6"]
            ),
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _save_open_figures(plt: object, workdir: str) -> None:
    """Save figures left open, unless the code already saved its own PNG files."""

    try:
        if any(name.lower().endswith(".png") for name in os.listdir(workdir)):
            plt.close("all")  # type: ignore[attr-defined]
            return
        numbers = plt.get_fignums()[:_MAX_FIGURES]  # type: ignore[attr-defined]
        for index, number in enumerate(numbers):
            plt.figure(number).savefig(  # type: ignore[attr-defined]
                os.path.join(workdir, f"figure_{index}.png"), dpi=100, bbox_inches="tight"
            )
        plt.close("all")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a broken figure must not hide the real result
        pass


def _error_result(exc: BaseException) -> dict:
    frames = traceback.extract_tb(exc.__traceback__)
    user_frames = [frame for frame in frames if frame.filename == _CODE_FILENAME]
    lines = traceback.format_list(user_frames) + traceback.format_exception_only(type(exc), exc)
    message = str(exc) or type(exc).__name__
    return {
        "ok": False,
        "error": message,
        "error_type": type(exc).__name__,
        "traceback": "".join(lines).strip(),
    }


def _install_audit_hook(workdir: str, read_roots: list[str]) -> None:
    norm = os.path.normcase
    real = os.path.realpath
    write_root = norm(real(workdir))
    allowed_read = tuple(norm(real(root)) for root in [workdir, *read_roots])
    blocked = _BLOCKED_EVENT_PREFIXES
    write_events = dict(_WRITE_PATH_EVENTS)
    read_events = dict(_READ_PATH_EVENTS)
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    sep = os.sep
    deny = PermissionError
    fspath = os.fspath
    fsdecode = os.fsdecode

    def under(path: object, roots: tuple[str, ...]) -> bool:
        if path is None or isinstance(path, int):
            return True  # already-open file descriptor or "current directory"
        try:
            candidate = norm(real(fsdecode(fspath(path))))
        except Exception:  # noqa: BLE001
            return False
        return any(candidate == root or candidate.startswith(root + sep) for root in roots)

    def hook(event: str, args: tuple) -> None:
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & write_flags)
            )
            if not under(path, (write_root,) if writing else allowed_read):
                raise deny(f"Blocked by the AgentFlow sandbox: open {path!r}")
            return
        if event.startswith(blocked):
            raise deny(f"Blocked by the AgentFlow sandbox: {event}")
        if event in write_events:
            for index in write_events[event]:
                if index < len(args) and not under(args[index], (write_root,)):
                    raise deny(f"Blocked by the AgentFlow sandbox: {event} {args[index]!r}")
        if event in read_events:
            for index in read_events[event]:
                if index < len(args) and not under(args[index], allowed_read):
                    raise deny(f"Blocked by the AgentFlow sandbox: {event} {args[index]!r}")

    sys.addaudithook(hook)


class _BoundedStringIO(io.StringIO):
    """StringIO that silently stops growing after ``limit`` characters."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def write(self, text: str) -> int:
        remaining = self._limit - self.tell()
        if remaining > 0:
            super().write(text[:remaining])
        return len(text)


def _make_safe_import(modules: dict[str, object], plt: object):  # noqa: ANN202
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002, ANN001, ANN202
        if name == "matplotlib.pyplot":
            # `import matplotlib.pyplot as plt` asks for the package (empty
            # fromlist) and then reads its `.pyplot` attribute.
            return plt if fromlist else modules["matplotlib"]
        root = name.split(".", maxsplit=1)[0]
        if root not in modules or (name != root and root != "matplotlib"):
            raise ImportError(f"Import of '{name}' is not allowed in the AgentFlow sandbox.")
        return modules[root]

    return safe_import


def _safe_builtins(safe_import: object) -> dict[str, object]:
    import builtins

    names = (
        "abs all any bool dict enumerate filter float format int isinstance len list map "
        "max min print range reversed round set sorted str sum tuple zip "
        "Exception ValueError TypeError KeyError IndexError ZeroDivisionError"
    ).split()
    safe = {name: getattr(builtins, name) for name in names}
    safe["__import__"] = safe_import
    return safe


if __name__ == "__main__":
    main(sys.argv[1])
