"""Run generated code in a separate, locked-down Python process."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
from pathlib import Path
from typing import Any

from backend.sandbox.base import SandboxResult

_RUNNER = Path(__file__).with_name("_child.py")
_MAX_IMAGES = 5
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_FONT_DIRS = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts"),
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class SubprocessSandbox:
    """Execute code with ``python -I -S`` in a temporary directory.

    Isolation layers (see README "Security model"):
    - separate process, empty environment, temporary ``cwd`` holding only
      copies of the input files, deleted afterwards;
    - hard wall-clock timeout, then the whole process group is killed;
    - POSIX resource limits (CPU, address space, file size, no new processes);
    - an audit hook in the child refusing file access outside the working
      directory, sockets, subprocesses, ``os.system``, ``ctypes``...
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        memory_mb: int | None = None,
        max_file_mb: int | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds or _env_int("SANDBOX_TIMEOUT_SECONDS", 5)
        self.startup_timeout_seconds = _env_int("SANDBOX_STARTUP_TIMEOUT_SECONDS", 60)
        self.memory_mb = memory_mb or _env_int("SANDBOX_MEMORY_MB", 1024)
        self.max_file_mb = max_file_mb or _env_int("SANDBOX_MAX_FILE_MB", 20)
        self.python_executable = python_executable or sys.executable
        self.cache_dir = Path(
            os.environ.get("SANDBOX_CACHE_DIR")
            or Path(tempfile.gettempdir()) / "agentflow-sandbox-cache"
        )

    def run(
        self,
        code: str,
        file_data: dict[str, Any] | None = None,
        input_files: list[Path] | None = None,
    ) -> SandboxResult:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="agentflow-run-", ignore_cleanup_errors=True
        ) as private_dir:
            private = Path(private_dir)
            workdir = private / "work"
            workdir.mkdir()
            for source in input_files or []:
                shutil.copyfile(source, workdir / Path(source).name)

            result_path = private / "result.json"
            config_path = private / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "code": code,
                        "file_data": file_data or {},
                        "workdir": str(workdir),
                        "result_path": str(result_path),
                        "site_paths": self._site_paths(),
                        "read_roots": self._read_roots(),
                        "limits": {
                            # Backstop only; the wall-clock timeout fires first.
                            "cpu_seconds": int(self.timeout_seconds + self.startup_timeout_seconds),
                            "memory_bytes": self.memory_mb * 1024 * 1024,
                            "file_bytes": self.max_file_mb * 1024 * 1024,
                        },
                    },
                    default=str,
                ),
                encoding="utf-8",
            )

            log_path = private / "child.log"
            with log_path.open("wb") as log:
                process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                    [self.python_executable, "-I", "-S", "-B", str(_RUNNER), str(config_path)],
                    cwd=workdir,
                    env=self._child_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    **self._process_group_kwargs(),
                )
                try:
                    # Trusted start-up (imports, font cache) has its own budget;
                    # the execution timeout starts once the child is locked down.
                    if not self._wait_until_ready(process):
                        self._kill(process)
                        return SandboxResult(
                            ok=False,
                            error="The sandbox did not start in time.",
                            error_type="SandboxError",
                        )
                    process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    self._kill(process)
                    return SandboxResult(
                        ok=False,
                        error=f"Code execution timed out after {self.timeout_seconds:g} seconds.",
                        error_type="TimeoutError",
                        timed_out=True,
                    )
                finally:
                    if process.stdout is not None:
                        process.stdout.close()

            images = self._collect_images(workdir)
            return self._read_result(process.returncode, result_path, log_path, images)

    # -- helpers --------------------------------------------------------------

    def _wait_until_ready(self, process: subprocess.Popen[bytes]) -> bool:
        """Wait for the child's READY line (or its exit) within the start-up budget."""

        line: list[bytes] = []
        reader = threading.Thread(
            target=lambda: line.append(process.stdout.readline() if process.stdout else b""),
            daemon=True,
        )
        reader.start()
        reader.join(self.startup_timeout_seconds)
        return not reader.is_alive()

    def _child_env(self) -> dict[str, str]:
        env = {
            "MPLCONFIGDIR": str(self.cache_dir),
            "MPLBACKEND": "Agg",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        if sys.platform == "win32":
            # Needed by the Windows CRT / numpy to start; not a secret.
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        return env

    def _site_paths(self) -> list[str]:
        paths = sysconfig.get_paths()
        return sorted({paths["purelib"], paths["platlib"]})

    def _read_roots(self) -> list[str]:
        roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
        roots.update(self._site_paths())
        roots.update(path for path in _FONT_DIRS if os.path.isdir(path))
        roots.add(str(self.cache_dir))
        return sorted(roots)

    @staticmethod
    def _process_group_kwargs() -> dict[str, Any]:
        if sys.platform == "win32":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if sys.platform == "win32":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()
        process.wait()

    @staticmethod
    def _collect_images(workdir: Path) -> list[bytes]:
        images: list[bytes] = []
        for path in sorted(workdir.glob("*.png"))[:_MAX_IMAGES]:
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= _MAX_IMAGE_BYTES:
                images.append(path.read_bytes())
        return images

    @staticmethod
    def _read_result(
        returncode: int, result_path: Path, log_path: Path, images: list[bytes]
    ) -> SandboxResult:
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None

        if not isinstance(data, dict):
            if returncode < 0:
                reason = f"signal {-returncode}"
                error = f"Execution was stopped by the sandbox ({reason}: resource limit exceeded)."
            else:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-500:].strip()
                error = f"Execution failed (exit code {returncode}). {tail}".strip()
            return SandboxResult(ok=False, error=error, error_type="SandboxError", images=images)

        return SandboxResult(
            ok=bool(data.get("ok")),
            stdout=str(data.get("stdout") or ""),
            error=data.get("error"),
            error_type=data.get("error_type"),
            traceback=data.get("traceback"),
            images=images,
        )
