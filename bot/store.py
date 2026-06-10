"""SQLite persistence: VIP subscriptions, referrals, and the public track
record that builds trust the screenshot's channel never earns."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass


@dataclass
class Sub:
    user_id: int
    expires_at: float


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS subs (
                user_id    INTEGER PRIMARY KEY,
                expires_at REAL NOT NULL,
                referred_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS referrals (
                referrer  INTEGER,
                referred  INTEGER PRIMARY KEY,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS calls (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT, side TEXT,
                entry REAL, stop_loss REAL, tp1 REAL, tp2 REAL,
                confidence INTEGER, tier TEXT,
                created_at REAL,
                outcome   TEXT DEFAULT 'open'   -- open|tp1|tp2|stop
            );
            """
        )
        self.db.commit()

    # --- subscriptions ----------------------------------------------------
    def grant_vip(self, user_id: int, days: int) -> float:
        now = time.time()
        cur = self.db.execute("SELECT expires_at FROM subs WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        base = max(now, row["expires_at"]) if row else now
        expires = base + days * 86400
        self.db.execute(
            "INSERT INTO subs(user_id, expires_at) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
            (user_id, expires),
        )
        self.db.commit()
        return expires

    def is_vip(self, user_id: int) -> bool:
        cur = self.db.execute("SELECT expires_at FROM subs WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return bool(row and row["expires_at"] > time.time())

    def vip_expiry(self, user_id: int) -> float | None:
        cur = self.db.execute("SELECT expires_at FROM subs WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row["expires_at"] if row else None

    # --- referrals --------------------------------------------------------
    def record_referral(self, referrer: int, referred: int) -> None:
        if referrer == referred:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO referrals(referrer, referred, created_at) VALUES(?,?,?)",
            (referrer, referred, time.time()),
        )
        self.db.commit()

    def referral_count(self, referrer: int) -> int:
        cur = self.db.execute("SELECT COUNT(*) c FROM referrals WHERE referrer=?", (referrer,))
        return cur.fetchone()["c"]

    # --- track record -----------------------------------------------------
    def log_call(self, sig, tier: str) -> int:
        cur = self.db.execute(
            "INSERT INTO calls(symbol,side,entry,stop_loss,tp1,tp2,confidence,tier,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (sig.symbol, sig.side, sig.entry, sig.stop_loss, sig.tp1, sig.tp2,
             sig.confidence, tier, time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def open_calls(self) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM calls WHERE outcome='open'"))

    def set_outcome(self, call_id: int, outcome: str) -> None:
        self.db.execute("UPDATE calls SET outcome=? WHERE id=?", (outcome, call_id))
        self.db.commit()

    def record_stats(self, days: int = 7) -> dict:
        since = time.time() - days * 86400
        rows = list(
            self.db.execute(
                "SELECT outcome, COUNT(*) c FROM calls "
                "WHERE created_at>=? AND outcome!='open' GROUP BY outcome",
                (since,),
            )
        )
        counts = {r["outcome"]: r["c"] for r in rows}
        wins = counts.get("tp1", 0) + counts.get("tp2", 0)
        losses = counts.get("stop", 0)
        total = wins + losses
        return {
            "wins": wins,
            "losses": losses,
            "total": total,
            "win_rate": (wins / total * 100) if total else 0.0,
        }
