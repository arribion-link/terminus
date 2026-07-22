#!/bin/bash
# Deterministically builds the local "remote" model repository used by the
# ref-gated triage scorer, plus the lockfile that pins trusted refs to
# specific commits.
#
# Produces:
#   /app/model.git                 - bare git repo (the "remote")
#   /app/config/model.lock.json    - {"<ref>": "<pinned commit sha>", ...}
#
# Refs created in the repo, and what each is for:
#   main     - initial placeholder commit, not referenced by the lockfile
#   stable   - correct, complete coefficients; lockfile pin matches the
#              branch tip exactly -> the only ref that should score
#              successfully out of the box.
#   release  - lockfile pins an earlier commit on this branch, but the
#              branch is then force-moved to a newer commit (simulating a
#              model swap after pinning) -> ref tip no longer matches the
#              pinned commit.
#   beta     - lockfile pin matches the branch tip, but the coefficients on
#              that commit are missing one contract feature and include one
#              extra, unknown key.
#   canary   - valid, complete coefficients, but this ref name is never
#              added to the lockfile at all.
set -euo pipefail

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export GIT_AUTHOR_NAME="Triage Model CI"
export GIT_AUTHOR_EMAIL="model-ci@example.invalid"
export GIT_COMMITTER_NAME="Triage Model CI"
export GIT_COMMITTER_EMAIL="model-ci@example.invalid"
export GIT_AUTHOR_DATE="2025-01-01T00:00:00Z"
export GIT_COMMITTER_DATE="2025-01-01T00:00:00Z"

git -C "$WORK" init -q -b main

write_coeffs() {
  # $1 = target file, remaining args = python literal for weights dict body
  cat > "$WORK/coefficients.json"
}

# --- main: placeholder, never trusted -------------------------------------
write_coeffs <<'EOF'
{
  "bias": 0.0,
  "weights": {
    "patient_age": 0.0,
    "patient_sex_f": 0.0,
    "visit_count": 0.0,
    "visit_ed_count": 0.0,
    "visit_acuity_max": 0.0,
    "visit_duration_total": 0.0,
    "device_spo2_min": 0.0,
    "event_count": 0.0,
    "event_severity_max": 0.0,
    "event_triage_escalation_present": 0.0
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "placeholder coefficients"
MAIN_SHA="$(git -C "$WORK" rev-parse HEAD)"

# --- stable: correct, complete coefficients -------------------------------
git -C "$WORK" checkout -q -b stable
write_coeffs <<'EOF'
{
  "bias": -2.1,
  "weights": {
    "patient_age": 0.015,
    "patient_sex_f": 0.12,
    "visit_count": 0.08,
    "visit_ed_count": 0.35,
    "visit_acuity_max": -0.22,
    "visit_duration_total": 0.004,
    "device_spo2_min": -0.05,
    "event_count": 0.10,
    "event_severity_max": 0.28,
    "event_triage_escalation_present": 0.9
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "stable: production coefficients"
STABLE_SHA="$(git -C "$WORK" rev-parse HEAD)"

# --- release: this is the commit the lockfile will pin -------------------
git -C "$WORK" checkout -q -b release "$MAIN_SHA"
write_coeffs <<'EOF'
{
  "bias": -1.8,
  "weights": {
    "patient_age": 0.014,
    "patient_sex_f": 0.10,
    "visit_count": 0.07,
    "visit_ed_count": 0.30,
    "visit_acuity_max": -0.20,
    "visit_duration_total": 0.0035,
    "device_spo2_min": -0.045,
    "event_count": 0.09,
    "event_severity_max": 0.25,
    "event_triage_escalation_present": 0.85
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "release: candidate coefficients (to be pinned)"
RELEASE_PINNED_SHA="$(git -C "$WORK" rev-parse HEAD)"

# --- beta: lockfile pin matches tip, but coefficients are malformed -------
git -C "$WORK" checkout -q -b beta "$MAIN_SHA"
write_coeffs <<'EOF'
{
  "bias": -1.5,
  "weights": {
    "patient_age": 0.013,
    "patient_sex_f": 0.11,
    "visit_count": 0.06,
    "visit_ed_count": 0.28,
    "visit_acuity_max": -0.18,
    "visit_duration_total": 0.003,
    "device_spo2_min": -0.04,
    "event_count": 0.08,
    "event_severity_max": 0.20,
    "unexpected_extra_feature": 1.0
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "beta: malformed coefficients (missing/extra keys)"
BETA_SHA="$(git -C "$WORK" rev-parse HEAD)"

# --- canary: valid, complete, but intentionally never pinned --------------
git -C "$WORK" checkout -q -b canary "$MAIN_SHA"
write_coeffs <<'EOF'
{
  "bias": -2.4,
  "weights": {
    "patient_age": 0.016,
    "patient_sex_f": 0.13,
    "visit_count": 0.09,
    "visit_ed_count": 0.38,
    "visit_acuity_max": -0.24,
    "visit_duration_total": 0.0045,
    "device_spo2_min": -0.055,
    "event_count": 0.11,
    "event_severity_max": 0.30,
    "event_triage_escalation_present": 0.95
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "canary: experimental coefficients, not for prod use"

# --- write the lockfile using the pinned SHAs captured above --------------
mkdir -p /app/config
python3 - "$STABLE_SHA" "$RELEASE_PINNED_SHA" "$BETA_SHA" <<'PYEOF'
import json
import sys

stable_sha, release_sha, beta_sha = sys.argv[1:4]
lock = {
    "stable": stable_sha,
    "release": release_sha,
    "beta": beta_sha,
}
with open("/app/config/model.lock.json", "w") as fh:
    json.dump(lock, fh, indent=2, sort_keys=True)
    fh.write("\n")
PYEOF

# --- now simulate a post-pin rewrite of "release" (the mismatch case) ----
# The lockfile above already captured RELEASE_PINNED_SHA. Moving the branch
# after that point means the repo's "release" tip no longer matches what
# was pinned -- exactly the scenario the worker must detect and reject.
git -C "$WORK" checkout -q release
write_coeffs <<'EOF'
{
  "bias": -0.9,
  "weights": {
    "patient_age": 0.030,
    "patient_sex_f": 0.40,
    "visit_count": 0.20,
    "visit_ed_count": 0.60,
    "visit_acuity_max": -0.40,
    "visit_duration_total": 0.01,
    "device_spo2_min": -0.09,
    "event_count": 0.22,
    "event_severity_max": 0.55,
    "event_triage_escalation_present": 1.4
  }
}
EOF
git -C "$WORK" add coefficients.json
git -C "$WORK" commit -q -m "release: unreviewed post-pin coefficients swap"

git -C "$WORK" checkout -q main

# --- publish as a bare repo -------------------------------------------------
rm -rf /app/model.git
git clone -q --bare "$WORK" /app/model.git
# Bare clones of local paths keep an absolute "origin" remote pointing back
# at the build scratch dir; strip it so nothing in the image references a
# path that won't exist at runtime.
git -C /app/model.git remote remove origin 2>/dev/null || true

echo "model repo built:"
echo "  main:    $MAIN_SHA"
echo "  stable:  $STABLE_SHA (lockfile pin matches tip)"
echo "  release: pinned=$RELEASE_PINNED_SHA (tip has since moved)"
echo "  beta:    $BETA_SHA (lockfile pin matches tip; coefficients malformed)"
echo "  canary:  unpinned"
