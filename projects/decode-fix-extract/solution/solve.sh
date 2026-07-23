#!/usr/bin/env bash
set -euo pipefail

cat > /app/decode_archive.py << 'PYEOF'
import struct
import sys

def hash_xoradd(data: bytes, key: int) -> int:
    h = key
    for b in data:
        h = ((h << 5) | (h >> 27)) & 0xFFFFFFFF
        h ^= b
        h = (h + 0x3B9ACA07) & 0xFFFFFFFF
    return h

with open('/app/data/metrics.arch', 'rb') as f:
    data = f.read()

magic = data[0:4]
if magic != b'ARCh':
    print("ERROR: invalid header")
    sys.exit(1)

version = data[4]
if version != 0x02:
    print("ERROR: invalid header")
    sys.exit(1)

reserved = data[14:16]
if reserved != b'\xC0\xDE':
    print("ERROR: invalid header")
    sys.exit(1)

ts_bytes = bytes([data[7], data[6], data[9], data[8]])
epoch_ts = struct.unpack('<I', ts_bytes)[0]
header_csum_data = hash_xoradd(data[0:8], 0xBEEF)
stored_csum = struct.unpack('<I', data[10:14])[0]
if header_csum_data != stored_csum:
    print("ERROR: invalid header")
    sys.exit(1)

count = data[5]

selected = []
corrupted = 0
pos = 16

for i in range(count):
    entry = data[pos:pos + 32]
    entry_data = entry[0:20]
    computed_csum = hash_xoradd(entry_data, 0xCAFE)
    stored_entry_csum = struct.unpack('<I', entry[20:24])[0]
    if computed_csum != stored_entry_csum:
        corrupted += 1
        pos += 32
        continue
    flags = struct.unpack('>H', entry[16:18])[0]
    severity = flags & 0x07
    alarm = (flags >> 3) & 0x01
    etype = (flags >> 4) & 0x01
    unit = (flags >> 5) & 0x01
    status = (flags >> 6) & 0x03
    if etype == 0 and severity == 0 and status == 0:
        reading = struct.unpack('>f', entry[12:16])[0]
        if unit == 1:
            reading = (reading - 32) * 5 / 9
        selected.append(reading)
    pos += 32

mean_val = round(sum(selected) / len(selected), 2) if selected else 0.0
print(f"MEAN: {mean_val}")
print(f"CORRUPTED: {corrupted}")
PYEOF

python3 /app/decode_archive.py
