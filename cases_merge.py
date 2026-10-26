#!/usr/bin/env python3
"""
Publish the case replays: copy new case files into the site, and build
    data/index.json     one entry per case (times, vehicle, payload, pad, frames, skipped)
    data/summary.json   per case, the countdown pad's series only - what the statistics view needs,
                        small enough to load in one go: frame minutes after the window start, and for
                        MRMS and the hybrid: status, red bits, yellow bits; plus field-mill peaks
    python cases_merge.py --inp out --site site
"""
import argparse
import datetime as dt
import glob
import json
import os
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="out")
    ap.add_argument("--site", default="site")
    a = ap.parse_args()
    cdir = os.path.join(a.site, "data", "cases")
    os.makedirs(cdir, exist_ok=True)
    new = sorted(glob.glob(os.path.join(a.inp, "*.json")))
    for f in new:
        shutil.copy(f, cdir)
    index, summary = [], {}
    for f in sorted(glob.glob(os.path.join(cdir, "*.json"))):
        c = json.load(open(f))
        start = dt.datetime.fromisoformat(c["start"])
        mins = [int((dt.datetime.fromisoformat(t) - start).total_seconds() // 60) for t in c["frames"]]
        index.append({k: c[k] for k in ("id", "start", "end", "vehicle", "payload", "pad", "pad_scored", "launched")}
                     | {"frames": len(c["frames"]), "skipped": len(c["skipped"]),
                        "kmlb_full": sum(1 for k in c["kmlb_info"] if k[3] == "full")})
        if c["pad_scored"] in c["pads"]:
            p = c["pads"].index(c["pad_scored"])
            summary[c["id"]] = {"m": mins,
                                "mrms": [[f["status"][p], f["red"][p], f["yel"][p]] for f in c["mrms"]],
                                "kmlb": [[f["status"][p], f["red"][p], f["yel"][p]] for f in c["kmlb"]],
                                "fm5": [x[p] for x in c["fm5"]], "fm7": [x[p] for x in c["fm7"]]}
    rk = json.load(open(glob.glob(os.path.join(cdir, "*.json"))[0]))["rule_keys"] if index else []
    meta = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "rule_keys": rk,
            "step_min": 2, "pre_min": 60, "cases": index}
    json.dump(meta, open(os.path.join(a.site, "data", "index.json"), "w"), separators=(",", ":"))
    json.dump(summary, open(os.path.join(a.site, "data", "summary.json"), "w"), separators=(",", ":"))
    print(f"{len(new)} new case file(s); {len(index)} cases published; summary for {len(summary)} "
          f"({os.path.getsize(os.path.join(a.site, 'data', 'summary.json')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
