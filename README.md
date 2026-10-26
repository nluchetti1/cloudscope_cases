# CloudScope case replays

Every logged countdown window since Oct 2020 (`countdown_pads.csv`, 492 windows), replayed every 2
minutes - from an hour before each window to its end - through the same pinned classifier as the
climatologies, twice per frame: MRMS alone and the KMLB hybrid (single-source columns). Lightning
is NLDN + GLM (from `cape_glm`), field mills come from `fieldmill/fieldmill_minutes.npz`.

The page lists every countdown, draws each rule through the window for MRMS and the hybrid, and
- once you load the LWO workbook WITH THE FILE PICKER - overlays the LWO's logged violations and
computes agreement statistics in your browser. The workbook is never uploaded anywhere; only
window times, vehicle, payload and pad are in this repo.

## Layout
```
cloudscope_cases/
├── cases_run.py               replays one month of windows
├── cases_merge.py             publishes cases, index.json and summary.json
├── climo_run.py               archive helpers (MRMS, KMLB, GOES, GLM) - same as kmlb_cloudscope_climo
├── kmlb_classify.py           KMLB hybrid - same as the live KMLB page
├── mrms_classify.py           the pinned classifier - same as the climatologies
├── countdown_pads.csv         the 492 windows: times, vehicle, payload, pad (no LWO calls)
├── fieldmill/fieldmill_minutes.npz
├── requirements.txt, _checks.py
├── web/index.html             the case-study page
├── .github/workflows/cases.yml
└── tests: test_cases.py, kmlb_synth.py
```

## First run
1. Create the repo `cloudscope_cases` (public), commit everything.
2. Actions -> "CloudScope case replays" -> Run with start `2021-08`, end `2021-08` (includes CRS-23):
   check the log's per-window lines ("N frames, M skipped, S s") for the real speed.
3. Settings -> Pages -> deploy from `gh-pages`; open the page, load the workbook, check CRS-23.
4. Then start `2020-10`, end `2025-12`, rerun unchecked.

## Notes
- Field mills: the rule is applied in the page from each pad's 15-minute peak |E|, so its threshold
  can be varied (standard: 1,000 V/m). The 1-minute archive peaks slightly below the logged values
  in some episodes (41 of 44 logged episodes reach 900 V/m within 5 nmi; 27 reach 1,000).
- The algorithm scores the pad point; the LWO judges the flight path. Some disagreements will be
  downrange clouds.
- LC-16 (Terran 1) is scored at SLC-20 (0.7 nmi away); test countdowns at LC-39A.
