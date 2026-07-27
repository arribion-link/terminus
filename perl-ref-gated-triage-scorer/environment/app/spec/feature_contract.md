# Feature Contract v3.1 — Triage Scorer

Patient session data arrives as nested JSON. The Perl worker must compute exactly the following 12 features in the declared order before applying model coefficients.

## Resource

- `/app/ref/contract_reference.py` — a Polars-based reference implementation that demonstrates the flattening logic on a toy example. It is NOT tested on all edge cases; the written rules below are definitive.

## Input schema

```json
{
  "patient_id": "<str>",
  "session_start": "2024-03-01T08:00:00Z",
  "visits": [
    {
      "visit_id": "<str>",
      "ts": "<ISO8601 UTC>",
      "heart_rate": <number|null|absent>,
      "spo2": <number|null|absent>,
      "bp_sys": <number|null|absent>,
      "bp_dia": <number|null|absent>,
      "site": "<str>"
    }
  ],
  "devices": [
    {
      "device_id": "<str>",
      "name": "<str>",
      "first_seen": "<ISO8601 UTC>",
      "last_seen": "<ISO8601 UTC|null|absent>"
    }
  ],
  "events": [
    {
      "event_id": "<str>",
      "ts": "<ISO8601 UTC>",
      "type": "<str>",
      "severity": <int|float|null|absent>
    }
  ]
}
```

All timestamps are ISO 8601 with trailing `Z` (UTC).

## Preprocessing

Parse timestamps to UTC epoch seconds. Any record whose `ts` (or `first_seen` for devices) is strictly greater than `session_start` is **excluded** from all further derivations ("future-dated"). Excluded records do not contribute to any feature.

## Canonical feature order (must be preserved across worker and scoring)

```
1. n_visits
2. hr_mean
3. hr_max
4. spo2_min
5. bp_sys_mean
6. visit_recency_weight
7. night_visit_ratio
8. n_events_weighted
9. n_fall_events
10. n_distinct_devices
11. device_span_hours
12. hr_slope_per_hour
```

## Feature derivations

### 1. n_visits
Number of included visits.

### 2. hr_mean
Arithmetic mean of `heart_rate` across included visits that have a numeric `heart_rate` field. If no visit supplies a `heart_rate`, the sentinel value `70.0` is used.

### 3. hr_max
Maximum `heart_rate` among the same subset as hr_mean. Sentinel: `70.0`.

### 4. spo2_min
Minimum `spo2` among included visits that have a numeric `spo2` field. Sentinel: `97.0`.

### 5. bp_sys_mean
Arithmetic mean of `bp_sys` among included visits that have a numeric field. Sentinel: `120.0`.

### 6. visit_recency_weight
Sum over included visits of `exp(-age_hours / 48.0)`, where `age_hours = (session_start_epoch − visit_ts_epoch) / 3600.0`.

### 7. night_visit_ratio
Fraction of included visits whose UTC hour-of-day is in the set `{22, 23, 0, 1, 2, 3, 4, 5}` (night window). If there are zero included visits, return `0.0`.

### 8. n_events_weighted
Sum over included events of `severity × exp(-age_hours / 24.0)`. If `severity` is absent, null, or non-numeric, use `1`. `age_hours` is computed versus `session_start` as for visits.

### 9. n_fall_events
Count of included events whose `type` equals `"fall_detected"`.

### 10. n_distinct_devices
Count of **distinct normalized device names** across included devices.

Normalization rule:
- Convert to lowercase.
- Replace every run of one or more non-alphanumeric characters with a single space.
- Strip leading and trailing whitespace.

If the normalized name is the empty string after stripping, the device is not counted.
Two devices with the same normalized name count as one.

### 11. device_span_hours
For each included device: `effective_last_seen = min(last_seen_epoch, session_start_epoch)` if `last_seen` is present and parseable; otherwise `effective_last_seen = session_start_epoch`. Span = `max(0, effective_last_seen − first_seen_epoch) / 3600.0`.

`device_span_hours = max(span across all included devices)`. If there are zero included devices, return `0.0`.

### 12. hr_slope_per_hour
Ordinary least-squares (OLS) slope of `heart_rate` against hours since the first heart-rate reading.

- Collect point pairs `(t_i, heart_rate_i)` from included visits that have a numeric `heart_rate`, in payload order.
- The clocks are `t_i = (visit_ts_epoch − t₀) / 3600.0`, where `t₀` is the epoch of the **first** such visit.
- If fewer than 2 points or all `t_i` are equal (zero variance), return `0.0`.

Slope formula (standard OLS):

```
n     = number of points
Sx    = Σ t_i
Sy    = Σ heart_rate_i
Sxx   = Σ t_i²
Sxy   = Σ t_i × heart_rate_i

denominator = n × Sxx − Sx²
slope       = (n × Sxy − Sx × Sy) / denominator
```

If `denominator` is zero, return `0.0`.
