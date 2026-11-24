#!/usr/bin/env python3
"""Static checks for the Multi-Session ORB Pro Pine Script files.

This is NOT a Pine compiler. TradingView's compiler is closed source, so the only
authoritative check is pasting the script into the Pine Editor. What this tool does:

  1. Syntax: parses each file with `pynescript` (an open-source Pine grammar).
  2. Names: every identifier must be defined before use (Pine is top-down), in an
     enclosing scope, or be a known built-in.
  3. Built-ins: every `namespace.member` reference must be in the whitelist below
     (catches typos such as `str.fromat`). The whitelist was written by hand from the
     Pine v6 reference manual, so it can itself be wrong or incomplete.
  4. Keyword arguments of the built-in functions used here are checked against their
     documented parameter names (catches e.g. `label.new(textsize=...)`).
  5. User-defined types: `obj.field` on a variable with a declared UDT type must be a
     real field; `Type.new(field = ...)` must use real fields.
  6. User functions: call arity / keyword names must match the definition.
  7. na comparisons: `==` / `!=` against a UDT field that can be `na` (default `na`, or
     no default) is flagged unless the same `or` expression checks `na(field)`.
     In Pine any comparison with na evaluates to false, so `x != s.winStart` is
     false — not true — while `winStart` is still na.

Usage:  python3 pine/tools/lint_pine.py pine/*.pine
Needs:  pip install pynescript   (parsing a large file can take a few minutes)
"""
from __future__ import annotations

import multiprocessing
import sys
import time

try:
    from pynescript.ast import parse
    from pynescript.ast import node as N
except ImportError:  # pragma: no cover
    print("pynescript is not installed: pip install pynescript")
    sys.exit(2)

# ───────────────────────── built-in knowledge (Pine v6) ─────────────────────────
PLAIN_BUILTINS = {
    # variables
    "open", "high", "low", "close", "volume", "time", "time_close", "bar_index", "na",
    "true", "false", "timenow", "hl2", "hlc3", "ohlc4", "last_bar_index", "last_bar_time",
    # functions
    "nz", "plot", "plotshape", "alert", "alertcondition", "indicator", "strategy",
    "timestamp", "year", "month", "dayofmonth", "dayofweek", "hour", "minute", "second",
    "int", "float", "bool", "string", "fill", "hline", "bgcolor", "barcolor", "fixnan",
    # types usable as names
    "color", "line", "label", "box", "table", "array", "map",
}

NAMESPACES = {
    "input": "bool int float string color timeframe session text_area time source symbol price enum",
    "str": "tostring format format_time contains startswith endswith substring replace_all replace "
           "split length lower upper tonumber pos match repeat trim",
    "math": "max min abs floor ceil round round_to_mintick log log10 pow sqrt sign sum avg exp",
    "ta": "ema sma rma rsi atr tr crossover crossunder highest lowest valuewhen change wma vwma",
    "request": "security",
    "ticker": "standard new modify heikinashi",
    "syminfo": "ticker tickerid prefix type mintick pointvalue currency timezone session "
               "description basecurrency root",
    "timeframe": "period isintraday isticks isseconds isminutes isdaily isweekly ismonthly isdwm "
                 "multiplier in_seconds main_period",
    "chart": "is_standard is_heikinashi is_renko is_kagi is_pnf is_linebreak is_range",
    "barstate": "isconfirmed islast isfirst isrealtime ishistory isnew islastconfirmedhistory",
    "barmerge": "lookahead_on lookahead_off gaps_on gaps_off",
    "display": "none all data_window status_line pane price_scale",
    "format": "mintick price percent volume inherit",
    "position": "top_left top_center top_right middle_left middle_center middle_right "
                "bottom_left bottom_center bottom_right",
    "size": "auto tiny small normal large huge",
    "text": "align_left align_center align_right align_top align_bottom wrap_auto wrap_none",
    "line": "new delete set_x1 set_x2 set_y1 set_y2 set_xy1 set_xy2 set_color set_style set_width "
            "set_extend get_price get_x1 get_x2 get_y1 get_y2 style_solid style_dotted style_dashed "
            "style_arrow_left style_arrow_right style_arrow_both all",
    "label": "new delete set_x set_y set_xy set_text set_color set_textcolor set_style set_size "
             "set_tooltip set_yloc set_xloc style_none style_xcross style_cross style_triangleup "
             "style_triangledown style_flag style_circle style_arrowup style_arrowdown "
             "style_label_up style_label_down style_label_left style_label_right "
             "style_label_lower_left style_label_lower_right style_label_upper_left "
             "style_label_upper_right style_label_center style_square style_diamond all",
    "box": "new delete set_left set_right set_top set_bottom set_lefttop set_rightbottom set_bgcolor "
           "set_border_color set_border_style set_border_width set_extend set_text set_text_color "
           "set_text_size set_text_halign set_text_valign get_top get_bottom get_left get_right all",
    "table": "new cell clear merge_cells delete cell_set_text cell_set_bgcolor cell_set_text_color all",
    "extend": "none right left both",
    "xloc": "bar_index bar_time",
    "yloc": "price abovebar belowbar",
    "color": "new rgb r g b t white black red green blue gray silver orange yellow aqua lime "
             "maroon navy olive purple teal fuchsia",
    "order": "ascending descending",
    "array": "new from",
    "map": "new",
    "alert": "freq_all freq_once_per_bar freq_once_per_bar_close",
    "plot": "style_line style_linebr style_stepline style_histogram style_cross style_circles "
            "style_area style_columns",
    "shape": "triangleup triangledown circle cross xcross diamond square flag labelup labeldown "
             "arrowup arrowdown",
    "location": "abovebar belowbar top bottom absolute",
    "currency": "NONE USD EUR USDT",
    "dayofweek": "sunday monday tuesday wednesday thursday friday saturday",
    "session": "regular extended ismarket ispremarket ispostmarket isfirstbar islastbar",
    "strategy": "entry exit close close_all cancel cancel_all order long short position_size "
                "position_avg_price equity netprofit grossprofit grossloss max_drawdown wintrades "
                "losstrades eventrades closedtrades opentrades initial_capital fixed cash "
                "percent_of_equity openprofit",
    "strategy.commission": "percent cash_per_contract cash_per_order",
    "strategy.closedtrades": "entry_id exit_id profit size entry_price exit_price commission "
                             "entry_bar_index exit_bar_index entry_time exit_time entry_comment "
                             "exit_comment max_runup max_drawdown",
    "strategy.opentrades": "entry_id profit size entry_price commission entry_bar_index entry_time "
                           "entry_comment",
}
NAMESPACES = {k: set(v.split()) for k, v in NAMESPACES.items()}

COLLECTION_METHODS = {
    "push", "get", "set", "size", "shift", "pop", "clear", "sort_indices", "sort", "first", "last",
    "contains", "put", "remove", "keys", "values", "includes", "indexof", "unshift", "insert",
    "copy", "join", "sum", "max", "min", "avg",
}

COMMON_INPUT = ["tooltip", "inline", "group", "confirm", "display", "active"]
SIGS = {
    "input.bool": ["defval", "title", *COMMON_INPUT],
    "input.int": ["defval", "title", "minval", "maxval", "step", "options", *COMMON_INPUT],
    "input.float": ["defval", "title", "minval", "maxval", "step", "options", *COMMON_INPUT],
    "input.string": ["defval", "title", "options", *COMMON_INPUT],
    "input.color": ["defval", "title", *COMMON_INPUT],
    "input.timeframe": ["defval", "title", "options", *COMMON_INPUT],
    "input.text_area": ["defval", "title", "tooltip", "group", "confirm", "display", "active"],
    "input.time": ["defval", "title", *COMMON_INPUT],
    "indicator": ["title", "shorttitle", "overlay", "format", "precision", "scale", "max_bars_back",
                  "timeframe", "timeframe_gaps", "explicit_plot_zorder", "max_lines_count",
                  "max_labels_count", "max_boxes_count", "calc_bars_count", "max_polylines_count",
                  "dynamic_requests", "behind_chart"],
    "strategy": ["title", "shorttitle", "overlay", "format", "precision", "scale", "pyramiding",
                 "calc_on_order_fills", "calc_on_every_tick", "max_bars_back",
                 "backtest_fill_limits_assumption", "default_qty_type", "default_qty_value",
                 "initial_capital", "currency", "slippage", "commission_type", "commission_value",
                 "process_orders_on_close", "close_entries_rule", "margin_long", "margin_short",
                 "explicit_plot_zorder", "max_lines_count", "max_labels_count", "max_boxes_count",
                 "calc_bars_count", "risk_free_rate", "use_bar_magnifier",
                 "fill_orders_on_standard_ohlc", "max_polylines_count", "dynamic_requests",
                 "behind_chart"],
    "request.security": ["symbol", "timeframe", "expression", "gaps", "lookahead",
                         "ignore_invalid_symbol", "currency", "calc_bars_count"],
    "box.new": ["left", "top", "right", "bottom", "border_color", "border_width", "border_style",
                "extend", "xloc", "bgcolor", "text", "text_size", "text_color", "text_halign",
                "text_valign", "text_wrap", "text_font_family", "force_overlay", "text_formatting"],
    "line.new": ["x1", "y1", "x2", "y2", "xloc", "extend", "color", "style", "width",
                 "force_overlay"],
    "label.new": ["x", "y", "text", "xloc", "yloc", "color", "style", "textcolor", "size",
                  "textalign", "tooltip", "text_font_family", "force_overlay", "text_formatting"],
    "table.new": ["position", "columns", "rows", "bgcolor", "frame_color", "frame_width",
                  "border_color", "border_width", "force_overlay"],
    "table.cell": ["table_id", "column", "row", "text", "width", "height", "text_color",
                   "text_halign", "text_valign", "text_size", "bgcolor", "tooltip",
                   "text_font_family", "text_formatting"],
    "table.merge_cells": ["table_id", "start_column", "start_row", "end_column", "end_row"],
    "table.clear": ["table_id", "start_column", "start_row", "end_column", "end_row"],
    "plot": ["series", "title", "color", "linewidth", "style", "trackprice", "histbase", "offset",
             "join", "editable", "show_last", "display", "format", "precision", "force_overlay",
             "linestyle"],
    "plotshape": ["series", "title", "style", "location", "color", "offset", "text", "textcolor",
                  "editable", "size", "show_last", "display", "format", "precision",
                  "force_overlay"],
    "alertcondition": ["condition", "title", "message"],
    "alert": ["message", "freq"],
    "strategy.entry": ["id", "direction", "qty", "limit", "stop", "oca_name", "oca_type", "comment",
                       "alert_message", "disable_alert"],
    "strategy.exit": ["id", "from_entry", "qty", "qty_percent", "profit", "limit", "loss", "stop",
                      "trail_price", "trail_points", "trail_offset", "oca_name", "comment",
                      "comment_profit", "comment_loss", "comment_trailing", "alert_message",
                      "alert_profit", "alert_loss", "alert_trailing", "disable_alert"],
    "strategy.close": ["id", "comment", "qty", "qty_percent", "alert_message", "immediately",
                       "disable_alert"],
    "str.tostring": ["value", "format"],
    "str.format_time": ["time", "format", "timezone"],
    "color.new": ["color", "transp"],
}


def split_top_level(src):
    """Split a script into independently parseable top-level chunks.

    ANTLR's Python runtime is very slow on long inputs, so each top-level statement
    (a line starting in column 0 plus its indented / continuation lines) is parsed on
    its own. Comment-only and blank lines are attached to the following chunk.
    """
    lines = src.split("\n")
    chunks, cur, cur_start = [], [], 0
    for i, line in enumerate(lines):
        starts_new = bool(line) and not line[0].isspace() and not line.startswith("//")
        if starts_new and any(l.strip() and not l.lstrip().startswith("//") for l in cur):
            chunks.append((cur_start, "\n".join(cur)))
            cur, cur_start = [], i
        if not cur:
            cur_start = i
        cur.append(line)
    if cur:
        chunks.append((cur_start, "\n".join(cur)))
    return chunks


def _parse_chunk(item):
    start, chunk = item
    # pad with newlines so reported line numbers match the real file
    try:
        return parse("\n" * start + chunk).body
    except SyntaxError as exc:
        return str(exc)


class Scope:
    def __init__(self, parent=None, kind="block"):
        self.parent = parent
        self.kind = kind
        self.names: dict[str, str | None] = {}

    def lookup(self, name):
        s = self
        while s is not None:
            if name in s.names:
                return True, s.names[name]
            s = s.parent
        return False, None


def dotted(expr):
    """Return 'a.b.c' for Name/Attribute chains, else None."""
    parts = []
    while isinstance(expr, N.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, N.Name):
        parts.append(expr.id)
        return ".".join(reversed(parts))
    return None


def type_name(t):
    if t is None:
        return None
    if isinstance(t, N.Name):
        return t.id
    if isinstance(t, N.Qualify):
        return type_name(t.value)
    if isinstance(t, N.Specialize):
        return dotted(t.value)
    return dotted(t)


class Linter:
    def __init__(self, path):
        self.path = path
        self.errors: list[str] = []
        self.udts: dict[str, dict[str, str | None]] = {}
        self.funcs: dict[str, list[tuple[str, bool]]] = {}
        self.na_fields: dict[str, set[str]] = {}
        self.guarded: list[set[str]] = []

    def err(self, node, msg):
        line = getattr(node, "lineno", "?")
        self.errors.append(f"{self.path}:{line}: {msg}")

    # ── type inference (only what is needed for UDT field checks) ──
    def type_of(self, expr, scope):
        if isinstance(expr, N.Name):
            return scope.lookup(expr.id)[1]
        if isinstance(expr, N.Attribute):
            base = self.type_of(expr.value, scope)
            if base in self.udts:
                return self.udts[base].get(expr.attr)
            return None
        if isinstance(expr, N.Call) and isinstance(expr.func, N.Attribute) and expr.func.attr == "new":
            base = dotted(expr.func.value)
            if base in self.udts:
                return base
        return None

    # ── declarations ──
    def declare(self, target, scope, tname=None):
        if isinstance(target, N.Name):
            scope.names[target.id] = tname
        elif isinstance(target, N.Tuple):
            for e in target.elts:
                self.declare(e, scope)

    # ── visitors ──
    def run(self, src):
        t0 = time.time()
        chunks = split_top_level(src)
        with multiprocessing.Pool() as pool:
            results = pool.map(_parse_chunk, chunks)
        body = []
        for (start, _), res in zip(chunks, results):
            if isinstance(res, str):
                raise SyntaxError(f"chunk starting at line {start + 1}: {res}")
            body.extend(res)
        print(f"  parsed {self.path} in {time.time() - t0:.0f}s")
        g = Scope(kind="global")
        self.block(body, g)

    def block(self, stmts, scope):
        for st in stmts:
            self.stmt(st, scope)

    def stmt(self, st, scope):
        if isinstance(st, N.TypeDef):
            fields = {}
            na_f = set()
            for f in st.body:
                if isinstance(f, N.Assign) and isinstance(f.target, N.Name):
                    fields[f.target.id] = type_name(f.type)
                    no_default_na = f.value is None and type_name(f.type) in ("int", "float", "string", "color")
                    if no_default_na or (isinstance(f.value, N.Name) and f.value.id == "na"):
                        na_f.add(f.target.id)
                    if f.value is not None:
                        self.expr(f.value, scope)
            self.udts[st.name] = fields
            self.na_fields[st.name] = na_f
            scope.names[st.name] = None
        elif isinstance(st, N.FunctionDef):
            params = [(p.name, p.default is not None) for p in st.args]
            self.funcs[st.name] = params
            scope.names[st.name] = None
            fs = Scope(scope, kind="function")
            for p in st.args:
                fs.names[p.name] = type_name(p.type)
                if p.default is not None:
                    self.expr(p.default, scope)
            self.block(st.body, fs)
        elif isinstance(st, N.Assign):
            if st.value is not None:
                self.expr(st.value, scope)
            tname = type_name(st.type) or (self.type_of(st.value, scope) if st.value is not None else None)
            if isinstance(st.target, N.Name) and st.target.id in scope.names and scope.kind != "global":
                self.err(st, f"'{st.target.id}' declared twice in the same scope")
            self.declare(st.target, scope, tname)
        elif isinstance(st, (N.ReAssign, N.AugAssign)):
            self.expr(st.value, scope)
            self.expr(st.target, scope, store=True)
        elif isinstance(st, N.Expr):
            self.expr(st.value, scope)
        elif isinstance(st, (N.Break, N.Continue)):
            pass
        else:
            self.err(st, f"unhandled statement {type(st).__name__}")

    def expr(self, e, scope, store=False):
        if e is None:
            return
        if isinstance(e, N.Name):
            found, _ = scope.lookup(e.id)
            if not found and e.id not in PLAIN_BUILTINS and e.id not in NAMESPACES:
                self.err(e, f"undefined name '{e.id}'")
            return
        if isinstance(e, N.Attribute):
            d = dotted(e)
            if d is not None:
                root = d.split(".")[0]
                found, _ = scope.lookup(root)
                if not found:
                    ns, member = d.rsplit(".", 1)
                    if ns in NAMESPACES:
                        if member not in NAMESPACES[ns] and d not in NAMESPACES:
                            self.err(e, f"unknown built-in '{d}'")
                        return
                    if root in NAMESPACES or root in PLAIN_BUILTINS:
                        # e.g. strategy.commission.percent handled above; anything else unknown
                        if d not in NAMESPACES:
                            self.err(e, f"unknown built-in '{d}'")
                        return
                    if root in self.udts:
                        return
                    self.err(e, f"undefined name '{root}'")
                    return
            base_t = self.type_of(e.value, scope)
            if base_t in self.udts and e.attr not in self.udts[base_t] and e.attr not in COLLECTION_METHODS:
                self.err(e, f"type '{base_t}' has no field '{e.attr}'")
            self.expr(e.value, scope)
            return
        if isinstance(e, N.Call):
            self.call(e, scope)
            return
        if isinstance(e, N.Constant):
            return
        if isinstance(e, N.BinOp):
            self.expr(e.left, scope)
            self.expr(e.right, scope)
        elif isinstance(e, N.BoolOp):
            guards = set()
            if isinstance(e.op, N.Or):
                for v in e.values:
                    if isinstance(v, N.Call) and dotted(v.func) == "na" and v.args:
                        d = dotted(v.args[0].value)
                        if d:
                            guards.add(d)
            self.guarded.append(guards)
            for v in e.values:
                self.expr(v, scope)
            self.guarded.pop()
        elif isinstance(e, N.UnaryOp):
            self.expr(e.operand, scope)
        elif isinstance(e, N.Compare):
            if any(isinstance(op, (N.Eq, N.NotEq)) for op in e.ops):
                for operand in [e.left, *e.comparators]:
                    if isinstance(operand, N.Attribute):
                        base_t = self.type_of(operand.value, scope)
                        d = dotted(operand)
                        if (base_t in self.na_fields and operand.attr in self.na_fields[base_t]
                                and not any(d in g for g in self.guarded)):
                            self.err(e, f"'==' / '!=' with '{d}', which can be na: Pine evaluates the "
                                        f"comparison as false while it is na — add 'na({d}) or …'")
            self.expr(e.left, scope)
            for c in e.comparators:
                self.expr(c, scope)
        elif isinstance(e, N.Conditional):
            self.expr(e.test, scope)
            self.expr(e.body, scope)
            self.expr(e.orelse, scope)
        elif isinstance(e, N.Subscript):
            self.expr(e.value, scope)
            self.expr(e.slice, scope)
        elif isinstance(e, N.Tuple):
            for x in e.elts:
                self.expr(x, scope)
        elif isinstance(e, N.If):
            self.expr(e.test, scope)
            self.block(e.body, Scope(scope))
            self.block(e.orelse, Scope(scope))
        elif isinstance(e, N.ForTo):
            self.expr(e.start, scope)
            self.expr(e.end, scope)
            self.expr(e.step, scope)
            fs = Scope(scope)
            self.declare(e.target, fs)
            self.block(e.body, fs)
        elif isinstance(e, N.ForIn):
            self.expr(e.iter, scope)
            fs = Scope(scope)
            self.declare(e.target, fs)
            self.block(e.body, fs)
        elif isinstance(e, N.While):
            self.expr(e.test, scope)
            self.block(e.body, Scope(scope))
        elif isinstance(e, N.Switch):
            self.expr(e.subject, scope)
            for case in e.cases:
                self.expr(case.pattern, scope)
                self.block(case.body, Scope(scope))
        elif isinstance(e, (N.Specialize, N.Qualify)):
            pass
        else:
            self.err(e, f"unhandled expression {type(e).__name__}")

    def call(self, e, scope):
        f = e.func
        name = None
        if isinstance(f, N.Specialize):
            name = dotted(f.value)
        else:
            name = dotted(f)
        kwargs = [a.name for a in e.args if a.name]
        npos = sum(1 for a in e.args if not a.name)
        for a in e.args:
            self.expr(a.value, scope)
        if isinstance(f, N.Specialize):
            if name not in ("array.new", "map.new"):
                self.err(e, f"unexpected template call '{name}'")
            return
        if name is None:
            # method call on an expression result, e.g. A_DR.get(i).cur
            if isinstance(f, N.Attribute):
                self.expr(f.value, scope)
                if f.attr not in COLLECTION_METHODS:
                    self.err(e, f"unknown method '.{f.attr}()'")
            return
        root = name.split(".")[0]
        found, _ = scope.lookup(root)
        if "." not in name:
            if name in self.funcs:
                params = self.funcs[name]
                pnames = [p for p, _ in params]
                required = sum(1 for _, has_def in params if not has_def)
                if npos + len(kwargs) < required or npos + len(kwargs) > len(params):
                    self.err(e, f"'{name}' expects {required}..{len(params)} args, got {npos + len(kwargs)}")
                for k in kwargs:
                    if k not in pnames:
                        self.err(e, f"'{name}' has no parameter '{k}'")
            elif not found and name not in PLAIN_BUILTINS:
                self.err(e, f"undefined function '{name}'")
            elif name in SIGS:
                self.check_kwargs(e, name, kwargs)
            return
        if found and root not in self.udts:
            # method call on a user variable (array / map) or field access chain
            obj, meth = name.rsplit(".", 1)
            obj_t = self.type_of(f.value, scope) if isinstance(f, N.Attribute) else None
            if obj_t in self.udts and meth not in self.udts[obj_t] and meth not in COLLECTION_METHODS:
                self.err(e, f"type '{obj_t}' has no field / method '{meth}'")
            elif obj_t not in self.udts and meth not in COLLECTION_METHODS:
                self.err(e, f"unknown method '.{meth}()' on '{obj}'")
            self.expr(f.value, scope)
            return
        if root in self.udts:
            ns, member = name.rsplit(".", 1)
            if member != "new":
                self.err(e, f"unknown UDT call '{name}'")
            fields = self.udts[root]
            for k in kwargs:
                if k not in fields:
                    self.err(e, f"type '{root}' has no field '{k}'")
            if npos > len(fields):
                self.err(e, f"too many positional fields for '{root}.new'")
            return
        ns, member = name.rsplit(".", 1)
        if ns not in NAMESPACES or member not in NAMESPACES[ns]:
            self.err(e, f"unknown built-in function '{name}'")
            return
        if name in SIGS:
            self.check_kwargs(e, name, kwargs)

    def check_kwargs(self, e, name, kwargs):
        allowed = SIGS[name]
        for k in kwargs:
            if k not in allowed:
                self.err(e, f"'{name}' has no parameter '{k}'")


def main(paths):
    total = 0
    for p in paths:
        src = open(p, encoding="utf-8").read()
        if not src.startswith("//@version=6"):
            print(f"{p}: first line must be //@version=6")
            total += 1
        lt = Linter(p)
        try:
            lt.run(src)
        except SyntaxError as exc:
            print(f"{p}: SYNTAX ERROR: {exc}")
            total += 1
            continue
        for msg in lt.errors:
            print(msg)
        total += len(lt.errors)
        print(f"  {p}: {len(lt.errors)} issue(s), {len(lt.udts)} types, {len(lt.funcs)} functions")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
