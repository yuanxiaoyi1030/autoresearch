# Purpose: Executes one approved Python entrypoint via fixed argv, audit-hook sandbox, bounded logs, and run snapshot.
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from research_runtime.llm import sanitized_subprocess_environment
from research_runtime.planning import canonical_hash

from .models import (
    ExperimentEnvironment, ExperimentRunStatus, ResourceUsage, RunControlRequest,
)


EXCLUDED_NAMES = {"__pycache__", ".matplotlib_cache", ".ipynb_checkpoints", ".git"}


def hash_file(path: Path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(part in EXCLUDED_NAMES for part in path.relative_to(root).parts):
            continue
        if is_reparse(path):
            raise ValueError("code tree cannot contain a symlink or junction")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


def is_reparse(path: Path) -> bool:
    value = os.lstat(str(path))
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


class D2LEnvironmentError(RuntimeError):
    pass


class D2LEnvironment:
    @staticmethod
    def resolve(dependencies: Iterable[str]) -> ExperimentEnvironment:
        executable = Path(sys.executable).resolve(strict=True)
        prefix = Path(sys.prefix).resolve(strict=True)
        conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
        if conda_env.casefold() != "d2l" or prefix.name.casefold() != "d2l":
            raise D2LEnvironmentError("Study Runtime requires activated Conda environment d2l")
        try:
            executable.relative_to(prefix)
        except ValueError:
            raise D2LEnvironmentError("Python interpreter is outside the active d2l prefix") from None
        versions: Dict[str, str] = {}
        for name in sorted(set(dependencies), key=str.casefold):
            normalized = name.strip()
            if not normalized:
                continue
            try:
                versions[normalized] = importlib.metadata.version(normalized)
            except importlib.metadata.PackageNotFoundError:
                raise D2LEnvironmentError(f"declared dependency is not installed: {normalized}") from None
        payload = {
            "python_interpreter": str(executable), "conda_env": "d2l",
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(), "dependency_versions": versions,
            "requested_device": "cpu",
        }
        return ExperimentEnvironment(environment_sha256=canonical_hash(payload), **payload)


class PreparedExecution:
    def __init__(self, *, run_root, code_root, artifact_root, stdout_path, stderr_path,
                 config_path, environment_path, profile_path, command, environment,
                 code_hash, config_hash, workspace_root):
        self.run_root = run_root
        self.code_root = code_root
        self.artifact_root = artifact_root
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.config_path = config_path
        self.environment_path = environment_path
        self.profile_path = profile_path
        self.command = command
        self.environment = environment
        self.code_hash = code_hash
        self.config_hash = config_hash
        self.workspace_root = workspace_root


class ExecutionOutcome:
    def __init__(self, status, exit_code, reason, error, usage):
        self.status = status
        self.exit_code = exit_code
        self.reason = reason
        self.error = error
        self.usage = usage


class _Capture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.saved = {"stdout": 0, "stderr": 0}
        self.observed = 0
        self.exceeded = threading.Event()
        self.lock = threading.Lock()

    def consume(self, name, chunk, stream):
        with self.lock:
            remaining = max(0, self.limit - sum(self.saved.values()))
            saved = chunk[:remaining]
            if saved:
                stream.write(saved)
                self.saved[name] += len(saved)
            self.observed += len(chunk)
            if len(chunk) > remaining or self.observed > self.limit:
                self.exceeded.set()


class LocalStudyExecutor:
    def __init__(self, known_secrets=lambda: ()) -> None:
        self.known_secrets = known_secrets
        self._slot = threading.BoundedSemaphore(1)

    def prepare(self, *, project_root: Path, workspace_root: Path, source_root: Path,
                run_id: str, entrypoint: str, approved_code_hash: str, config: dict,
                dependencies: Iterable[str], visualization_profile: Optional[dict] = None):
        project_root = project_root.resolve(strict=True)
        workspace_root = workspace_root.resolve(strict=True)
        source_root = source_root.resolve(strict=True)
        source_root.relative_to(workspace_root)
        workspace_root.relative_to(project_root)
        if is_reparse(source_root):
            raise ValueError("implementation root cannot be a symlink or junction")
        actual_hash = tree_hash(source_root)
        if actual_hash != approved_code_hash:
            raise ValueError("implementation code tree no longer matches approved hash")
        source_entrypoint = (source_root / entrypoint).resolve(strict=True)
        source_entrypoint.relative_to(source_root)
        if not source_entrypoint.is_file() or is_reparse(source_entrypoint):
            raise ValueError("approved entrypoint must be a regular file")

        run_root = project_root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        code_root = run_root / "code"
        self._snapshot(source_root, code_root)
        if tree_hash(code_root) != approved_code_hash:
            raise ValueError("run code snapshot hash mismatch")
        artifact_root = run_root / "artifacts"
        log_root = run_root / "logs"
        volatile_root = run_root / "volatile"
        artifact_root.mkdir()
        log_root.mkdir()
        volatile_root.mkdir()
        config_path = run_root / "config.json"
        environment = D2LEnvironment.resolve(dependencies)
        environment_path = run_root / "environment.json"
        profile_path = run_root / "visualization_profile.json"
        self._write_json(config_path, config)
        self._write_json(environment_path, environment.model_dump(mode="json"))
        self._write_json(profile_path, visualization_profile or {})
        bootstrap = run_root / "bootstrap.py"
        with bootstrap.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(self._bootstrap_source())
        command = [environment.python_interpreter, str(bootstrap)]
        return PreparedExecution(
            run_root=run_root, code_root=code_root, artifact_root=artifact_root,
            stdout_path=log_root / "stdout.log", stderr_path=log_root / "stderr.log",
            config_path=config_path, environment_path=environment_path,
            profile_path=profile_path, command=command, environment=environment,
            code_hash=approved_code_hash, config_hash=canonical_hash(config),
            workspace_root=workspace_root,
        )

    def execute(self, prepared: PreparedExecution, *, entrypoint: str, timeout_seconds: float,
                output_limit_bytes: int,
                control: Optional[Callable[[], RunControlRequest]] = None) -> ExecutionOutcome:
        if not self._slot.acquire(blocking=False):
            raise RuntimeError("Study Runtime concurrency limit is 1")
        try:
            return self._execute(prepared, entrypoint, timeout_seconds, output_limit_bytes,
                                 control or (lambda: RunControlRequest.NONE))
        finally:
            self._slot.release()

    def _execute(self, prepared, entrypoint, timeout_seconds, output_limit_bytes, control):
        capture = _Capture(output_limit_bytes)
        started = time.monotonic()
        process = None
        reason = None
        env = sanitized_subprocess_environment()
        secrets = tuple(value for value in self.known_secrets() if value)
        env = {name: value for name, value in env.items()
               if not any(secret in value for secret in secrets)}
        volatile = prepared.run_root / "volatile"
        env.update({
            "PYTHONUNBUFFERED": "1",
            "AUTORESEARCH_ENTRYPOINT": entrypoint,
            "AUTORESEARCH_CODE_ROOT": str(prepared.code_root),
            "AUTORESEARCH_WORKSPACE_ROOT": str(prepared.workspace_root),
            "AUTORESEARCH_CONFIG_PATH": str(prepared.config_path),
            "AUTORESEARCH_ARTIFACT_DIR": str(prepared.artifact_root),
            "AUTORESEARCH_VISUALIZATION_PROFILE_PATH": str(prepared.profile_path),
            "AUTORESEARCH_VOLATILE_DIR": str(volatile),
            "AUTORESEARCH_NETWORK_POLICY": "disabled",
            "MPLCONFIGDIR": str(volatile / "matplotlib"),
            "PYTHONPYCACHEPREFIX": str(volatile / "pycache"),
            "CUDA_VISIBLE_DEVICES": "",
            "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
        })
        creationflags = 0
        popen_kwargs = {}
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            popen_kwargs["start_new_session"] = True
        stdout_tmp = prepared.stdout_path.with_name(".stdout.tmp")
        stderr_tmp = prepared.stderr_path.with_name(".stderr.tmp")
        try:
            with stdout_tmp.open("xb") as stdout_stream, stderr_tmp.open("xb") as stderr_stream:
                process = subprocess.Popen(
                    prepared.command, cwd=str(prepared.code_root), env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=False, creationflags=creationflags, **popen_kwargs,
                )
                readers = [
                    threading.Thread(target=self._drain,
                                     args=("stdout", process.stdout, stdout_stream, capture), daemon=True),
                    threading.Thread(target=self._drain,
                                     args=("stderr", process.stderr, stderr_stream, capture), daemon=True),
                ]
                for reader in readers:
                    reader.start()
                while process.poll() is None:
                    requested = control()
                    if requested is RunControlRequest.PAUSE:
                        reason = "paused"
                        break
                    if requested is RunControlRequest.CANCEL:
                        reason = "cancelled"
                        break
                    if capture.exceeded.is_set():
                        reason = "output_limit_exceeded"
                        break
                    if time.monotonic() - started >= timeout_seconds:
                        reason = "timeout"
                        break
                    time.sleep(0.02)
                if reason:
                    self._terminate(process)
                process.wait(timeout=10)
                for reader in readers:
                    reader.join(timeout=5)
                stdout_stream.flush()
                stderr_stream.flush()
            os.replace(str(stdout_tmp), str(prepared.stdout_path))
            os.replace(str(stderr_tmp), str(prepared.stderr_path))
            if reason == "paused":
                status = ExperimentRunStatus.PAUSED
            elif reason == "cancelled":
                status = ExperimentRunStatus.CANCELLED
            elif reason == "timeout":
                status = ExperimentRunStatus.TIMED_OUT
            elif reason == "output_limit_exceeded":
                status = ExperimentRunStatus.OUTPUT_LIMIT_EXCEEDED
            elif process.returncode == 0:
                status = ExperimentRunStatus.COMPLETED
            else:
                status = ExperimentRunStatus.FAILED
            error = None if status is ExperimentRunStatus.COMPLETED else (
                reason or f"process exited with code {process.returncode}"
            )
            return ExecutionOutcome(
                status, process.returncode, reason, error,
                ResourceUsage(
                    wall_seconds=time.monotonic() - started,
                    stdout_bytes=capture.saved["stdout"], stderr_bytes=capture.saved["stderr"],
                    observed_output_bytes=capture.observed, process_id=process.pid,
                ),
            )
        except Exception as exc:
            if process is not None and process.poll() is None:
                self._terminate(process)
            for temporary, final in ((stdout_tmp, prepared.stdout_path),
                                     (stderr_tmp, prepared.stderr_path)):
                if temporary.exists() and not final.exists():
                    os.replace(str(temporary), str(final))
                elif not final.exists():
                    final.write_bytes(b"")
            return ExecutionOutcome(
                ExperimentRunStatus.FAILED, None, "runner_internal_error",
                f"{type(exc).__name__}: {exc}",
                ResourceUsage(wall_seconds=time.monotonic() - started),
            )

    @staticmethod
    def _drain(name, pipe, stream, capture):
        try:
            while True:
                chunk = pipe.read(8192)
                if not chunk:
                    return
                capture.consume(name, chunk, stream)
        finally:
            pipe.close()

    @staticmethod
    def _terminate(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, shell=False, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    @classmethod
    def _snapshot(cls, source: Path, target: Path):
        target.mkdir()
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if any(part in EXCLUDED_NAMES for part in relative.parts):
                continue
            if is_reparse(path):
                raise ValueError("implementation cannot contain symlinks or junctions")
            destination = target / relative
            if path.is_dir():
                destination.mkdir(exist_ok=True)
            elif path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with path.open("rb") as input_stream, destination.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)

    @staticmethod
    def _write_json(path: Path, payload):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _bootstrap_source() -> str:
         return '''# AutoResearch deterministic audit-hook bootstrap\nimport os, runpy, sys\nfrom pathlib import Path\ncode = Path(os.environ["AUTORESEARCH_CODE_ROOT"]).resolve()\nworkspace = Path(os.environ["AUTORESEARCH_WORKSPACE_ROOT"]).resolve()\nartifacts = Path(os.environ["AUTORESEARCH_ARTIFACT_DIR"]).resolve()\nvolatile = Path(os.environ["AUTORESEARCH_VOLATILE_DIR"]).resolve()\nconfig = Path(os.environ["AUTORESEARCH_CONFIG_PATH"]).resolve()\nprofile = Path(os.environ["AUTORESEARCH_VISUALIZATION_PROFILE_PATH"]).resolve()\nprefix = Path(sys.prefix).resolve()\nentry = (code / os.environ["AUTORESEARCH_ENTRYPOINT"]).resolve()\nif code not in entry.parents or entry.suffix.lower() != ".py":\n    raise RuntimeError("entrypoint escaped approved code snapshot")\ndef within(path, root):\n    try:\n        path.relative_to(root); return True\n    except ValueError:\n        return False\ndef audit(event, args):\n    if event.startswith("subprocess") or event.startswith("socket") or event in {"os.system", "os.posix_spawn"}:\n        raise PermissionError("process/network/native loading disabled by Study Runtime")\n    if event == "ctypes.dlopen":\n        raw = args[0] if args else None\n        if not isinstance(raw, (str, bytes, os.PathLike)):\n            raise PermissionError("native loading is limited to the active d2l runtime")\n        raw_name = os.fsdecode(raw).replace("\\\\", "/").casefold()\n        native_path = Path(raw).resolve()\n        windows_system_name = raw_name in {\n            "kernel32", "user32", "gdi32", "advapi32", "ole32",\n            "shell32", "comdlg32", "msvcrt", "ucrtbase",\n        }\n        if not (within(native_path, prefix) or windows_system_name):\n            raise PermissionError("native loading is limited to the active d2l runtime")\n        return\n    if event == "open" and args:\n        raw = args[0]\n        if not isinstance(raw, (str, bytes, os.PathLike)):\n            return\n        path = Path(raw).resolve()\n        mode = str(args[1]) if len(args) > 1 else "r"\n        writing = any(flag in mode for flag in ("w", "a", "x", "+"))\n        if writing and not (within(path, artifacts) or within(path, volatile)):\n            raise PermissionError("writes are confined to Artifact/volatile roots")\n        if not writing and not (within(path, code) or within(path, workspace) or within(path, artifacts) or within(path, volatile) or within(path, prefix) or path in {config, profile}):\n            raise PermissionError("read escaped approved workspace/runtime roots")\nsys.addaudithook(audit)\nsys.path[:] = [str(code)] + [item for item in sys.path if within(Path(item or ".").resolve(), prefix)]\nrunpy.run_path(str(entry), run_name="__main__")\n'''
