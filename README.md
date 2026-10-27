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
├── replay_run.py              radar replay of one case (live-viewer frames, one per KMLB volume)
├── replay_publish.py          adds a replay to the site, keeps the newest 20
├── replay_engine/             the LIVE KMLB page's mrms_classify.py (v23) + kmlb_classify.py,
│                              and viewer.html (the live page with a replay mode)
├── .github/workflows/cases.yml
└── tests: test_cases.py, test_replay.py, kmlb_synth.py
```

## First run
1. Create the repo `cloudscope_cases` (public), commit everything.
2. Actions -> "CloudScope case replays" -> Run with start `2021-08`, end `2021-08` (includes CRS-23):
   check the log's per-window lines ("N frames, M skipped, S s") for the real speed.
3. Settings -> Pages -> deploy from `gh-pages`; open the page, load the workbook, check CRS-23.
4. Then start `2020-10`, end `2025-12`, rerun unchecked.

## Radar replays
Each case has a "Request radar replay" button. It opens a pre-filled GitHub issue ("Replay <case
id>"); submitting it runs .github/workflows/replay.yml (only for issues the repo owner opens), which
rebuilds the case in the live KMLB viewer - maps, cross-sections, lightning, field-mill markers,
pad readouts - one frame per KMLB volume across the LCC evaluation window, from the archives. The
link is posted on the issue (about 15 minutes), and the case page then shows "Open radar replay".
The newest 20 replays are kept (~25 MB each). Also runnable from the Actions tab with a case id.

The replay uses the LIVE classifier (replay_engine/mrms_classify.py, v23); the case lanes use the
climatologies' pinned v19. The cloud and anvil rules are the same in both; on the replay maps field
mills are part of overall status, as on the live page. Isotherms come from the freezing level and
a lapse rate (no historical BUFKIT); MERLIN has no archive before mid-2026.

## Notes
- Field mills: the rule is applied in the page from each pad's 15-minute peak |E|, so its threshold
  can be varied (standard: 1,000 V/m). The 1-minute archive peaks slightly below the logged values
  in some episodes (41 of 44 logged episodes reach 900 V/m within 5 nmi; 27 reach 1,000).
- The algorithm scores the pad point; the LWO judges the flight path. Some disagreements will be
  downrange clouds.
- LC-16 (Terran 1) is scored at SLC-20 (0.7 nmi away); test countdowns at LC-39A.
- The field-mill archive has gaps (e.g. 1 Jul - 4 Aug 2022): 19 windows have no mill data at all.
  Frames without a reading are shown grey and left out of the field-mill scores.
