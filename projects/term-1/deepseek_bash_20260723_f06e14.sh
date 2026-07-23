#!/bin/bash
set -uo pipefail

mkdir -p /logs/verifier

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set"
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

cd /app
python gateway.py &
SERVICE_PID=$!
sleep 5

python -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
rc=$?

kill $SERVICE_PID 2>/dev/null || true

if [ $rc -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi