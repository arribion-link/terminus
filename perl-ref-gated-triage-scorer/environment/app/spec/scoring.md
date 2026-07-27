# Scoring and Response Specification v1

## Model file format

At the resolved git commit, the file `model.json` at the repository root contains:

```json
{
  "model_version": "1.0.0",
  "intercept": -1.2,
  "coefficients": {
    "n_visits": 0.15,
    "hr_mean": -0.03,
    ...
  },
  "trained_at": "2024-01-01T00:00:00Z"
}
```

The `coefficients` map has exactly one entry per feature name in the canonical feature order (see feature contract).

## Feature order and hash

The canonical feature list (in order):

```
n_visits,hr_mean,hr_max,spo2_min,bp_sys_mean,visit_recency_weight,night_visit_ratio,n_events_weighted,n_fall_events,n_distinct_devices,device_span_hours,hr_slope_per_hour
```

`feature_order_hash` = first 12 hex characters of `SHA-256(joined_string)` where `joined_string` is the comma-joined list above.

## Scoring formula

Let `x₁…x₁₂` be the feature vector in canonical order.
Let `c₁…c₁₂` be the coefficients loaded from the model file.
Let `b` be the intercept.

```
z_raw = b + Σ (cᵢ × xᵢ)     (left-to-right summation, IEEE 754 double)
z     = clamp(z_raw, −40.0, 40.0)
p     = 1 / (1 + exp(−z))
score = round_half_even(p, 6)
```

`round_half_even(v, d)` rounds to `d` decimal places, breaking ties to the even digit. Both Python's built-in `round()` and glibc's `sprintf("%.6f", ...)` implement this for double values.

## Response JSON fields

The worker must include these fields in its success response:

| field               | type   | description |
|--------------------|--------|-------------|
| `ok`               | bool   | always `true` |
| `score`            | number | probability, 0–1 |
| `model_commit`     | string | 40-hex lowercase SHA of the commit used |
| `ref_kind`         | string | `"commit"` or `"tag"` |
| `model_version`    | string | from the model file |
| `feature_order_hash` | string | 12-hex hash as defined above |
| `features`         | object | key → feature value for each of the 12 features |

Feature values are IEEE 754 doubles serialized as JSON numbers.
