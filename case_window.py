#!/usr/bin/env python3
"""Print a case's LCC evaluation window for the GR2 package, as GitHub step outputs:
    python case_window.py 20210828_0537_LC39A      -> start=2021-08-28T05:37  end=2021-08-28T07:37  payload=CRS-23
Same window table and case ids as cases_run.load_windows (pandas only, no radar libraries)."""
import sys
import pandas as pd


def window(case_id, path="countdown_pads.csv"):
    W = pd.read_csv(path, parse_dates=["start", "end"])
    W = W[W.match.isin(["good", "test"])].drop_duplicates(subset=["start", "end", "payload", "pad"])
    pad = W["pad"].where(W["pad"].notna(), "TEST").astype(str).str.replace("-", "")
    W["id"] = W.start.dt.strftime("%Y%m%d_%H%M") + "_" + pad
    r = W[W["id"] == case_id]
    if r.empty:
        raise SystemExit(f"no case {case_id!r}")
    r = r.iloc[0]
    return r.start.floor("min"), r.end.ceil("min"), str(r.payload)


if __name__ == "__main__":
    s, e, p = window(sys.argv[1])
    print(f"start={s:%Y-%m-%dT%H:%M}\nend={e:%Y-%m-%dT%H:%M}\npayload={p}")
