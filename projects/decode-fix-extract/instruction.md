decode a custom binary metrics archive and extract specific values.

there is a file at /app/data/metrics.arch that contains binary sensor data. the format is:

header (16 bytes):
- magic: 4 bytes ascii "ARCh"
- version: 1 byte, must be 0x02
- count: 1 byte, number of entries
- epoch_ts: 4 bytes, stored middle-endian (byte order: 1,0,3,2), seconds since 2010-01-01 00:00:00 utc
- checksum: 4 bytes, xor rolling hash of the header bytes 0-7 with key 0xBEEF
- reserved: 2 bytes, must be 0xC0DE

entry (32 bytes each, sequentially after header):
- name: 8 bytes, ascii left-aligned null-padded
- sensor_id: 4 bytes, little-endian unsigned int
- reading: 4 bytes, ieee 754 float stored in big-endian byte order
- flags: 2 bytes, bit field stored as big-endian
  - bits 0-2: severity (0=info, 1=warn, 2=critical)
  - bit 3: alarm (1=active)
  - bit 4: type (0=temperature, 1=pressure)
  - bit 5: unit (0=celsius, 1=fahrenheit for temperature; 0=kpa, 1=psi for pressure)
  - bits 6-7: status (0=ok, 1=degraded, 2=fault, 3=unknown)
  - bits 8-15: unused
- reserved_b: 2 bytes, must be 0xFE 0xED
- entry_checksum: 4 bytes, little-endian, computed as xor-add rolling hash over the data bytes of this entry (name, sensor_id, reading, flags, reserved_b) with key 0xCAFE
- padding: 8 bytes, zero-filled

xor-add rolling hash algorithm:
def hash_xoradd(data: bytes, key: int) -> int:
    h = key
    for b in data:
        h = ((h << 5) | (h >> 27)) & 0xFFFFFFFF
        h ^= b
        h = (h + 0x3B9ACA07) & 0xFFFFFFFF
    return h

the archive may contain entries with invalid checksums. those entries are corrupted and must be skipped.

your task:
1. write a python script /app/decode_archive.py that reads metrics.arch
2. validate the header magic, version, reserved field, and header checksum. if any header validation fails, print "ERROR: invalid header" and exit with code 1
3. decode all 32-byte entries sequentially using the offset from the header end
4. skip entries where entry_checksum does not match the computed hash
5. from valid entries, select only those with type=temperature (flags bit 4 = 0) AND severity=info (flags bits 0-2 = 0) AND status=ok (flags bits 6-7 = 0)
6. for selected entries, convert fahrenheit readings to celsius: C = (F - 32) * 5/9, round to 2 decimal places. keep celsius readings as-is
7. compute the mean of the converted readings, round to 2 decimal places
8. print the result as: "MEAN: <value>"
9. print a count of how many entries were corrupted (skipped): "CORRUPTED: <count>"

your script must use the python struct module and must not use any third-party libraries beyond the python standard library.

output example:
MEAN: 23.45
CORRUPTED: 2
