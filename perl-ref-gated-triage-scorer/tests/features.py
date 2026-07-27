"""Reference feature computation shared by the property test harness and oracle."""
import hashlib
import math
import re
from datetime import datetime, timezone

FEATURE_ORDER = [
    "n_visits",
    "hr_mean",
    "hr_max",
    "spo2_min",
    "bp_sys_mean",
    "visit_recency_weight",
    "night_visit_ratio",
    "n_events_weighted",
    "n_fall_events",
    "n_distinct_devices",
    "device_span_hours",
    "hr_slope_per_hour",
]


def iso_to_epoch(ts):
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def _normalized_device_name(name):
    name = name.lower()
    joined = "".join(ch if ch.isalnum() else " " for ch in name)
    return re.sub(r"\s+", " ", joined).strip()


def feature_hash(order=None):
    if order is None:
        order = FEATURE_ORDER
    return hashlib.sha256(",".join(order).encode()).hexdigest()[:12]


def compute_features(payload):
    session_ts = iso_to_epoch(payload["session_start"])

    visits = payload.get("visits", [])
    events = payload.get("events", [])
    devices = payload.get("devices", [])

    incl_visits = []
    for v in visits:
        ts = iso_to_epoch(v["ts"])
        if ts > session_ts:
            continue
        incl_visits.append({**v, "_ts": ts})

    incl_events = []
    for e in events:
        ts = iso_to_epoch(e["ts"])
        if ts > session_ts:
            continue
        incl_events.append({**e, "_ts": ts})

    incl_devices = []
    for d in devices:
        ts = iso_to_epoch(d["first_seen"])
        if ts > session_ts:
            continue
        incl_devices.append({**d, "_ft": ts})

    features = {}
    features["n_visits"] = len(incl_visits)

    hr_vals = [
        v["heart_rate"] for v in incl_visits
        if "heart_rate" in v and isinstance(v["heart_rate"], (int, float))
    ]
    features["hr_mean"] = sum(hr_vals) / len(hr_vals) if hr_vals else 70.0
    features["hr_max"] = max(hr_vals) if hr_vals else 70.0

    features["hr_slope_per_hour"] = 0.0
    if len(hr_vals) >= 2:
        pairs = [
            (v["_ts"], v["heart_rate"])
            for v in incl_visits
            if "heart_rate" in v and isinstance(v["heart_rate"], (int, float))
        ]
        t0 = pairs[0][0]
        xy = [(p[0] - t0, p[1]) for p in pairs]
        t_vals = [x / 3600.0 for x, y in xy]
        hr_v = [y for x, y in xy]
        if max(t_vals) != min(t_vals) and len(t_vals) >= 2:
            n = len(t_vals)
            st = sum(t_vals)
            sh = sum(hr_v)
            sth = sum(t * h for t, h in zip(t_vals, hr_v))
            st2 = sum(t * t for t in t_vals)
            denom = n * st2 - st * st
            if abs(denom) > 1e-12:
                features["hr_slope_per_hour"] = (n * sth - st * sh) / denom

    spo2_vals = [
        v["spo2"] for v in incl_visits
        if "spo2" in v and isinstance(v["spo2"], (int, float))
    ]
    features["spo2_min"] = min(spo2_vals) if spo2_vals else 97.0

    bp_vals = [
        v["bp_sys"] for v in incl_visits
        if "bp_sys" in v and isinstance(v["bp_sys"], (int, float))
    ]
    features["bp_sys_mean"] = sum(bp_vals) / len(bp_vals) if bp_vals else 120.0

    recency = 0.0
    for v in incl_visits:
        age_h = (session_ts - v["_ts"]) / 3600.0
        recency += math.exp(-age_h / 48.0)
    features["visit_recency_weight"] = recency

    night_count = 0
    for v in incl_visits:
        dt = datetime.fromtimestamp(v["_ts"], tz=timezone.utc)
        h = dt.hour
        if h == 22 or h == 23 or 0 <= h <= 5:
            night_count += 1
    features["night_visit_ratio"] = night_count / len(incl_visits) if incl_visits else 0.0

    ew = 0.0
    for e in incl_events:
        sev = e.get("severity")
        if not isinstance(sev, (int, float)):
            sev = 1
        age_h = (session_ts - e["_ts"]) / 3600.0
        ew += sev * math.exp(-age_h / 24.0)
    features["n_events_weighted"] = ew

    features["n_fall_events"] = sum(
        1 for e in incl_events if e.get("type") == "fall_detected"
    )

    norm_set = set()
    for d in incl_devices:
        n = _normalized_device_name(d.get("name", ""))
        if n:
            norm_set.add(n)
    features["n_distinct_devices"] = len(norm_set)

    max_span = 0.0
    for d in incl_devices:
        ft = d["_ft"]
        if d.get("last_seen") is not None:
            eff = min(iso_to_epoch(d["last_seen"]), session_ts)
        else:
            eff = session_ts
        span = max(0.0, (eff - ft) / 3600.0)
        max_span = max(max_span, span)
    features["device_span_hours"] = max_span if incl_devices else 0.0

    return features


def compute_score(features_dict, coeffs, intercept):
    z = intercept
    for fname in FEATURE_ORDER:
        z += coeffs.get(fname, 0) * features_dict.get(fname, 0)
    z = max(-40.0, min(40.0, z))
    p = 1.0 / (1.0 + math.exp(-z))
    return round(p, 6)
