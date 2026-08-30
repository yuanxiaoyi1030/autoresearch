<!-- Purpose: Documents running and validating the loopback-only v0.2 research console. -->
# AutoResearch v0.2 frontend

This Next.js console is a local-only view and control surface over the persisted v0.2 backend. It does not
store scientific state or API credentials in browser storage. Refresh recovery comes from SQLite-backed API
records, events, immutable revisions, runs, reviews, and paper artifacts.

The backend defaults to `http://127.0.0.1:8100`; the frontend defaults to `http://127.0.0.1:3000`. Both start
scripts bind explicitly to loopback. `AUTORESEARCH_V0_2_API_ORIGIN` may override the backend origin only with
another credential-free HTTP(S) loopback origin.

Run after dependencies have been installed with explicit user approval:

```powershell
npm run typecheck
npm run test:contract
npm run build
npm run dev
```

Provider/model configuration is persisted only as non-secret backend runtime configuration. The API-key field
submits once to backend process memory and clears immediately. The UI intentionally has no arbitrary shell,
Python, interpreter, command, or package-management entry point.
