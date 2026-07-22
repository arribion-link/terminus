#!/usr/bin/env python3
"""Reference feature-contract generator.

This is the canonical source of truth for the triage feature contract
(see CONTRACT.md in this directory). It builds the contract as a Polars
DataFrame -- the same representation used by the offline model-training
pipeline -- and serializes it to /app/contract/feature_contract.json so
that other language runtimes (the Perl inference worker) can consume a
plain-JSON view of the same schema.

This script runs once at image build time. It is deterministic and does
not read any external state.
"""
import json
import sys

import polars as pl

CONTRACT_VERSION = "triage-contract-v1"

# name, dtype, default value used when the aggregation has no data to
# operate over. Order here IS the contract order.
_ROWS = [
    ("patient_age", "float", 0.0),
    ("patient_sex_f", "float", 0.0),
    ("visit_count", "float", 0.0),
    ("visit_ed_count", "float", 0.0),
    ("visit_acuity_max", "float", 0.0),
    ("visit_duration_total", "float", 0.0),
    ("device_spo2_min", "float", 100.0),
    ("event_count", "float", 0.0),
    ("event_severity_max", "float", 0.0),
    ("event_triage_escalation_present", "float", 0.0),
]


def build_contract_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "name": [r[0] for r in _ROWS],
            "type": [r[1] for r in _ROWS],
            "default": [r[2] for r in _ROWS],
        }
    )


def main() -> int:
    frame = build_contract_frame()

    features = [
        {"name": row["name"], "type": row["type"], "default": row["default"]}
        for row in frame.iter_rows(named=True)
    ]

    contract = {
        "contract_version": CONTRACT_VERSION,
        "features": features,
    }

    out_path = "/app/contract/feature_contract.json"
    with open(out_path, "w") as fh:
        json.dump(contract, fh, indent=2, sort_keys=False)
        fh.write("\n")

    sys.stderr.write(f"wrote {len(features)} features to {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
