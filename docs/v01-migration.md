# v0.1 compatibility and migration

v0.2 does not migrate or modify v0.1 in place. The only supported bridge is the explicit builtin
`builtin/weight_decay_v1`, exposed through `GET /api/builtins` and the compatibility controls in the frontend
settings page.

`POST /api/compatibility/v0.1/imports/weight-decay-v1` opens the legacy SQLite database with read-only immutable
URI flags and `query_only`. It selects the latest complete cohort matching the exact baseline/treatment × seeds
0, 1, 2 matrix, validates config hashes, CPU execution, pairing keys and eligibility, then verifies every
referenced Artifact path, ownership, size, and SHA-256. It rejects traversal and reparse points.

Verified files are copied to
`v_0_2_runtime_data/compatibility/v0_1/{manifest-hash}/artifacts/`; an atomic manifest and immutable SQLite record
make repeated imports content-idempotent. The importer hashes the source database before and after the copy and
rechecks source Artifacts. Imported content endpoints verify the copied hash again and deny tampered files.

The import proves provenance and byte integrity, not scientific reproduction. Every imported item carries
`legacy_hash_verified_not_reproduced`. To claim reproduction, create a new generic v0.2 Study and run it through
the normal approval, implementation, execution, analysis, and review gates.
