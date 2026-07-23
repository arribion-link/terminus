The gateway at `/app/gateway/app.py` (Flask, already working, don't touch it) accepts
`POST /v1/score` with a JSON body like `{"model_ref": "stable", "session": {...}}` and shells
out to `/app/worker/infer.pl` for the actual scoring. Right now that worker is just a stub that
returns `not_implemented` -- I need it actually written.

`session` is a nested patient-session blob (visits/devices/events, see any fixture under
`/app/fixtures` for shape). The worker has to flatten it into a feature vector that matches
the contract at `/app/contract/feature_contract.json` exactly -- names, order, and default
values when there's nothing to aggregate. That file is generated from a Polars reference
script, `/app/contract/build_contract.py`; the human-readable version of the same contract
(with the actual aggregation rules per feature) is `/app/contract/CONTRACT.md`.

Model coefficients live in a local git repo at `/app/model.git`, one `coefficients.json` per
commit, keyed by feature name. The request's `model_ref` names a branch in that repo, but
don't just trust whatever the branch currently points to -- `/app/config/model.lock.json` has
the commit each trusted ref is supposed to be pinned at. Worker needs to clone/fetch the repo,
resolve the requested ref, and refuse to score if the ref isn't in the lockfile at all, or if
it resolves to something other than the pinned commit. Also refuse if the coefficients at that
commit don't have weights for exactly the contract's feature set (missing or extra keys both
count).

On success it should respond with a score, a 0/1 label, and provenance metadata -- at minimum
the resolved commit sha and the contract version it scored against, so results are auditable
later. Same deterministic inputs should always give the same score.
