#!/usr/bin/env python3
"""Python reference model of the Multi-Session ORB Pro signal engine.

A line-by-line port of the SHARED CORE engine functions (f_latestStart, f_newWindow,
f_finalize, f_signals, f_openTrade, f_manageTrade, f_engine) so the *algorithm* can be
unit-tested off TradingView: session clock across daylight-saving changes, holidays,
missing bars, misaligned timeframes, range freezing, breakout / retest / false-breakout
rules and trade tracking.

It does NOT prove the Pine code compiles or behaves identically on TradingView — it
checks that the design is right. Keep it in sync when the Pine engine changes.
Pine's `timestamp(tz, y, m, d, h, mi, s)` is modelled with `zoneinfo`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAY_MS = 86_400_000


def nan():
    return float("nan")


def isna(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def pine_ne(a, b) -> bool:
    """Pine's `a != b`: any comparison involving na evaluates to false."""
    return False if isna(a) or isna(b) else a != b


# ───────────────────────── Pine time built-ins ─────────────────────────
def ts(tz: str, y: int, m: int, d: int, h: int, mi: int, s: int = 0) -> int:
    return int(datetime(y, m, d, h, mi, s, tzinfo=ZoneInfo(tz)).timestamp() * 1000)


def local(t: int, tz: str) -> datetime:
    return datetime.fromtimestamp(t / 1000, ZoneInfo(tz))


def dayofweek(t: int, tz: str) -> int:  # Pine: 1 = Sunday … 7 = Saturday
    return (local(t, tz).isoweekday() % 7) + 1


def date_str(t: int, tz: str) -> str:
    return local(t, tz).strftime("%Y-%m-%d")


# ───────────────────────── input parsing (mirrors f_maskText / f_parseHM) ─────────────────────────
def mask_from_text(t: str) -> str:
    low = t.lower()
    return "".join("1" if code in low else "0" for code in ("su", "mo", "tu", "we", "th", "fr", "sa"))


def parse_hm(t: str, part: int, default: int) -> int:
    p = t.replace(" ", "").split(":")
    try:
        v = float(p[part]) if len(p) == 2 else None
    except ValueError:
        v = None
    lim = 23 if part == 0 else 59
    return default if v is None or v < 0 or v > lim or v != math.floor(v) else int(v)


# ───────────────────────── configuration ─────────────────────────
@dataclass
class SessCfg:
    key: str
    tz: str
    sh: int
    sm: int
    dur: int = 15
    enabled: bool = True
    days: str = "0111110"  # Su Mo Tu We Th Fr Sa
    hol_on: bool = True
    hol: str = ""
    tf_ok: bool = True


@dataclass
class Params:
    tf_sec: int = 300
    mode: int = 1  # 1 breakout close, 2 breakout + retest, 3 breakout + momentum
    long_ok: bool = True
    short_ok: bool = True
    first_only: bool = False
    max_sig: int = 2
    sig_win_min: int = 180
    life_hrs: int = 12
    retest_bars: int = 12
    retest_candle: bool = True
    mom_body: int = 55
    mom_atr: float = 1.0
    fb_on: bool = True
    fb_bars: int = 6
    block_open: bool = True
    exit_inside: bool = False
    skip_partial: bool = False
    time_exit_min: int = 0
    unit_ticks: bool = True
    mintick: float = 0.25
    min_dist: float = 2
    tol: float = 8
    stop_mode: int = 1  # 1 opposite boundary, 2 midpoint, 3 ATR
    stop_buf: float = 2
    stop_atr: float = 1.5
    tp1_r: float = 1.0
    tp2_r: float = 2.0
    be: bool = True
    be_off: float = 1
    crypto_7d: bool = False
    is_crypto: bool = False


@dataclass
class Bar:
    time: int
    o: float
    h: float
    l: float
    c: float
    time_close: int = 0


@dataclass
class SessState:
    candStart: int | None = None
    candNext: int | None = None
    candOk: bool = False
    candDate: str = ""
    winStart: int | None = None
    winEnd: int | None = None
    win1hEnd: int | None = None
    winDate: str = ""
    phase: int = 0
    hi: float = field(default_factory=nan)
    lo: float = field(default_factory=nan)
    orh: float = field(default_factory=nan)
    orl: float = field(default_factory=nan)
    mid: float = field(default_factory=nan)
    endTime: int | None = None
    bars: int = 0
    partial: bool = False
    misaligned: bool = False
    valid: bool = True
    rangeOk: bool = True
    expireAt: int | None = None
    sigEndAt: int | None = None
    bullArmed: bool = False
    bearArmed: bool = False
    pendDir: int = 0
    pendBar: int | None = None
    lastBrkDir: int = 0
    fbWatch: int = 0
    fbBar: int | None = None
    brkCount: int = 0
    sigCount: int = 0
    trDir: int = 0
    trEntry: float = field(default_factory=nan)
    trStop: float = field(default_factory=nan)
    trStop0: float = field(default_factory=nan)
    trTp1: float = field(default_factory=nan)
    trTp2: float = field(default_factory=nan)
    trTp1Hit: bool = False
    trBE: bool = False
    trBar: int | None = None
    trTime: int | None = None
    trType: str = ""
    trId: str = ""
    ev: dict = field(default_factory=dict)


# ───────────────────────── engine (port of the Pine SHARED CORE) ─────────────────────────
class Engine:
    def __init__(self, p: Params):
        self.p = p

    def px(self, v, atr):
        return v * self.p.mintick if self.p.unit_ticks else v * (0.0 if isna(atr) else atr)

    def round_tick(self, v):
        return round(v / self.p.mintick) * self.p.mintick

    def day_ok(self, c: SessCfg, st: int) -> bool:
        dow = dayofweek(st, c.tz)
        return (self.p.is_crypto and self.p.crypto_7d) or c.days[dow - 1] == "1"

    def is_holiday(self, c: SessCfg, ds: str) -> bool:
        return c.hol_on and ds in c.hol

    @staticmethod
    def latest_start(c: SessCfg, t: int) -> int:
        d = local(t, c.tz)
        st = ts(c.tz, d.year, d.month, d.day, c.sh, c.sm)
        if st > t:
            p = ts(c.tz, d.year, d.month, d.day, 12, 0) - DAY_MS
            pd = local(p, c.tz)
            st = ts(c.tz, pd.year, pd.month, pd.day, c.sh, c.sm)
        return st

    @staticmethod
    def next_day_start(c: SessCfg, st: int) -> int:
        d = local(st, c.tz)
        p = ts(c.tz, d.year, d.month, d.day, 12, 0) + DAY_MS
        pd = local(p, c.tz)
        return ts(c.tz, pd.year, pd.month, pd.day, c.sh, c.sm)

    def close_trade(self, s: SessState, px: float, reason: int):
        risk0 = abs(s.trEntry - s.trStop0)
        s.ev["exit"] = (s.trDir, reason, s.trId, px, s.trDir * (px - s.trEntry) / risk0 if risk0 > 0 else nan())
        s.trDir = 0

    def open_trade(self, c, s, dir_, typ, b: Bar, atr, bar_index, bar_tc) -> bool:
        p = self.p
        buf = self.px(p.stop_buf, atr)
        if p.stop_mode == 1:
            stop = s.orl - buf if dir_ > 0 else s.orh + buf
        elif p.stop_mode == 2:
            stop = s.mid - buf if dir_ > 0 else s.mid + buf
        else:
            stop = b.c - atr * p.stop_atr if dir_ > 0 else b.c + atr * p.stop_atr
        stop = self.round_tick(stop)
        risk = b.c - stop if dir_ > 0 else stop - b.c
        if isna(risk) or risk <= 0:
            return False
        if s.trDir != 0:
            self.close_trade(s, b.c, 7)
        s.sigCount += 1
        s.trDir, s.trEntry, s.trStop, s.trStop0 = dir_, b.c, stop, stop
        s.trTp1 = self.round_tick(b.c + dir_ * risk * p.tp1_r)
        s.trTp2 = self.round_tick(b.c + dir_ * risk * max(p.tp2_r, p.tp1_r))
        s.trTp1Hit, s.trBE = False, False
        s.trBar, s.trTime, s.trType = bar_index, bar_tc, typ
        s.trId = f"{c.key}-{s.winDate.replace('-', '')}-{s.sigCount}{'L' if dir_ > 0 else 'S'}"
        s.ev["entry"] = (dir_, typ, b.c, stop, s.trTp1, s.trTp2)
        return True

    def manage_trade(self, s: SessState, b: Bar, atr, bar_tc):
        p = self.p
        if s.trDir == 1:
            if b.l <= s.trStop:
                self.close_trade(s, min(b.o, s.trStop), 4 if s.trBE else 3)
            else:
                if not s.trTp1Hit and b.h >= s.trTp1:
                    s.trTp1Hit = True
                    s.ev["tp1"] = s.trId
                    if p.be:
                        s.trStop = max(s.trStop, self.round_tick(s.trEntry + self.px(p.be_off, atr)))
                        s.trBE = True
                if b.h >= s.trTp2:
                    self.close_trade(s, max(b.o, s.trTp2), 2)
        elif s.trDir == -1:
            if b.h >= s.trStop:
                self.close_trade(s, max(b.o, s.trStop), 4 if s.trBE else 3)
            else:
                if not s.trTp1Hit and b.l <= s.trTp1:
                    s.trTp1Hit = True
                    s.ev["tp1"] = s.trId
                    if p.be:
                        s.trStop = min(s.trStop, self.round_tick(s.trEntry - self.px(p.be_off, atr)))
                        s.trBE = True
                if b.l <= s.trTp2:
                    self.close_trade(s, min(b.o, s.trTp2), 2)
        if s.trDir != 0:
            if p.exit_inside and ((s.trDir == 1 and b.c < s.orh) or (s.trDir == -1 and b.c > s.orl)):
                self.close_trade(s, b.c, 6)
            elif p.time_exit_min > 0 and bar_tc - s.trTime >= p.time_exit_min * 60000:
                self.close_trade(s, b.c, 5)

    def new_window(self, c, s, st, b: Bar, prev_tc):
        s.winStart, s.winEnd, s.win1hEnd = st, st + c.dur * 60000, st + 3_600_000
        s.winDate = s.candDate
        s.phase = 1
        s.hi = s.lo = s.orh = s.orl = s.mid = nan()
        s.endTime = None
        s.bars = 0
        s.misaligned = prev_tc is not None and prev_tc > st
        s.partial = b.time > st
        s.valid = not s.misaligned and not (prev_tc is None and b.time > st)
        s.rangeOk = True
        s.expireAt = s.sigEndAt = None
        s.bullArmed = s.bearArmed = False
        s.pendDir, s.pendBar, s.lastBrkDir = 0, None, 0
        s.fbWatch, s.fbBar, s.brkCount, s.sigCount = 0, None, 0, 0
        s.ev["new_window"] = st

    def finalize(self, c, s, end_t):
        p = self.p
        s.phase = 2
        s.orh, s.orl = s.hi, s.lo
        s.mid = self.round_tick((s.hi + s.lo) / 2)
        s.endTime = end_t
        exp_bars = math.floor(c.dur * 60 / p.tf_sec) if p.tf_sec > 0 else 0
        s.partial = s.partial or s.bars < exp_bars
        if s.misaligned or (p.skip_partial and s.partial):
            s.valid = False
        s.expireAt = s.winEnd + p.life_hrs * 3_600_000 if p.life_hrs > 0 else None
        sig_end = s.winEnd + p.sig_win_min * 60000 if p.sig_win_min > 0 else None
        if sig_end is None:
            s.sigEndAt = s.expireAt
        elif s.expireAt is None:
            s.sigEndAt = sig_end
        else:
            s.sigEndAt = min(sig_end, s.expireAt)
        s.bullArmed = s.bearArmed = True
        s.ev["range_done"] = (s.orh, s.orl)

    def momentum(self, dir_, b: Bar, atr):
        rng = b.h - b.l
        dir_bar = b.c > b.o if dir_ == 1 else b.c < b.o
        return dir_bar and rng > 0 and abs(b.c - b.o) >= rng * self.p.mom_body / 100 and (isna(atr) or rng >= atr * self.p.mom_atr)

    def signals(self, c, s, allow, b: Bar, atr, bar_index, bar_tc, f_long=True, f_short=True):
        p = self.p
        entry = 0
        in_sig = (s.sigEndAt is None or bar_tc <= s.sigEndAt) and (s.expireAt is None or bar_tc < s.expireAt)
        min_d, tol = self.px(p.min_dist, atr), self.px(p.tol, atr)
        can_enter = allow and s.valid and s.rangeOk and s.sigCount < p.max_sig and not (p.block_open and s.trDir != 0)
        if s.fbWatch == 1:
            if b.c < s.orh:
                s.ev["false"], s.fbWatch = 1, 0
            elif bar_index - s.fbBar >= p.fb_bars:
                s.fbWatch = 0
        elif s.fbWatch == -1:
            if b.c > s.orl:
                s.ev["false"], s.fbWatch = -1, 0
            elif bar_index - s.fbBar >= p.fb_bars:
                s.fbWatch = 0
        if not s.bullArmed and b.c < s.orh:
            s.bullArmed = True
        if not s.bearArmed and b.c > s.orl:
            s.bearArmed = True
        if s.pendDir != 0:
            if not in_sig or bar_index - s.pendBar > p.retest_bars:
                s.pendDir = 0
                s.ev["retest_timeout"] = True
            elif s.pendDir == 1:
                if b.c < s.orh:
                    s.pendDir = 0
                    s.ev["retest_fail"] = True
                elif b.l <= s.orh + tol and (not p.retest_candle or b.c > b.o):
                    s.pendDir = 0
                    took = can_enter and f_long and self.open_trade(c, s, 1, "RETEST", b, atr, bar_index, bar_tc)
                    if took:
                        entry = 1
                    else:
                        s.ev["filtered"] = 1
            else:
                if b.c > s.orl:
                    s.pendDir = 0
                    s.ev["retest_fail"] = True
                elif b.h >= s.orl - tol and (not p.retest_candle or b.c < b.o):
                    s.pendDir = 0
                    took = can_enter and f_short and self.open_trade(c, s, -1, "RETEST", b, atr, bar_index, bar_tc)
                    if took:
                        entry = -1
                    else:
                        s.ev["filtered"] = -1
        if entry == 0 and s.pendDir == 0 and in_sig and s.valid:
            bdir = 1 if (s.bullArmed and b.c > s.orh + min_d) else (-1 if (s.bearArmed and b.c < s.orl - min_d) else 0)
            if bdir != 0:
                if bdir == 1:
                    s.bullArmed = False
                else:
                    s.bearArmed = False
                s.brkCount += 1
                s.lastBrkDir = bdir
                s.ev["break"] = bdir
                if p.fb_on:
                    s.fbWatch, s.fbBar = bdir, bar_index
                dir_ok = p.long_ok if bdir == 1 else p.short_ok
                setup_ok = s.rangeOk and dir_ok and s.sigCount < p.max_sig and (not p.first_only or s.brkCount == 1)
                took = False
                if p.mode == 2:
                    if setup_ok:
                        s.pendDir, s.pendBar = bdir, bar_index
                        s.ev["setup"] = bdir
                elif setup_ok and can_enter and (f_long if bdir == 1 else f_short) and (p.mode == 1 or self.momentum(bdir, b, atr)):
                    took = self.open_trade(c, s, bdir, "MOMENTUM" if p.mode == 3 else "BREAKOUT", b, atr, bar_index, bar_tc)
                if took:
                    entry = bdir
                elif "setup" not in s.ev:
                    s.ev["filtered"] = bdir
        return entry

    def step(self, c: SessCfg, s: SessState, b: Bar, bar_index: int, prev_t, prev_tc, allow=True, atr=nan()):
        """One confirmed historical bar (barstate.isconfirmed is always true on history)."""
        p = self.p
        s.ev = {}
        entry = 0
        bar_tc = b.time_close or (b.time + p.tf_sec * 1000)
        if not (c.enabled and c.tf_ok):
            return entry
        if s.trDir != 0 and bar_index > s.trBar:
            self.manage_trade(s, b, atr, bar_tc)
        # session clock: timezone maths only when the cached next window start is reached
        if isna(s.candStart) or b.time >= s.candNext:
            new_st = self.latest_start(c, b.time)
            s.candStart = new_st
            s.candNext = self.next_day_start(c, new_st)
            s.candDate = date_str(new_st, c.tz)
            s.candOk = self.day_ok(c, new_st) and not self.is_holiday(c, s.candDate)
        st = s.candStart
        in_win = s.candOk and st <= b.time < st + c.dur * 60000
        if in_win and (isna(s.winStart) or pine_ne(st, s.winStart)):
            if s.trDir != 0:
                self.close_trade(s, b.c, 5)
            self.new_window(c, s, st, b, prev_tc)
        if s.phase == 1:
            if b.time < s.winEnd:
                s.hi = b.h if isna(s.hi) else max(s.hi, b.h)
                s.lo = b.l if isna(s.lo) else min(s.lo, b.l)
                s.bars += 1
                if bar_tc > s.winEnd:
                    s.misaligned = True
                if bar_tc >= s.winEnd:
                    self.finalize(c, s, b.time)
            else:
                self.finalize(c, s, prev_t)
        if s.phase == 2 and b.time >= s.winEnd:
            entry = self.signals(c, s, allow, b, atr, bar_index, bar_tc)
        if s.phase == 2 and s.expireAt is not None and bar_tc >= s.expireAt:
            s.phase = 3
            s.ev["expire"] = True
            s.pendDir = 0
            s.fbWatch = 0
            if s.trDir != 0:
                self.close_trade(s, b.c, 5)
        return entry


def run(engine: Engine, cfgs: list[SessCfg], bars: list[Bar]):
    """Runs all sessions over the bars with the 'one signal per bar' priority chain."""
    states = [SessState() for _ in cfgs]
    log = []
    prev_t = prev_tc = None
    for i, b in enumerate(bars):
        if not b.time_close:
            b.time_close = b.time + engine.p.tf_sec * 1000
        taken = False
        for c, s in zip(cfgs, states):
            e = engine.step(c, s, b, i, prev_t, prev_tc, allow=not taken)
            taken = taken or e != 0
            if s.ev:
                log.append((i, b.time, c.key, dict(s.ev)))
        prev_t, prev_tc = b.time, b.time_close
    return states, log


def window_table(first: str, days: int = 7):
    """Print each default session's window start in local, New York and UTC time."""
    from datetime import date as _date

    sessions = [
        SessCfg("NY", "America/New_York", 9, 30, days="0111110"),
        SessCfg("LDN", "Europe/London", 8, 0, days="0111110"),
        SessCfg("CME", "America/New_York", 18, 0, days="1111100"),
        SessCfg("TKY", "Asia/Tokyo", 9, 0, days="0111110"),
    ]
    d0 = _date.fromisoformat(first)
    print(f"{'local date':<12}{'session':<8}{'local':<12}{'New York':<16}{'UTC':<12}")
    for k in range(days):
        d = d0 + timedelta(days=k)
        for c in sessions:
            st = ts(c.tz, d.year, d.month, d.day, c.sh, c.sm)
            dow = dayofweek(st, c.tz)
            if c.days[dow - 1] != "1":
                continue
            print(f"{d.isoformat():<12}{c.key:<8}{local(st, c.tz).strftime('%a %H:%M'):<12}"
                  f"{local(st, 'America/New_York').strftime('%a %m-%d %H:%M'):<16}"
                  f"{local(st, 'UTC').strftime('%H:%M'):<12}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2:
        window_table(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    else:
        print("usage: python3 pine/tools/engine_reference.py YYYY-MM-DD [days]")
