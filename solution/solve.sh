#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install the reference inference worker.
cp "$SCRIPT_DIR/infer.pl" /app/worker/infer.pl
chmod +x /app/worker/infer.pl

# Sanity check: the worker should now respond with a score instead of
# "not_implemented" for a trusted, pinned ref.
echo '{"model_ref":"stable","session":{"patient":{"age":1,"sex":"M"}}}' \
    | perl /app/worker/infer.pl > /tmp/solve_sanity_check.json

grep -q '"score"' /tmp/solve_sanity_check.json

echo "infer.pl installed and responding"
