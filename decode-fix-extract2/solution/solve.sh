#!/usr/bin/env bash
set -euo pipefail

cat > /app/traverse_chain.py << 'PYEOF'
import hashlib, os, subprocess, sys

data_dir = "/app/data"

with open(os.path.join(data_dir, "manifest.txt")) as f:
    line = f.readline().strip()
current_hash = line.split("START: ")[1]

while True:
    path = os.path.join(data_dir, current_hash)
    if not os.path.exists(path):
        print(f"ERROR: file not found: {current_hash}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        content = f.read()
    if "EXEC:" in content:
        cmd = content.split("EXEC: ")[1].strip().split("\n")[0]
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        output = result.stdout.strip()
        with open("/app/result.txt", "w") as out:
            out.write(output + "\n")
        print(output)
        break
    elif "NEXT:" in content:
        current_hash = content.split("NEXT: ")[1].strip().split("\n")[0]
    else:
        print("ERROR: malformed chain file", file=sys.stderr)
        sys.exit(1)
PYEOF

python3 /app/traverse_chain.py
