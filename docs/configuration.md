# Configuration

`Settings` defaults to loopback host `127.0.0.1`, port `8100`, runtime root
`D:\code\work\autoresearch\v_0_2_runtime_data`, and v0.1 compatibility source
`D:\code\work\autoresearch\v_0_1_runtime_data`.

Runtime environment variables use the `AUTORESEARCH_V0_2_` prefix:

- `RUNTIME_ROOT`, `V0_1_RUNTIME_ROOT`, `ALLOWED_IMPORT_ROOTS`, `HOST`, and `PORT`;
- `LLM_PROVIDER_ID`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_PROTOCOL`, and `LLM_API_KEY`;
- the documented LLM temperature, timeout, retry, token, call, and cost budget fields.

`ALLOWED_IMPORT_ROOTS` uses the operating-system path separator. Every B-mode source must resolve below one of
these roots. The source root itself and every accessed child must not be a symlink or junction.

Users may configure a default LLM route and per-stage overrides for Project Understanding, Literature,
Hypothesis/Planning, Experiment Code, Analysis, Research Review, and Writer. The UI submits API keys separately;
keys live only in backend process memory (or their source environment) and must be supplied again after restart.
Anthropic and Gemini entries are declared extension points, not implemented providers. Fake is explicit offline
test mode and is never selected silently.

The frontend proxy origin is controlled by `AUTORESEARCH_V0_2_API_ORIGIN` and must be a credential-free HTTP(S)
loopback origin without path, query, or fragment.
