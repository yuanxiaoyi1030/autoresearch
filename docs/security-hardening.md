# Security hardening

The API and frontend reject non-loopback listeners. Browser calls use same-origin credentials and the frontend
does not persist API keys. Server-side secret scanning covers configuration views, jobs, events, LLM metadata,
results, logs, prompts, Artifacts, and child-process environments.

Imports are data-only: Python is parsed with AST, notebooks with JSON, and binaries are inventoried but not
executed. Absolute paths, `..` traversal, symlinks, junctions, and reparse-point escapes are rejected. The
`coscientist` tree and all v0.1 trees are read-only. B-mode execution occurs only from verified derived files in
the v0.2 project workspace.

LLM code packages are declarative. Static validation rejects undeclared dependencies, package management,
network/process capabilities, destructive calls, credential literals, escaped paths, and semantic differences
not approved by a newer Plan. Runners use fixed argv, `shell=False`, the active `d2l` interpreter, bounded
output/time, stripped environment, disabled network/child processes, and runtime-confined file access.

Every evidence-bearing Artifact records size and SHA-256. Content endpoints re-check the current file and deny
tampered content. Analysis is deterministically regenerated; formal Policy Guard checks override reviewer prose.
Legacy results remain `legacy_hash_verified_not_reproduced` and cannot silently become reproduced evidence.

Current residual risks:

- The Python sandbox is defense-in-depth inside the local user account, not an OS VM or hostile-code isolation
  boundary. Only validated generated code should run.
- Live provider correctness, availability, pricing, and data handling depend on the user-selected external
  provider. Automated tests use deterministic doubles and do not transmit research data externally.
- LaTeX rendering depends on locally available executables; unsupported venue packages fall back to bundled safe
  templates rather than official style files.
- Windows process termination and filesystem ACL behavior can vary. Interrupted records are retained and must be
  reviewed before resumption.
