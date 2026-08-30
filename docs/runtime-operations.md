# Runtime operations

## Runtime layout

The default root is `D:\code\work\autoresearch\v_0_2_runtime_data` and is initialized with:

- `autoresearch_v0_2.sqlite3` for durable projects, revisions, jobs, events, reviews, and compatibility records;
- `projects/` for isolated workspaces, implementations, runs, analyses, evidence, and papers;
- `compatibility/` for verified copies imported from v0.1;
- `cache/`, `exports/`, and `tmp/` for v0.2-only operational data.

The root must not equal, contain, or be contained by `v_0_1_runtime_data`. Runtime paths are returned by
`GET /health` and shown in the frontend footer.

## Start and verify

```powershell
conda activate d2l
python scripts/run_api.py
```

In a second terminal, run `npm run dev` from `apps/frontend`. Both commands bind only to loopback. No package
operation is part of startup.

Run backend acceptance only after activating `d2l`:

```powershell
conda activate d2l
python -m unittest discover -s tests -q
```

Frontend verification is `npm run typecheck`, `npm run test:contract`, then `npm run build`.

## Recovery semantics

Durable jobs are idempotent by project, kind, key, and payload hash. On service restart, a `running` durable job
is changed to `pending`, retains its attempt count and error history, emits `job.recovered`, and is retried as a
new attempt. Experiment runs interrupted by restart become `stale`; resume creates a child run instead of
overwriting the original. Pause, resume, cancel, failure, timeout, output-limit, and negative-result records are
append-only history.

Back up the runtime root only while the API is stopped, or use a SQLite-consistent backup procedure. Never
restore a v0.1 database over the v0.2 database.
