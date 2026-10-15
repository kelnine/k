"""The fixed settings of script 6's campaign engine (``06_wyckoff_theultimator5.pine``).

Every value below is hard-coded in the script (L53-176), not an input; the names are the
Pine names in upper snake case and each line cites its Pine line. The thresholds the
script writes inline inside expressions (``sprATR >= 0.80``, ``pEff <= climaxEff * 1.20``
…) stay inline in ``measures.py`` / ``wyckoff_engine.py`` next to their Pine line number.
Only Entry Strictness (L28) is a user input that changes the Auto entry; it is the
strategy's ``entry_strictness`` param.

The schematic layout constants (L53-55) and the multi-timeframe scan (L175-176) belong
to the display and the higher-timeframe override, which are not ported (README).
"""

# ── Structure detection (L56-69) ──────────────────────────────────────────────────────────
PIVOT_LEN = 4  # pivotLen (L57)
ADAPTIVE_SWING_MIN = 2  # adaptiveSwingMin (L59); swingModeInput = "ATR Adaptive" (L58)
ADAPTIVE_SWING_MAX = 10  # adaptiveSwingMax (L60)
ADAPTIVE_SWING_VOL_LEN = 50  # adaptiveSwingVolLen (L61)
TREND_LEN = 25  # trendLen (L62)
PRIOR_TREND_MAX_BARS = 200  # priorTrendMaxBars (L63)
PRIOR_TREND_PIVOT_FACTOR = 8.0  # priorTrendPivotFactor (L64)
PRIOR_TREND_STRONG = 35.0  # priorTrendStrong (L65)
PRIOR_TREND_NEUTRAL = 15.0  # priorTrendNeutral (L66)
CONTINUATION_TREND_LEN = 200  # continuationTrendLen (L67)
OPPOSITE_CYCLE_MIN_BARS = 25  # oppositeCycleMinBars (L68)
EXTREME_LEN = 30  # extremeLen (L69)

# ── Campaign lifecycle (L70-84) ───────────────────────────────────────────────────────────
PHASE_A_MIN_BARS = 6  # phaseAMinBars (L71)
PHASE_A_AFTER_AR_MAX_BARS = 45  # phaseAAfterArMaxBars (L72)
PHASE_B_IDLE_MAX_BARS = 125  # phaseBIdleMaxBars (L73)
PHASE_C_IDLE_MAX_BARS = 50  # phaseCIdleMaxBars (L74)
PHASE_A_PREMATURE_DEPARTURE_BARS = 3  # phaseAPrematureDepartureBars (L75)
PHASE_A_PREMATURE_DEPARTURE_TR_FRAC = 0.30  # phaseAPrematureDepartureTRFrac (L76)
PHASE_A_PREMATURE_DEPARTURE_ATR = 0.75  # phaseAPrematureDepartureATR (L77)
STRUCTURE_INVALIDATION_ATR = 0.50  # structureInvalidationATR (L78)
STRUCTURE_INVALIDATION_BARS = 2  # structureInvalidationBars (L79)
PHASE_B_DEPARTURE_BARS = 3  # phaseBDepartureBars (L80)
PHASE_B_DEPARTURE_TR_FRAC = 0.35  # phaseBDepartureTRFrac (L81)
PHASE_B_DEPARTURE_ATR = 0.75  # phaseBDepartureATR (L82)
PHASE_D_FAIL_BARS = 3  # phaseDFailBars (L83)
PHASE_E_MAX_BARS = 300  # phaseEMaxBars (L84)

# ── Volume and volatility (L86-96) ────────────────────────────────────────────────────────
VOL_LEN = 50  # volLen (L87)
ATR_LEN = 14  # atrLen (L88)
CLIMAX_VOL_MULT = 1.8  # climaxVolMult (L89)
CLIMAX_SPREAD_MULT = 1.5  # climaxSpreadMult (L90)
RELAXED_CLIMAX_FACTOR = 0.80  # relaxedClimaxFactor (L91)
PRELIM_VOL_MULT = 1.25  # prelimVolMult (L92)
PRELIM_EXTREME_ATR = 0.75  # prelimExtremeATR (L93)
PRELIM_EFFICIENCY_LOOKBACK = 10  # prelimEfficiencyLookback (L94)
PRELIM_EFFICIENCY_RATIO = 0.80  # prelimEfficiencyRatio (L95)
PRELIM_MIN_SCORE = 4  # prelimMinScore (L96)

# ── Climax confirmation (L98-106) ─────────────────────────────────────────────────────────
SC_CLOSE_MIN = 0.35  # scCloseMin (L99)
BC_CLOSE_MAX = 0.65  # bcCloseMax (L100)
CLIMAX_MIN_SCORE = 5  # climaxMinScore (L101)
CLIMAX_ABSORPTION_MIN_BARS = 3  # climaxAbsorptionMinBars (L102)
CLIMAX_ABSORPTION_MAX_BARS = 8  # climaxAbsorptionMaxBars (L103)
CLIMAX_ABSORPTION_EXTREME_ATR = 0.50  # climaxAbsorptionExtremeATR (L104)
CLIMAX_ABSORPTION_REBOUND_ATR = 0.35  # climaxAbsorptionReboundATR (L105)
CLIMAX_ABSORPTION_VOL_FLOOR = 0.90  # climaxAbsorptionVolFloor (L106)

# ── AR and Phase B (L108-128) ─────────────────────────────────────────────────────────────
MIN_AR_ATR = 2.0  # minARATR (L109)
MAX_AR_BARS = 30  # maxARBars (L110)
AR_MAX_EXTENSION_ATR = 15.0  # arMaxExtensionATR (L111)
BOUNDARY_TOL_ATR = 0.75  # boundaryTolATR (L112)
ST_MAX_VOL_RATIO = 0.90  # stMaxVolRatio (L113)
ST_MAX_SPREAD_RATIO = 0.90  # stMaxSpreadRatio (L114)
ST_MIN_SCORE = 4  # stMinScore (L115)
MIN_PHASE_B_BARS = 30  # minPhaseBBars (L116)
MIN_PHASE_B_TESTS = 2  # minPhaseBTests (L117)
MIN_PHASE_B_OPPOSITE_TESTS = 1  # minPhaseBOppositeTests (L118)
MIN_PHASE_B_TRAVERSALS = 2  # minPhaseBTraversals (L119)
PHASE_B_ZONE_FRAC = 0.25  # phaseBZoneFrac (L120)
PHASE_B_RANGE_MIN_ATR = 1.5  # phaseBRangeMinATR (L121)
PHASE_B_RANGE_MAX_ATR = 8.0  # phaseBRangeMaxATR (L122)
PHASE_B_BAD_TEST_COOLDOWN_FACTOR = 2.0  # phaseBBadTestCooldownFactor (L123)
PHASE_B_EDGE_EXPANSION_CAP = 0.15  # phaseBEdgeExpansionCap (L124)
TERMINAL_TEST_MIN_BARS_AFTER_ST = 3  # terminalTestMinBarsAfterST (L125)
TERMINAL_TEST_VOL_RATIO = 0.85  # terminalTestVolRatio (L126)
TERMINAL_TEST_SPREAD_RATIO = 0.85  # terminalTestSpreadRatio (L127)
TERMINAL_TEST_OTHER_MAX_RATIO = 1.05  # terminalTestOtherMaxRatio (L128)

# ── Phase C probes and tests (L130-142) ───────────────────────────────────────────────────
EXCURSION_RECOVERY_BARS = 3  # excursionRecoveryBars (L131)
SPRING_MIN_PEN_ATR = 0.15  # springMinPenATR (L132)
SPRING_MAX_PEN_ATR = 2.5  # springMaxPenATR (L133)
SPRING_CLOSE_MIN = 0.55  # springCloseMin (L134)
UTAD_CLOSE_MAX = 0.45  # utadCloseMax (L135)
SPRING_EFFORT_MAX_MULT = 1.50  # springEffortMaxMult (L136)
EXCURSION_MIN_SCORE = 3  # excursionMinScore (L137)
TEST_TOL_ATR = 1.25  # testTolATR (L138)
TEST_MAX_VOL_RATIO = 0.80  # testMaxVolRatio (L139)
TEST_MAX_SPREAD_RATIO = 0.80  # testMaxSpreadRatio (L140)
TEST_EXTREME_TOLERANCE_ATR = 0.15  # testExtremeToleranceATR (L141)
TEST_MIN_SCORE = 2  # testMinScore (L142)

# ── Phase D and E (L143-165) ──────────────────────────────────────────────────────────────
PHASE_C_TO_D_MIN_BARS = 3  # phaseCToDMinBars (L144)
PHASE_D_MIN_BARS = 4  # phaseDMinBars (L145)
PHASE_D_VALIDATION_MIN = 60  # phaseDValidationMin (L146)
PHASE_D_DOMINANCE_FRAC = 0.65  # phaseDDominanceFrac (L147)
BREAK_ATR = 0.15  # breakATR (L148)
STRENGTH_VOL_MULT = 1.15  # strengthVolMult (L149)
STRENGTH_SPREAD_ATR = 1.15  # strengthSpreadATR (L150)
SOS_CLOSE_MIN = 0.65  # sosCloseMin (L151)
SOW_CLOSE_MAX = 0.35  # sowCloseMax (L152)
STRENGTH_MIN_SCORE = 3  # strengthMinScore (L153)
SOS_MULTI_BAR_LEN = 5  # sosMultiBarLen (L154)
SOS_MULTI_BAR_ATR = 2.0  # sosMultiBarATR (L155)
SOS_MULTI_BAR_EFFORT = 1.10  # sosMultiBarEffort (L156)
LPS_BOUNDARY_ATR = 1.50  # lpsBoundaryATR (L157)
LPS_VOL_MULT = 1.00  # lpsVolMult (L158)
LPS_SPREAD_ATR = 1.00  # lpsSpreadATR (L159)
LPS_MIN_SCORE = 2  # lpsMinScore (L160)
CONFIRM_BARS = 3  # confirmBars (L161)
DIRECT_ACCEPTANCE_BARS = 5  # directAcceptanceBars (L162)
DIRECT_ACCEPTANCE_CONFIDENCE = 75  # directAcceptanceConfidence (L163)
MIN_CONFIDENCE_PHASE_C = 45  # minConfidencePhaseC (L164)
MIN_CONFIDENCE_PHASE_D = 55  # minConfidencePhaseD (L165)

# ── Entries (L167-173) ────────────────────────────────────────────────────────────────────
ENTRY_MIN_CONFIDENCE_CONSERVATIVE = 75  # entryMinConfidenceConservative (L168)
ENTRY_MIN_CONFIDENCE_STANDARD = 60  # entryMinConfidenceStandard (L169)
ENTRY_MIN_CONFIDENCE_AGGRESSIVE = 55  # entryMinConfidenceAggressive (L170)
ENTRY_MIN_TESTS_CONSERVATIVE = 7  # entryMinTestsConservative (L171): readiness out of 9
ENTRY_MIN_TESTS_STANDARD = 6  # entryMinTestsStandard (L172)
ENTRY_MIN_TESTS_AGGRESSIVE = 5  # entryMinTestsAggressive (L173)

# ── Deepest look-backs the engine reads (port bookkeeping, not Pine settings) ─────────────
# ``x[pLen]`` with pLen <= ADAPTIVE_SWING_MAX, and f_priorTrendScore's ``close[e + n]`` with
# e <= 8 and n <= round(10 * 8.0) = 80 (L1117-1119): history kept for 100 bars.
HISTORY_DEPTH = 100
