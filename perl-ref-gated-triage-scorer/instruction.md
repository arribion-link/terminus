the flask gateway at /app/gateway/app.py exposes a /score endpoint that delegates to a perl worker at /app/worker/triage_worker.pl. right now the worker is a stub — it just exits with an error.

i need you to implement the worker in perl. it receives patient session json from the gateway and must pull model coefficients from a local bare git repo at /srv/model-repo.git per the verification rules. then flatten the nested patient data into exactly 12 features and compute a logistic score. the response must include provenance metadata and the score rounded to 6 decimal places.

all the specs are in /app/spec/:
- feature_contract.md — exactly what 12 features to compute and how
- scoring.md — the formula, rounding, response schema, feature order hash
- ref_policy.md — how to resolve model_ref strings and what to reject
- ipc_contract.md — the json protocol between gateway and worker

there's also a polars reference script at /app/ref/contract_reference.py that shows the feature math on a tiny example — it does not handle all the edge cases so lean on the spec docs.

the worker must use only perl core modules (no cpan). after you're done the gateway's /health should return {"status":"ok","worker":"ok"} and /score should work against the tags and commits shipped in the repo.
