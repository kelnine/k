#!/usr/bin/env python3
"""Unit tests for the engine design (pure Python, standard library only).

    python3 pine/tools/test_engine_reference.py -v

These exercise the reference model in engine_reference.py, which mirrors the Pine
SHARED CORE. They validate session times across DST, holidays, missing bars,
timeframe alignment, range freezing and the signal / trade rules.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine_reference import Bar, Engine, Params, SessCfg, SessState, local, run, ts  # noqa: E402

NY = "America/New_York"


def cfg_ny(**kw):
    return SessCfg(key="NY", tz=NY, sh=9, sm=30, **kw)


def cfg_ldn(**kw):
    return SessCfg(key="LDN", tz="Europe/London", sh=8, sm=0, **kw)


def cfg_cme(**kw):
    return SessCfg(key="CME", tz=NY, sh=18, sm=0, days="1111100", **kw)


def cfg_tky(**kw):
    return SessCfg(key="TKY", tz="Asia/Tokyo", sh=9, sm=0, **kw)


def bar(day: str, hhmm: str, o, h, l, c, tf_min=5, tz=NY) -> Bar:
    y, m, d = map(int, day.split("-"))
    hh, mm = map(int, hhmm.split(":"))
    t = ts(tz, y, m, d, hh, mm)
    return Bar(t, o, h, l, c, t + tf_min * 60000)


def flat_bars(day: str, start: str, end: str, price=100.0, tf_min=5):
    """Flat 1-tick bars between two NY times (inclusive start, exclusive end)."""
    y, m, d = map(int, day.split("-"))
    t = ts(NY, y, m, d, *map(int, start.split(":")))
    t_end = ts(NY, y, m, d, *map(int, end.split(":")))
    out = []
    while t < t_end:
        out.append(Bar(t, price, price + 0.25, price - 0.25, price, t + tf_min * 60000))
        t += tf_min * 60000
    return out


def events(log, key=None, kind=None):
    return [(i, ev) for i, _, k, ev in log if (key is None or k == key) and (kind is None or kind in ev)]


class SessionClock(unittest.TestCase):
    """Window membership must match a direct timezone computation for every bar."""

    def check_range(self, c: SessCfg, first: date, last: date):
        eng = Engine(Params())
        tz = ZoneInfo(c.tz)
        # ground truth: windows on allowed local weekdays
        truth = set()
        d = first - timedelta(days=2)
        while d <= last + timedelta(days=2):
            st = datetime(d.year, d.month, d.day, c.sh, c.sm, tzinfo=tz)
            pine_dow = st.isoweekday() % 7 + 1
            if c.days[pine_dow - 1] == "1":
                for k in range(c.dur // 5):
                    truth.add(int((st + timedelta(minutes=5 * k)).timestamp() * 1000))
            d += timedelta(days=1)
        t = int(datetime(first.year, first.month, first.day, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
        t_end = int(datetime(last.year, last.month, last.day, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
        n_in = 0
        while t < t_end:
            st = eng.latest_start(c, t)
            ok = eng.day_ok(c, st)
            in_win = ok and st <= t < st + c.dur * 60000
            self.assertEqual(in_win, t in truth, f"{c.key} {datetime.fromtimestamp(t / 1000, tz)}")
            n_in += in_win
            t += 300_000
        self.assertGreater(n_in, 0)

    def test_all_sessions_through_2026_2027_dst_changes(self):
        spans = [(date(2026, 3, 1), date(2026, 4, 6)), (date(2026, 10, 20), date(2026, 11, 10)),
                 (date(2027, 3, 8), date(2027, 4, 2)), (date(2027, 10, 25), date(2027, 11, 12))]
        for c in (cfg_ny(), cfg_ldn(), cfg_cme(), cfg_tky()):
            for a, b in spans:
                self.check_range(c, a, b)

    def test_window_crossing_local_midnight(self):
        # 23:50 + 30 min crosses midnight: bars after 00:00 must still belong to the previous day's window
        self.check_range(SessCfg(key="X", tz=NY, sh=23, sm=50, dur=30, days="1111111"), date(2026, 3, 5), date(2026, 3, 12))

    def test_london_open_in_new_york_time(self):
        c = cfg_ldn()
        expect_4am = {date(2026, 3, 9), date(2026, 3, 27), date(2026, 10, 26), date(2026, 10, 30),
                      date(2027, 3, 15), date(2027, 3, 26), date(2027, 11, 1)}
        expect_3am = {date(2026, 3, 6), date(2026, 3, 30), date(2026, 10, 23), date(2026, 11, 2),
                      date(2027, 3, 12), date(2027, 3, 29), date(2027, 11, 8)}
        for d in expect_4am | expect_3am:
            st = ts(c.tz, d.year, d.month, d.day, 8, 0)
            ny = local(st, NY)
            self.assertEqual(ny.hour, 4 if d in expect_4am else 3, str(d))
            self.assertEqual(ny.date(), d)

    def test_tokyo_is_previous_new_york_evening(self):
        c = cfg_tky()
        st = ts(c.tz, 2026, 11, 24, 9, 0)  # US winter
        self.assertEqual(local(st, NY).strftime("%Y-%m-%d %H:%M"), "2026-11-23 19:00")
        st = ts(c.tz, 2026, 7, 15, 9, 0)  # US summer
        self.assertEqual(local(st, NY).strftime("%Y-%m-%d %H:%M"), "2026-07-14 20:00")

    def test_cme_sunday_reopen_and_no_friday(self):
        eng = Engine(Params())
        bars = flat_bars("2026-11-20", "17:30", "18:30") + flat_bars("2026-11-22", "18:00", "18:30")
        _, log = run(eng, [cfg_cme()], bars)
        starts = [local(ev["new_window"], NY).strftime("%a %H:%M") for _, ev in events(log, kind="new_window")]
        self.assertEqual(starts, ["Sun 18:00"])

    def test_holiday_is_skipped(self):
        eng = Engine(Params())
        c = cfg_ny(hol="2026-11-26 Thanksgiving")
        bars = flat_bars("2026-11-26", "09:00", "10:30") + flat_bars("2026-11-27", "09:00", "10:30")
        _, log = run(eng, [c], bars)
        starts = [local(ev["new_window"], NY).strftime("%m-%d") for _, ev in events(log, kind="new_window")]
        self.assertEqual(starts, ["11-27"])


def ny_session(after, tf_min=5, open_bars=None):
    """Bars for 2026-11-24 (Tue): pre-market, a 100–110 opening range, then `after`."""
    day = "2026-11-24"
    pre = flat_bars(day, "09:00", "09:30", 103.0, tf_min)
    rng = open_bars if open_bars is not None else [
        bar(day, "09:30", 103, 105, 100, 104),
        bar(day, "09:35", 104, 110, 102, 109),  # closes near the high while forming
        bar(day, "09:40", 109, 108.5, 101, 105),
    ]
    out = pre + rng
    t = ts(NY, 2026, 11, 24, 9, 45)
    for o, h, l, c in after:
        out.append(Bar(t, o, h, l, c, t + tf_min * 60000))
        t += tf_min * 60000
    return out


class RangeAndSignals(unittest.TestCase):
    def test_range_freezes_at_window_close_and_no_signal_while_forming(self):
        eng = Engine(Params())
        bars = ny_session([(105, 106, 104, 105)])
        # a forming bar closing above the running high must not signal
        bars[7] = bar("2026-11-24", "09:35", 104, 110, 102, 109.9)
        states, log = run(eng, [cfg_ny()], bars)
        done = events(log, kind="range_done")
        self.assertEqual(len(done), 1)
        i, ev = done[0]
        self.assertEqual(ev["range_done"], (110, 100))
        self.assertEqual(local(bars[i].time, NY).strftime("%H:%M"), "09:40")
        self.assertEqual(events(log, kind="entry"), [])

    def test_breakout_close_needs_min_distance(self):
        eng = Engine(Params())  # min distance 2 ticks = 0.5
        bars = ny_session([(108, 110.6, 107, 110.25), (110, 112, 109.5, 111)])
        _, log = run(eng, [cfg_ny()], bars)
        ent = events(log, kind="entry")
        self.assertEqual(len(ent), 1)
        i, ev = ent[0]
        self.assertEqual(local(bars[i].time, NY).strftime("%H:%M"), "09:50")
        d, typ, entry, stop, tp1, tp2 = ev["entry"]
        self.assertEqual((d, typ, entry, stop), (1, "BREAKOUT", 111, 99.5))  # ORL − 2 ticks
        self.assertEqual((tp1, tp2), (122.5, 134.0))

    def test_bearish_breakout_and_direction_filter(self):
        bars = ny_session([(101, 101, 98, 99)])
        _, log = run(Engine(Params()), [cfg_ny()], bars)
        self.assertEqual(events(log, kind="entry")[0][1]["entry"][0], -1)
        _, log = run(Engine(Params(short_ok=False)), [cfg_ny()], bars)
        self.assertEqual(events(log, kind="entry"), [])
        self.assertEqual(events(log, kind="filtered")[0][1]["filtered"], -1)

    def test_retest_requires_prior_breakout(self):
        p = Params(mode=2)
        # breakout close 112, then a bar wicks to 110.5 (within 8-tick tolerance of 110) and closes green above
        bars = ny_session([(109, 112.5, 108.8, 112), (112, 113, 110.5, 112.75)])
        _, log = run(Engine(p), [cfg_ny()], bars)
        self.assertEqual(len(events(log, kind="setup")), 1)
        ent = events(log, kind="entry")
        self.assertEqual(len(ent), 1)
        self.assertEqual(ent[0][1]["entry"][1], "RETEST")
        self.assertEqual(local(bars[ent[0][0]].time, NY).strftime("%H:%M"), "09:50")
        # same touch without a prior breakout → no retest
        bars2 = ny_session([(109, 110.4, 108, 110.3), (110.3, 111, 110.1, 110.4)])
        _, log2 = run(Engine(p), [cfg_ny()], bars2)
        self.assertEqual(events(log2, kind="entry"), [])

    def test_retest_failure_and_false_breakout_warning(self):
        p = Params(mode=2)
        bars = ny_session([(109, 112.5, 108.8, 112), (112, 112.2, 108, 108.5)])
        _, log = run(Engine(p), [cfg_ny()], bars)
        self.assertEqual(events(log, kind="entry"), [])
        self.assertEqual(len(events(log, kind="retest_fail")), 1)
        self.assertEqual(events(log, kind="false")[0][1]["false"], 1)

    def test_retest_timeout(self):
        p = Params(mode=2, retest_bars=2)
        after = [(109, 112.5, 108.8, 112)] + [(113, 114, 112.8, 113.5)] * 4
        _, log = run(Engine(p), [cfg_ny()], ny_session(after))
        self.assertEqual(len(events(log, kind="retest_timeout")), 1)
        self.assertEqual(events(log, kind="entry"), [])

    def test_momentum_mode_needs_strong_candle(self):
        p = Params(mode=3, mom_atr=0)
        weak = ny_session([(110.2, 113, 109, 110.8)])  # body 0.6 of range 4
        _, log = run(Engine(p), [cfg_ny()], weak)
        self.assertEqual(events(log, kind="entry"), [])
        strong = ny_session([(108, 112.2, 107.8, 112)])
        _, log = run(Engine(p), [cfg_ny()], strong)
        self.assertEqual(events(log, kind="entry")[0][1]["entry"][1], "MOMENTUM")

    def test_tp1_break_even_then_stop_at_entry(self):
        bars = ny_session([(110, 112, 109.5, 111), (111, 123, 110.8, 122), (122, 122.5, 110, 111)])
        _, log = run(Engine(Params()), [cfg_ny()], bars)
        self.assertEqual(len(events(log, kind="tp1")), 1)
        ex = events(log, kind="exit")
        self.assertEqual(len(ex), 1)
        d, reason, _id, px, r = ex[0][1]["exit"]
        self.assertEqual((d, reason, px), (1, 4, 111.25))  # break-even stop = entry + 1 tick
        self.assertAlmostEqual(r, 0.25 / 11.5, places=6)

    def test_same_bar_stop_and_target_counts_stop_first(self):
        bars = ny_session([(110, 112, 109.5, 111), (111, 135, 99, 120)])
        _, log = run(Engine(Params()), [cfg_ny()], bars)
        self.assertEqual(events(log, kind="exit")[0][1]["exit"][1], 3)

    def test_first_breakout_only_and_max_signals(self):
        # long breakout → stopped → short breakout
        after = [(110, 112, 109.5, 111), (111, 111, 98, 98.5), (98.5, 99, 97, 97.5)]
        _, log = run(Engine(Params()), [cfg_ny()], ny_session(after))
        self.assertEqual([ev["entry"][0] for _, ev in events(log, kind="entry")], [1, -1])
        _, log = run(Engine(Params(first_only=True)), [cfg_ny()], ny_session(after))
        self.assertEqual([ev["entry"][0] for _, ev in events(log, kind="entry")], [1])
        _, log = run(Engine(Params(max_sig=1)), [cfg_ny()], ny_session(after))
        self.assertEqual(len(events(log, kind="entry")), 1)

    def test_missing_last_window_bar_freezes_on_next_bar(self):
        day = "2026-11-24"
        opening = [bar(day, "09:30", 103, 105, 100, 104), bar(day, "09:35", 104, 110, 102, 109)]
        bars = flat_bars(day, "09:00", "09:30", 103.0) + opening
        bars.append(bar(day, "09:50", 109, 112, 108, 111))  # 09:40 and 09:45 bars missing
        states, log = run(Engine(Params()), [cfg_ny()], bars)
        i, ev = events(log, kind="range_done")[0]
        self.assertEqual(ev["range_done"], (110, 100))
        self.assertEqual(i, len(bars) - 1)
        self.assertTrue(states[0].partial)
        self.assertEqual(len(events(log, kind="entry")), 1)  # signal evaluated on the same (post-window) bar

    def test_missing_first_bar_is_partial(self):
        day = "2026-11-24"
        opening = [bar(day, "09:35", 104, 110, 102, 109), bar(day, "09:40", 109, 108.5, 101, 105)]
        bars = flat_bars(day, "09:00", "09:30", 103.0) + opening + [bar(day, "09:45", 109, 112, 108, 111)]
        states, log = run(Engine(Params()), [cfg_ny()], bars)
        self.assertTrue(states[0].partial)
        self.assertEqual(len(events(log, kind="entry")), 1)
        states, log = run(Engine(Params(skip_partial=True)), [cfg_ny()], bars)
        self.assertFalse(states[0].valid)
        self.assertEqual(events(log, kind="entry"), [])

    def test_misaligned_timeframe_is_invalid(self):
        # 10-minute bars cannot tile 09:30–09:45: the 09:40 bar closes at 09:50
        p = Params(tf_sec=600)
        day = "2026-11-24"
        bars = [bar(day, hm, 103, 105, 100, 104, tf_min=10) for hm in ("09:00", "09:10", "09:20", "09:30", "09:40")]
        bars.append(bar(day, "09:50", 104, 115, 103, 114, tf_min=10))
        states, log = run(Engine(p), [cfg_ny()], bars)
        self.assertTrue(states[0].misaligned)
        self.assertFalse(states[0].valid)
        self.assertEqual(events(log, kind="entry"), [])

    def test_expiry_closes_trade_and_stops_signals(self):
        p = Params(life_hrs=1)
        after = [(110, 112, 109.5, 111)] + [(111, 112, 110.8, 111.5)] * 14
        states, log = run(Engine(p), [cfg_ny()], ny_session(after))
        ex = events(log, kind="exit")
        self.assertEqual(ex[0][1]["exit"][1], 5)
        self.assertEqual(states[0].phase, 3)
        i, _ = events(log, kind="expire")[0]
        self.assertEqual(local(ny_session(after)[i].time_close, NY).strftime("%H:%M"), "10:45")

    def test_signal_window(self):
        p = Params(sig_win_min=15)
        after = [(105, 106, 104, 105)] * 3 + [(110, 112, 109.5, 111)]  # breakout at 10:00 bar (closes 10:05)
        _, log = run(Engine(p), [cfg_ny()], ny_session(after))
        self.assertEqual(events(log, kind="entry"), [])

    def test_one_signal_per_bar_across_sessions(self):
        a = cfg_ny()
        b = SessCfg(key="NY2", tz=NY, sh=9, sm=30)
        _, log = run(Engine(Params()), [a, b], ny_session([(110, 112, 109.5, 111)]))
        self.assertEqual([k for _, _, k, ev in log if "entry" in ev], ["NY"])

    def test_new_window_resets_levels(self):
        bars = ny_session([(110, 112, 109.5, 111)])
        # next day trades inside the old trade's stop/targets, so only the new window can close it
        bars += flat_bars("2026-11-25", "09:20", "10:00", 115.0)
        states, log = run(Engine(Params(life_hrs=0)), [cfg_ny()], bars)
        self.assertEqual(states[0].orh, 115.25)
        self.assertEqual(states[0].winDate, "2026-11-25")
        self.assertEqual(events(log, kind="exit")[0][1]["exit"][1], 5)


if __name__ == "__main__":
    unittest.main()
