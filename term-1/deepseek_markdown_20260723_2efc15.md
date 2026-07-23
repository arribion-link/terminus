# Ref-Verified Inference Service

The Flask gateway at `/app/gateway.py` exposes a POST endpoint `/infer` that's stubbed out. 

## What needs to be implemented

**Git ref verification**: The bare repo at `/app/model_repo.bare` contains model coefficients on branches `main` and `develop`. The service must:

- Accept `?ref=main` or `?ref=develop` query parameters
- Verify the requested ref exists in the bare repo
- Verify the ref's commit hash matches the pin in `/app/config/pins.json`
- Reject unpinned refs with HTTP 400

**Perl feature extractor**: Write `/app/perl_worker/feature_extractor.pl` that:

- Reads JSON patient session from `--input <file>`
- Flattens visit, device, and event histories into 47 features
- Outputs a JSON array of floats matching the Polars contract

**Inference**: Load coefficients from the repo at the pinned commit:

- Use `git show <commit>:models/coefficients.json`
- Compute `score = 1 / (1 + exp(-(dot(features, coeffs) + intercept)))`
- Return JSON with `{"score": 0.753, "ref": "main", "commit": "abc123..."}`

**Caching**: Cache loaded models per ref for 5 minutes.

Run `/app/tests/test_inference.py` to verify. All 8 tests must pass.

The Perl script must handle empty visit/device/event histories gracefully.