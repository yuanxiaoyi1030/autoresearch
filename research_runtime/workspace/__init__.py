# Purpose: Exposes v0.2 project workspace path confinement.
from .manager import WorkspaceBoundaryError, WorkspaceManager, is_relative_to

__all__ = ["WorkspaceBoundaryError", "WorkspaceManager", "is_relative_to"]

