#!/usr/bin/env python3
"""Validate a custom-case request and add it to custom_cases.csv. Prints GitHub step outputs.
    BODY="pad: SLC-40\nstart: 2026-03-14 18:00\nend: 2026-03-14 20:00\nname: My case" python custom_request.py
or  python custom_request.py --pad SLC-40 --start "2026-03-14 18:00" --end "2026-03-14 20:00" --name "My case" """
import argparse, datetime as dt, os, re, sys
import pandas as pd

PADS = ["LC-39A", "LC-39B", "SLC-40", "SLC-41", "SLC-37B", "SLC-46", "LC-36", "SLC-36", "SLC-20", "LZ-1"]
FIRST = dt.datetime(2020, 10, 14)            # MRMS archive used by the engine
MAX_H = 8.0
CSV = "custom_cases.csv"


def parse_body(body):
    f = {}
    for line in body.replace("\r", "").split("\n"):
        m = re.match(r"\s*(pad|start|end|name)\s*:\s*(.+?)\s*$", line, re.I)
        if m:
            f[m.group(1).lower()] = m.group(2)
    return f


def main():
    ap = argparse.ArgumentParser()
    for k in ("pad", "start", "end", "name"):
        ap.add_argument("--" + k, default=None)
    a = ap.parse_args()
    f = parse_body(os.environ.get("BODY", "")) if os.environ.get("BODY") else {}
    f.update({k: v for k, v in vars(a).items() if v})
    try:
        pad = f["pad"].upper().replace(" ", "")
        start = pd.Timestamp(f["start"].upper().rstrip("Z").replace("T", " ")).to_pydatetime().replace(second=0, microsecond=0)
        end = pd.Timestamp(f["end"].upper().rstrip("Z").replace("T", " ")).to_pydatetime().replace(second=0, microsecond=0)
    except Exception as e:
        sys.exit(f"could not read pad / start / end ({type(e).__name__}: {e}) - expected lines like 'pad: SLC-40', 'start: 2026-03-14 18:00'")
    name = re.sub(r"[^\w .,()/+-]", "", f.get("name", "") or f"Custom {pad} {start:%Y-%m-%d}")[:60] or f"Custom {pad}"
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    errors = []
    if pad not in PADS: errors.append(f"pad {pad!r} is not one of {PADS}")
    if end <= start: errors.append("end must be after start")
    if (end - start).total_seconds() > MAX_H * 3600: errors.append(f"window longer than {MAX_H:g} hours")
    if start < FIRST: errors.append(f"start before {FIRST:%Y-%m-%d} (the archive the engine uses)")
    if end > now - dt.timedelta(hours=1): errors.append("the window must have ended at least an hour ago")
    if errors:
        sys.exit("invalid request: " + "; ".join(errors))
    cid = f"{start:%Y%m%d_%H%M}_{pad.replace('-', '')}C"
    X = pd.read_csv(CSV) if os.path.exists(CSV) else pd.DataFrame(columns=["start", "end", "vehicle", "payload", "pad", "launched_this_count", "match", "requested"])
    row = {"start": f"{start:%Y-%m-%d %H:%M}", "end": f"{end:%Y-%m-%d %H:%M}", "vehicle": "Custom", "payload": name, "pad": pad,
           "launched_this_count": False, "match": "custom", "requested": f"{now:%Y-%m-%d}"}
    keep = X[~((X["start"].astype(str).str[:16] == row["start"]) & (X["pad"] == pad))]
    pd.concat([keep, pd.DataFrame([row])], ignore_index=True).to_csv(CSV, index=False)
    out = os.environ.get("GITHUB_OUTPUT")
    lines = f"id={cid}\nmonth={start:%Y-%m}\nname={name}\n"
    if out:
        open(out, "a").write(lines)
    print(lines.strip())


if __name__ == "__main__":
    main()
