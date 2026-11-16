"""Stratiform-deck fixes (deck_fix.py, kv01 13 Nov 2026) on hand-built storms, old vs new classifier.
    python test_deck.py <old mrms_classify.py> <new mrms_classify.py>"""
import sys, os, importlib.util
import numpy as np

def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m

OLD, NEW = load("old", sys.argv[1]), load("new", sys.argv[2])
FAILS = []
def check(c, m):
    print(("  ok    " if c else "  FAIL  ") + m)
    if not c: FAILS.append(m)

H = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0,
     7.5, 8.0, 8.5, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
LA = np.round(29.595 - 0.01 * np.arange(200), 3); LO = np.round(-81.595 + 0.01 * np.arange(200), 3)
P = NEW.SITES["LC-39A"]; jp, ip = int(np.argmin(np.abs(LA - P[0]))), int(np.argmin(np.abs(LO - P[1])))
LOg, LAg = np.meshgrid(LO, LA)
E = (LOg - P[1]) * 60 * np.cos(np.radians(P[0])); N = (LAg - P[0]) * 60          # nmi east / north of the pad
Z0 = 4000.0
ISO_Z = {0: 4000.0, -5: 4770.0, -10: 5540.0, -15: 6310.0, -20: 7080.0}            # freezing level + 6.5 C/km

LITE = os.environ.get("DECK_LITE") == "1"     # single-level path: 3 km level + 2 km root level, as the case engine


def make_sep(mod, vol, z0):
    if LITE:
        lvl, root = vol[H.index(3.0)], vol[H.index(2.0)]
        comp = vol.max(axis=0)
        if mod is NEW:
            return mod.separation_lite(lvl, 3.0, LA, LO, comp, root)
        return mod.separation_lite(lvl, 3.0, LA, LO)
    enc = mod.encode_volume(vol)
    vb, vt = mod.column_base_top(enc)
    return mod.separation(vol, H, vb, z0, None, LA, LO, vt)


class Scene:
    def __init__(self):
        self.vol = np.full((len(H), 200, 200), -99.0, np.float32)
        self.vii = np.zeros((200, 200), np.float32)
    def add(self, m, base, top, dbz):
        for k, h in enumerate(H):
            if base <= h <= top:
                self.vol[k][m] = np.maximum(self.vol[k][m], dbz)
        return self
    def fields(self, mod):
        F = {k: np.full((200, 200), fill, np.float32) for k, (_, fill, _) in mod.PRODUCTS.items()}
        F["cg"][:] = -1.0
        comp = self.vol.max(axis=0)
        F["comp"][:] = np.where(comp >= 0, comp, F["comp"])
        for key, tc in (("r0", 0), ("r5", -5), ("r10", -10), ("r15", -15), ("r20", -20)):
            k = int(np.argmin(np.abs(np.array(H) - ISO_Z[tc] / 1000.0)))
            F[key][:] = np.where(self.vol[k] >= 0, self.vol[k], F[key])
        echo = self.vol >= 0
        top = np.where(echo.any(0), np.array(H)[len(H) - 1 - np.argmax(echo[::-1], 0)] * 1000.0, -1.0)
        F["hmax"][:] = np.where(top > 0, top, F["hmax"])
        hi = [k for k, h in enumerate(H) if h >= 7.0]
        sup = self.vol[hi].max(axis=0)
        F["super"][:] = np.where(sup >= 0, sup, F["super"])
        F["vii"][:] = self.vii
        return F
    def run(self, mod, history="empty"):
        z0 = np.full((200, 200), Z0, np.float32)
        sep = make_sep(mod, self.vol, z0)
        hist = np.zeros((200, 200), bool) if history == "empty" else history
        st, red, yel, cls, top, diag = mod.evaluate(self.fields(mod), z0, LA, LO, hist, None, sep, None, None)
        return {k: bool(v[jp, ip]) for k, v in red.items()}, cls, diag
    def both(self, history="empty"):
        return self.run(OLD, history), self.run(NEW, history)

def disc(e, n, r): return (E - e) ** 2 + (N - n) ** 2 <= r * r
CU = ("cumulus_through", "cumulus_5nm", "cumulus_10nm")
deck = (np.abs(E) <= 45) & (np.abs(N) <= 45)                       # a 90 x 90 nmi elevated deck

print("1. post-frontal deck, base 4 km, top 9 km, 15 dBZ, with fall streaks to 2.5 km beside the pad")
S = Scene().add(deck, 4.0, 9.0, 15.0)
for e, n in ((3, 2), (-4, 5), (6, -3), (1, -7)):
    S.add(disc(e, n, 1.2), 2.5, 4.0, 18.0)
(ro, co, _), (rn, cn, _) = S.both()
streak = disc(3, 2, 1.0)
check(any(ro[k] for k in CU), f"old: cumulus rules at the pad ({[k for k in CU if ro[k]]}) - the kv01 false alarm")
check(not any(rn[k] for k in CU), "new: no cumulus rule at the pad")
check(np.isin(cn[streak], (8,)).mean() > 0.9, f"new: the fall streak is layered cloud (class 8: {np.isin(cn[streak], (8,)).mean():.0%})")

print("2. isolated Florida cumulus, rooted at 0.5 km, top 8 km, 30 dBZ, 7 nmi east, clear sky around")
S = Scene().add(disc(7, 0, 1.0), 0.5, 8.0, 30.0)
(ro, _, _), (rn, cn, _) = S.both()
check(ro["cumulus_10nm"] and rn["cumulus_10nm"], "both: cumulus colder than -20 C within 10 nmi")
check(cn[disc(7, 0, 0.6)].min() == 4, "new: the tower is cumulus topping below -20 C (class 4)")

print("3. the same tower rooted under the deck (embedded but reaching the ground)")
S = Scene().add(deck, 4.0, 9.0, 15.0).add(disc(7, 0, 1.0), 0.5, 8.0, 30.0)
(ro, _, _), (rn, cn, _) = S.both()
check(rn["cumulus_10nm"] == ro["cumulus_10nm"] == True, "both: still cumulus within 10 nmi - rooted keeps isolated status")

print("4. raised part of the deck with VII > 0: 25 dBZ, base 3 km, top 11 km (kv01 10:14)")
S = Scene().add(deck, 4.0, 9.0, 15.0).add(disc(-8, 6, 1.5), 3.0, 11.0, 25.0)
S.vii[disc(-8, 6, 1.0)] = 0.5
(ro, co, do), (rn, cn, dn) = S.both()
check(do["attached"][deck].mean() > 0.5, f"old: the deck becomes attached anvil ({do['attached'][deck].mean():.0%} of it)")
check(dn["attached"][deck].mean() < 0.01 and not rn["attached_anvil"], "new: no attached anvil, no attached-anvil rule at the pad")

print("5. a real thunderstorm: 50 dBZ core rooted at 0.5 km, VII > 0, with a connected anvil")
S = Scene().add(disc(-25, 0, 3.0), 0.5, 12.0, 50.0).add((E > -25) & (E < 2.5) & (np.abs(N) <= 4), 8.0, 12.0, 12.0)
S.vii[disc(-25, 0, 2.0)] = 5.0
(ro, _, do), (rn, _, dn) = S.both()
anv = (E > -20) & (E < 2) & (np.abs(N) <= 3)
check(ro["attached_anvil"] and rn["attached_anvil"] and dn["attached"][anv].mean() > 0.9,
      "both: attached anvil within 3 nmi of the pad")

print("6. first frame (no history), deck with no convection anywhere")
S = Scene().add(deck, 4.0, 9.0, 15.0)
(ro, co, do), (rn, cn, dn) = S.both(history=None)
check(do["detached"][deck].mean() > 0.9 and ro["detached_anvil"], "old: the whole deck is detached anvil, violating at the pad")
check(dn["detached"][deck].mean() < 0.01 and not rn["detached_anvil"], "new: elevated layer, no detached-anvil rule")

print("7. first frame, floating ice beside the pad and a real core 30 nmi away")
S = Scene().add(disc(0, 0, 4.0), 8.0, 11.0, 10.0).add(disc(-30, -25, 2.0), 0.5, 12.0, 50.0)
(ro, _, _), (rn, _, _) = S.both(history=None)
check(ro["detached_anvil"] and rn["detached_anvil"], "both: detached anvil (no history, but convection in the frame)")

print("8. echo based at 4.5 km with no isotherm-product echo (kv01 12:48)")
m8 = disc(4, 0, 2.0)
S = Scene().add(m8, 4.5, 7.0, 8.0)
F_new = S.fields(NEW)
for k in ("r0", "r5", "r10", "r15", "r20"):
    F_new[k][:] = NEW.PRODUCTS[k][1]                           # the isotherm products missed it
F_new["hmax"][m8] = 5000.0                                     # MRMS hmax: height of the strongest echo, not the top
F_new["super"][:] = NEW.PRODUCTS["super"][1]                   # tops ~7 km, under the Super layer
z0 = np.full((200, 200), Z0, np.float32)
sep = make_sep(NEW, S.vol, z0)
_, _, _, cls_n, _, d_n = NEW.evaluate(F_new, z0, LA, LO, np.zeros((200, 200), bool), None, sep, None, None)
sep_o = make_sep(OLD, S.vol, z0)
_, _, _, cls_o, _, d_o = OLD.evaluate(F_new, z0, LA, LO, np.zeros((200, 200), bool), None, sep_o, None, None)
m = disc(4, 0, 1.5)
check(not np.isin(cls_o[m], (8,)).any() and np.isin(cls_n[m], (8,)).mean() > 0.9,
      f"old: not recognised as elevated (classes {sorted(set(cls_o[m].tolist()))}); new: elevated layer (class 8)")

print(f"\n{'single-level path' if LITE else '3-D volume path'}: {len(FAILS)} failure(s)"); sys.exit(1 if FAILS else 0)
