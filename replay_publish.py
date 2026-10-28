#!/usr/bin/env python3
"""Add a built replay to the site, keep the newest KEEP, and update data/replays.json.
    python replay_publish.py <case id> --inp out --site site"""
import argparse, datetime as dt, json, os, shutil

KEEP = 20                     # ~25 MB each; GitHub Pages sites should stay under ~1 GB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case"); ap.add_argument("--inp", default="out"); ap.add_argument("--site", default="site")
    ap.add_argument("--gr2-url", default="", help="the GR2 package's release URL (empty if its build failed)")
    ap.add_argument("--gr2-partial", default="false")
    a = ap.parse_args()
    src, dst = os.path.join(a.inp, "replay", a.case), os.path.join(a.site, "replay", a.case)
    m = json.load(open(os.path.join(src, "manifest.json")))
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    path = os.path.join(a.site, "data", "replays.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    reg = json.load(open(path)) if os.path.exists(path) else {}
    reg[a.case] = {"frames": len(m["frames"]), "volumes": m["replay"]["volumes"],
                   "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    if a.gr2_url:
        reg[a.case]["gr2"] = a.gr2_url
        reg[a.case]["gr2_partial"] = a.gr2_partial == "true"
    for old in sorted(reg, key=lambda k: reg[k]["built"], reverse=True)[KEEP:]:
        shutil.rmtree(os.path.join(a.site, "replay", old), ignore_errors=True)
        del reg[old]
    json.dump(reg, open(path, "w"), indent=1)
    print(f"published replay {a.case} ({reg[a.case]['frames']} frames); {len(reg)} replay(s) kept")


if __name__ == "__main__":
    main()
