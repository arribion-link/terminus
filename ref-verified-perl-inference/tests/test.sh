# Start the gateway if it isn't already up
if ! curl -s -o /dev/null http://127.0.0.1:8080/healthz; then
    # Use -u for unbuffered output, so logs appear immediately
    nohup python3 -u /app/gateway/app.py > /tmp/gateway.log 2>&1 &
    # Wait up to 30 seconds (60 * 0.5)
    for _ in $(seq 1 60); do
        if curl -s -o /dev/null http://127.0.0.1:8080/healthz; then
            break
        fi
        sleep 0.5
    done
    # If still not up, print the gateway log for debugging
    if ! curl -s -o /dev/null http://127.0.0.1:8080/healthz; then
        echo "ERROR: Gateway failed to start. Log:" >&2
        cat /tmp/gateway.log >&2
        mkdir -p /logs/verifier
        echo 0 > /logs/verifier/reward.txt
        exit 0
    fi
fi