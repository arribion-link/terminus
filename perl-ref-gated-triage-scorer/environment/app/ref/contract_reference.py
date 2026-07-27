"""
Polars-based reference that demonstrates the feature contract on a tiny example.
Reads /app/fixtures/sample_session.json and prints computed feature values.
This is a learning aid — it does not handle all edge cases.
The definitive rules are in /app/spec/feature_contract.md.
"""
import json
import polars as pl
from datetime import datetime, timezone

SESSION_START = "2024-03-01T08:00:00Z"

with open("/app/fixtures/sample_session.json") as f:
    payload = json.load(f)

session_ts = int(datetime.fromisoformat(SESSION_START.replace("Z", "+00:00")).timestamp())

visits = payload.get("visits", [])
events = payload.get("events", [])
devices = payload.get("devices", [])

v_df = pl.DataFrame(visits) if visits else pl.DataFrame()
e_df = pl.DataFrame(events) if events else pl.DataFrame()
d_df = pl.DataFrame(devices) if devices else pl.DataFrame()

if len(v_df) > 0:
    v_df = v_df.with_columns(pl.col("ts").str.replace("Z", "+00:00").str.strptime(pl.Datetime).cast(pl.Int64).truediv(1000000).alias("_ts"))
    v_df = v_df.filter(pl.col("_ts") <= session_ts)

if len(e_df) > 0:
    e_df = e_df.with_columns(pl.col("ts").str.replace("Z", "+00:00").str.strptime(pl.Datetime).cast(pl.Int64).truediv(1000000).alias("_ts"))
    e_df = e_df.filter(pl.col("_ts") <= session_ts)

if len(d_df) > 0:
    d_df = d_df.with_columns(pl.col("first_seen").str.replace("Z", "+00:00").str.strptime(pl.Datetime).cast(pl.Int64).truediv(1000000).alias("_ft"))
    d_df = d_df.filter(pl.col("_ft") <= session_ts)

n_visits = len(v_df)
print(f"n_visits: {n_visits}")

if "heart_rate" in v_df.columns and len(v_df.filter(pl.col("heart_rate").is_not_null())) > 0:
    hr_vals = v_df.filter(pl.col("heart_rate").is_not_null()).get_column("heart_rate")
    print(f"hr_mean: {hr_vals.mean()}")
    print(f"hr_max: {hr_vals.max()}")
else:
    print("hr_mean: 70.0 (sentinel)")
    print("hr_max: 70.0 (sentinel)")

if "spo2" in v_df.columns and len(v_df.filter(pl.col("spo2").is_not_null())) > 0:
    print(f"spo2_min: {v_df.filter(pl.col('spo2').is_not_null()).get_column('spo2').min()}")
else:
    print("spo2_min: 97.0 (sentinel)")

if "bp_sys" in v_df.columns and len(v_df.filter(pl.col("bp_sys").is_not_null())) > 0:
    print(f"bp_sys_mean: {v_df.filter(pl.col('bp_sys').is_not_null()).get_column('bp_sys').mean()}")
else:
    print("bp_sys_mean: 120.0 (sentinel)")

print("(for full 12-feature computation, see /app/spec/feature_contract.md)")
