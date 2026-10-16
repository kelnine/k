"""Script 6's campaign state: the Pine ``WS`` type (L366-483), ``PivotTriplet`` (L354-363)
and the script's integer codes (L178-263).

``WS`` mirrors the Pine type field by field, in the same order, with snake-case names
(the Pine name is in each comment). Pine's ``na`` is ``math.nan`` for floats and ``None``
for ints; every comparison with a ``None`` int is written out in the engine the way Pine
evaluates it (a comparison with na is false). One field is the port's own: ``serial``,
the campaign's identity, so the strategy can tell which campaign a trade belongs to
(Pine compares campaign objects by reference and climax time instead, L1811).
"""

import math
from dataclasses import dataclass, field

# ── directions, types, regimes, phases (L179-198) ─────────────────────────────────────────
DIR_NONE = 0
DIR_ACCUM = 1
DIR_DIST = -1

TYPE_NONE = 0
TYPE_ACCUM = 1
TYPE_REACCUM = 2
TYPE_DIST = -1
TYPE_REDIST = -2

REGIME_NONE = 0
REGIME_MARKUP = 1
REGIME_MARKDOWN = -1

PHASE_NONE = 0
PHASE_A = 1
PHASE_B = 2
PHASE_C = 3
PHASE_D = 4
PHASE_E = 5

# ── events (L208-223) ─────────────────────────────────────────────────────────────────────
EV_NONE = 0
EV_SC = 1
EV_BC = 2
EV_AR = 3
EV_ST = 4
EV_SPRING = 5
EV_UTAD = 6
EV_TEST = 7
EV_SOS = 8
EV_SOW = 9
EV_LPS = 10
EV_LPSY = 11
EV_CTEST_ACC = 12
EV_CTEST_DST = 13
EV_MARKUP = 14
EV_MARKDOWN = 15

# ── Phase B test classes (L225-228) and entry kinds (L230-234) ────────────────────────────
TEST_NONE = 0
TEST_GOOD = 1
TEST_POOR = 2
TEST_FAILED = 3

ENTRY_NONE = 0
ENTRY_TEST = 1
ENTRY_STRENGTH = 2
ENTRY_LPS = 3
ENTRY_PHASE_E = 4

# ── per-bar event bits (L242-255) ─────────────────────────────────────────────────────────
BIT_PS = 1
BIT_SC = 2
BIT_BC = 4
BIT_AR = 8
BIT_ST = 16
BIT_SPRING = 32
BIT_UTAD = 64
BIT_TEST = 128
BIT_SOS = 256
BIT_SOW = 512
BIT_LPS = 1024
BIT_LPSY = 2048
BIT_E = 4096
BIT_CTEST = 16384

# ── reset reasons (L257-263) ──────────────────────────────────────────────────────────────
RS_INVALID = 0
RS_ABSORB = 1
RS_NORANGE = 2
RS_DEPART = 3
RS_STALE = 4
RS_DEMOTE = 5
RS_EEND = 6

PHASE_NAMES = {
    PHASE_NONE: "-",
    PHASE_A: "A",
    PHASE_B: "B",
    PHASE_C: "C",
    PHASE_D: "D",
    PHASE_E: "E",
}
DIR_NAMES = {DIR_NONE: "NONE", DIR_ACCUM: "ACCUM", DIR_DIST: "DIST"}
TYPE_NAMES = {
    TYPE_NONE: "NONE",
    TYPE_ACCUM: "Accumulation",
    TYPE_REACCUM: "Reaccumulation",
    TYPE_DIST: "Distribution",
    TYPE_REDIST: "Redistribution",
}
EVENT_NAMES = {
    EV_NONE: "NONE",
    EV_SC: "SC",
    EV_BC: "BC",
    EV_AR: "AR",
    EV_ST: "ST",
    EV_SPRING: "Spring",
    EV_UTAD: "UTAD",
    EV_TEST: "Test",
    EV_SOS: "SOS",
    EV_SOW: "SOW",
    EV_LPS: "LPS",
    EV_LPSY: "LPSY",
    EV_CTEST_ACC: "C-Test (accumulation)",
    EV_CTEST_DST: "C-Test (distribution)",
    EV_MARKUP: "Markup",
    EV_MARKDOWN: "Markdown",
}
ENTRY_NAMES = {
    ENTRY_NONE: "NONE",
    ENTRY_TEST: "TEST",
    ENTRY_STRENGTH: "STRENGTH",
    ENTRY_LPS: "LPS",
    ENTRY_PHASE_E: "PHASE_E",
}
BIT_NAMES = (
    (BIT_PS, "PS"),
    (BIT_SC, "SC"),
    (BIT_BC, "BC"),
    (BIT_AR, "AR"),
    (BIT_ST, "ST"),
    (BIT_SPRING, "Spring"),
    (BIT_UTAD, "UTAD"),
    (BIT_TEST, "Test"),
    (BIT_SOS, "SOS"),
    (BIT_SOW, "SOW"),
    (BIT_LPS, "LPS"),
    (BIT_LPSY, "LPSY"),
    (BIT_E, "Phase E"),
    (BIT_CTEST, "C-Test"),
)
RESET_NAMES = {
    RS_INVALID: "RS_INVALID",
    RS_ABSORB: "RS_ABSORB",
    RS_NORANGE: "RS_NORANGE",
    RS_DEPART: "RS_DEPART",
    RS_STALE: "RS_STALE",
    RS_DEMOTE: "RS_DEMOTE",
    RS_EEND: "RS_EEND",
}


def bit_names(mask: int) -> list[str]:
    """The names of the event bits set in ``mask`` (``f_hasBit``, L564), in bit order."""
    return [name for bit, name in BIT_NAMES if mask & bit]


def has_bit(mask: int, bit: int) -> bool:
    """``f_hasBit(_mask, _bit)`` (L564-565) for the script's power-of-two bits."""
    return mask & bit != 0


def add_bit(mask: int, bit: int) -> int:
    """``f_addBit`` (L567-568): the bit is added once."""
    return mask | bit


NAN = math.nan


@dataclass(slots=True)
class PivotTriplet:
    """``PivotTriplet`` (L354-363): the first three same/opposite-edge Phase B pivots."""

    b1: int | None = None
    t1: float = NAN
    p1: float = NAN
    b2: int | None = None
    t2: float = NAN
    p2: float = NAN
    b3: int | None = None
    t3: float = NAN
    p3: float = NAN


@dataclass(slots=True)
class WS:
    """Campaign state, the Pine ``WS`` type (L366-483), field by field.

    Times are Pine ``time`` values: bar open times in milliseconds since the epoch, as
    floats. ``st_hist``/``op_hist`` are ``na`` (None) until ``f_initPivotHistory`` runs,
    which the engine does right after every ``WS.new()`` (L1092, L1234, L1270, L1676).
    """

    stop_side: int = 0  # stopSide
    outcome: int = 0  # outcome
    phase: int = 0  # phase
    ev: int = 0  # ev
    start_bar: int | None = None  # startBar
    piv_len: int | None = None  # pivLen
    birth_trend: float = NAN  # birthTrend
    ctx_bull: bool = False  # ctxBull
    ctx_bear: bool = False  # ctxBear
    climax_bar: int | None = None  # climaxBar
    climax_time: float = NAN  # climaxTime
    climax_price: float = NAN  # climaxPrice
    climax_eff: float = NAN  # climaxEff
    climax_spr: float = NAN  # climaxSpr
    climax_atr: float = NAN  # climaxATR
    climax_score: int = 0  # climaxScore
    absorbed: bool = False  # absorbed
    ps_time: float = NAN  # psTime
    ps_price: float = NAN  # psPrice
    ps_score: int = 0  # psScore
    orig_high: float = NAN  # origHigh
    orig_low: float = NAN  # origLow
    range_high: float = NAN  # rangeHigh
    range_low: float = NAN  # rangeLow
    ar_run_price: float = NAN  # arRunPrice
    ar_run_bar: int | None = None  # arRunBar
    ar_run_time: float = NAN  # arRunTime
    ar_ok: bool = False  # arOK
    ar_bar: int | None = None  # arBar
    ar_time: float = NAN  # arTime
    ar_price: float = NAN  # arPrice
    st_count: int = 0  # stCount
    st_n: int = 0  # stN
    st_eff_sum: float = 0.0  # stEffSum
    st_spr_sum: float = 0.0  # stSprSum
    last_good_eff: float = NAN  # lastGoodEff
    last_good_spr: float = NAN  # lastGoodSpr
    st_bar: int | None = None  # stBar
    st_time: float = NAN  # stTime
    st_price: float = NAN  # stPrice
    st_hist: PivotTriplet | None = None  # stHist
    st_score: int = 0  # stScore
    edge1: float = NAN  # edge1
    edge2: float = NAN  # edge2
    edge3: float = NAN  # edge3
    opp_count: int = 0  # oppCount
    op_n: int = 0  # opN
    op_eff_sum: float = 0.0  # opEffSum
    op_spr_sum: float = 0.0  # opSprSum
    op_last_bar: int | None = None  # opLastBar
    op_last_price: float = NAN  # opLastPrice
    op_hist: PivotTriplet | None = None  # opHist
    trav_count: int = 0  # travCount
    last_zone: int = 0  # lastZone
    last_zone_bar: int | None = None  # lastZoneBar
    last_bad_bar: int | None = None  # lastBadBar
    b_start_bar: int | None = None  # bStartBar
    b_start_time: float = NAN  # bStartTime
    c_start_time: float = NAN  # cStartTime
    c_ready_bar: int | None = None  # cReadyBar
    d_start_bar: int | None = None  # dStartBar
    d_start_time: float = NAN  # dStartTime
    e_start_bar: int | None = None  # eStartBar
    e_start_time: float = NAN  # eStartTime
    pend: bool = False  # pend
    pend_edge: int = 0  # pendEdge
    pend_start_bar: int | None = None  # pendStartBar
    pend_ext_bar: int | None = None  # pendExtBar
    pend_ext: float = NAN  # pendExt
    pend_ext_time: float = NAN  # pendExtTime
    pend_eff: float = NAN  # pendEff
    pend_spr: float = NAN  # pendSpr
    pend_cool_bar: int | None = None  # pendCoolBar
    prov_edge: int = 0  # provEdge
    prov_bar: int | None = None  # provBar
    prov_price: float = NAN  # provPrice
    prov_time: float = NAN  # provTime
    prov_eff: float = NAN  # provEff
    prov_spr: float = NAN  # provSpr
    prov_score: int = 0  # provScore
    exc: bool = False  # exc
    exc_tested: bool = False  # excTested
    exc_bar: int | None = None  # excBar
    exc_price: float = NAN  # excPrice
    exc_time: float = NAN  # excTime
    exc_eff: float = NAN  # excEff
    exc_spr: float = NAN  # excSpr
    exc_score: int = 0  # excScore
    test_time: float = NAN  # testTime
    test_price: float = NAN  # testPrice
    test_score: int = 0  # testScore
    str_bar: int | None = None  # strBar
    str_time: float = NAN  # strTime
    str_price: float = NAN  # strPrice
    str_score: int = 0  # strScore
    lps_time: float = NAN  # lpsTime
    lps_price: float = NAN  # lpsPrice
    lps_bar: int | None = None  # lpsBar
    lps_score: int = 0  # lpsScore

    entry_time: float = NAN  # entryTime
    entry_price: float = NAN  # entryPrice
    entry_kind: int = 0  # entryKind
    out_count: int = 0  # outCount
    last_event_bar: int | None = None  # lastEventBar
    last_event_time: float = NAN  # lastEventTime
    last_event_price: float = NAN  # lastEventPrice
    last_act_bar: int | None = None  # lastActBar
    cf_prior: bool = False  # cfPrior
    cf_climax: bool = False  # cfClimax
    cf_ar: bool = False  # cfAR
    cf_st: bool = False  # cfST
    cf_exc: bool = False  # cfExc
    cf_test: bool = False  # cfTest
    cf_strength: bool = False  # cfStrength
    cf_lps: bool = False  # cfLPS
    cf_accept: bool = False  # cfAccept

    serial: int = field(default=0, compare=False)  # port only: the campaign's identity
