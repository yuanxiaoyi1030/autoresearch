# Purpose: Loads validated v0.2 runtime, import-root, and loopback API settings.
import os
from pathlib import Path
from typing import Iterable, Tuple


DEFAULT_RUNTIME_ROOT = Path(r"D:\code\work\autoresearch\v_0_2_runtime_data")
DEFAULT_ALLOWED_IMPORT_ROOTS = (Path(r"D:\ml_project"),)
DEFAULT_V0_1_RUNTIME_ROOT = Path(r"D:\code\work\autoresearch\v_0_1_runtime_data")
ENV_PREFIX = "AUTORESEARCH_V0_2_"


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class Settings:
    def __init__(
        self,
        runtime_root: Path = DEFAULT_RUNTIME_ROOT,
        allowed_import_roots: Iterable[Path] = DEFAULT_ALLOWED_IMPORT_ROOTS,
        v0_1_runtime_root: Path = DEFAULT_V0_1_RUNTIME_ROOT,
        host: str = "127.0.0.1",
        port: int = 8100,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("API host must be loopback")
        self.runtime_root = _resolved(Path(runtime_root))
        v0_1_root = _resolved(Path(v0_1_runtime_root))
        if (self.runtime_root == v0_1_root
                or _is_relative_to(self.runtime_root, v0_1_root)
                or _is_relative_to(v0_1_root, self.runtime_root)):
            raise ValueError("v0.2 runtime root must not overlap v0.1 runtime data")
        self.v0_1_runtime_root = v0_1_root
        self.allowed_import_roots: Tuple[Path, ...] = tuple(
            _resolved(Path(path)) for path in allowed_import_roots
        )
        if not self.allowed_import_roots:
            raise ValueError("at least one allowed import root is required")
        self.host = host
        self.port = int(port)

    @classmethod
    def from_env(cls) -> "Settings":
        roots = os.environ.get(ENV_PREFIX + "ALLOWED_IMPORT_ROOTS")
        allowed = [Path(item) for item in roots.split(os.pathsep) if item] if roots else DEFAULT_ALLOWED_IMPORT_ROOTS
        return cls(
            runtime_root=Path(os.environ.get(ENV_PREFIX + "RUNTIME_ROOT", str(DEFAULT_RUNTIME_ROOT))),
            v0_1_runtime_root=Path(os.environ.get(
                ENV_PREFIX + "V0_1_RUNTIME_ROOT", str(DEFAULT_V0_1_RUNTIME_ROOT),
            )),
            allowed_import_roots=allowed,
            host=os.environ.get(ENV_PREFIX + "HOST", "127.0.0.1"),
            port=int(os.environ.get(ENV_PREFIX + "PORT", "8100")),
        )
