# Worker <> Gateway IPC Contract v1

The Flask gateway invokes the Perl worker as a subprocess for each request.
Communication is line-buffered JSON on stdin/stdout.

## Invocation

```
perl /app/worker/triage_worker.pl
```

One JSON line is written to worker stdin. The worker writes exactly one JSON line to stdout before exiting.

## Input (stdin)

```json
{
  "op": "score" | "ping",
  "payload": { ... },          // required when op == "score"
  "model_ref": "<ref>"         // required when op == "score"
}
```

- `op` — operation: `"score"` for inference, `"ping"` for health check.
- `payload` — patient session object per the feature contract.
- `model_ref` — git ref string per the ref policy.

## Output (stdout, success)

```json
{
  "ok": true,
  "score": 0.123456,
  "model_commit": "b224771e18be8178c0bd7858669502548498c3ba",
  "ref_kind": "commit" | "tag",
  "model_version": "1.0.0",
  "feature_order_hash": "aff334b4bb5b",
  "features": { "n_visits": 3, ... }
}
```

- `score` — probability between 0 and 1, with up to 6 fractional decimal digits.
- `model_commit` — resolved 40-hex commit SHA (lowercase).
- `ref_kind` — `"commit"` if a pinned SHA was given, `"tag"` if an annotated tag name was resolved.
- `model_version` — from the model file at that commit.
- `feature_order_hash` — first 12 hex chars of SHA-256 of comma-joined canonical feature order (per scoring spec).
- `features` — the computed feature vector for the given payload.

## Output (stdout, error)

```json
{
  "ok": false,
  "error_code": "UNPINNED_REF" | "REF_MISMATCH" | "INVALID_PAYLOAD",
  "message": "<human-readable detail>"
}
```

Error codes (the gateway maps these to HTTP):

| error_code     | HTTP | Meaning |
|---------------|------|---------|
| UNPINNED_REF  | 422  | model_ref is not a fully-pinned 40-hex SHA or valid annotated tag |
| REF_MISMATCH  | 422  | model_ref is a 40-hex SHA but not advertised by the remote |
| INVALID_PAYLOAD | 400 | payload or model_ref is missing, unparseable, or violates required schema |

If the worker exits non-zero or produces no parseable JSON, the gateway returns HTTP 502.

## Ping

For `"op":"ping"` the worker must respond:

```json
{"ok": true}
```

No other fields are required.
