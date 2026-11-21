"""Attack tests for the execution of LLM-generated code.

Each test plays the role of malicious (or just broken) generated code and
checks that it cannot hurt the server. They go through ``CodeExecutor.execute``,
the entry point the CodeAgent uses.

Written before the subprocess sandbox existed: they all failed against the
old in-process ``exec()`` executor.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

import backend
from backend.tools.code_executor import CodeExecutor

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="resource limits (setrlimit) only exist on POSIX"
)

SUBCLASS_OS = (
    "_wrap = [c for c in ().__class__.__base__.__subclasses__() "
    "if c.__name__ == '_wrap_close'][0]\n"
    "_os = _wrap.__init__.__globals__\n"
)


def attempt(code: str, timeout: float = 20.0) -> tuple[str, float]:
    """Run ``code`` like the CodeAgent would; return (output or error text, seconds).

    The call runs in a daemon thread so that a missing timeout makes the test
    fail instead of hanging the whole suite.
    """

    outcome: dict[str, str] = {}

    def target() -> None:
        try:
            outcome["text"] = CodeExecutor().execute(code, {"columns": [], "rows": []})
        except BaseException as exc:  # noqa: BLE001 - we want every failure mode
            outcome["text"] = f"{type(exc).__name__}: {exc}"

    started = time.monotonic()
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)
    elapsed = time.monotonic() - started
    if worker.is_alive():
        pytest.fail(f"generated code was still running after {timeout:.0f}s (not killed)")
    return outcome["text"], elapsed


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    path = tmp_path / "outside" / "secret.csv"
    path.parent.mkdir()
    path.write_text("token\nTOP-SECRET-1234\n", encoding="utf-8")
    return path


# --- Filesystem -------------------------------------------------------------


def test_cannot_read_file_outside_workdir(secret_file: Path) -> None:
    text, _ = attempt(f"print(pd.read_csv({str(secret_file)!r}).to_string())")
    assert "TOP-SECRET-1234" not in text
    assert "sandbox" in text.lower()


def test_cannot_read_backend_source_or_env() -> None:
    target = Path(list(backend.__path__)[0]) / "main.py"
    text, _ = attempt(
        f"print(pd.read_csv({str(target)!r}, sep='\\x07', header=None).to_string())"
    )
    assert "FastAPI" not in text
    assert "sandbox" in text.lower()


@POSIX_ONLY
def test_cannot_read_etc_passwd() -> None:
    text, _ = attempt("print(pd.read_csv('/etc/passwd', sep=':', header=None).to_string())")
    assert "root" not in text


def test_cannot_write_file_outside_workdir(tmp_path: Path) -> None:
    target = tmp_path / "pwned.csv"
    attempt(f"pd.DataFrame({{'a': [1]}}).to_csv({str(target)!r})")
    assert not target.exists()


# --- Escapes from the restricted builtins -----------------------------------


def test_subclasses_escape_cannot_run_shell(tmp_path: Path) -> None:
    marker = tmp_path / "escaped.txt"
    attempt(SUBCLASS_OS + f"_os['system']('echo pwned > ' + {str(marker)!r})")
    assert not marker.exists()


def test_globals_escape_cannot_open_files(secret_file: Path) -> None:
    code = (
        "_b = pd.read_csv.__globals__['__builtins__']\n"
        "_open = _b['open'] if _b.__class__ is dict else _b.open\n"
        f"print(_open({str(secret_file)!r}).read())"
    )
    text, _ = attempt(code)
    assert "TOP-SECRET-1234" not in text


# --- Network and processes --------------------------------------------------


def test_cannot_open_network_socket() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(0.5)
    port = server.getsockname()[1]
    try:
        attempt(f"pd.read_csv('http://127.0.0.1:{port}/data.csv')")
        try:
            connection, _ = server.accept()
            connection.close()
            connected = True
        except OSError:
            connected = False
    finally:
        server.close()
    assert not connected, "generated code reached a network socket"


def test_cannot_start_subprocess(tmp_path: Path) -> None:
    marker = tmp_path / "spawned.txt"
    child = f"open({str(marker)!r}, 'w').write('x')"
    code = (
        "_sp = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'Popen'][0]\n"
        f"_sp([{sys.executable!r}, '-c', {child!r}]).wait()\n"
    )
    attempt(code)
    assert not marker.exists()


# --- Resources --------------------------------------------------------------


def test_infinite_loop_is_killed_within_10_seconds() -> None:
    text, elapsed = attempt("while True:\n    pass\n")
    assert elapsed < 10
    assert "timed out" in text.lower()


@POSIX_ONLY
def test_massive_memory_allocation_is_stopped() -> None:
    code = (
        "chunks = []\n"
        "for _ in range(64):\n"
        "    chunks.append('x' * (256 * 1024 * 1024))\n"
        "print('allocated', len(chunks))"
    )
    text, _ = attempt(code, timeout=30)
    assert "allocated 64" not in text
    assert "memory" in text.lower() or "stopped by the sandbox" in text.lower()
    # The server (this process) is still healthy afterwards.
    assert CodeExecutor().execute("print(1 + 1)", {"columns": [], "rows": []}) == "2"


# --- Secrets ----------------------------------------------------------------


def test_server_environment_variables_are_invisible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    text, _ = attempt(
        SUBCLASS_OS + "print(_os['environ'].get('GROQ_API_KEY'), len(_os['environ']))"
    )
    assert "gsk-test-not-a-real-key" not in text


def test_server_still_responsive_after_attacks() -> None:
    assert CodeExecutor().execute("print(sum([1, 2, 3]))", {"columns": [], "rows": []}) == "6"
