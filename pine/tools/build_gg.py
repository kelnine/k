#!/usr/bin/env python3
"""Build the GG Charts edition of AIO Trading Suite [K] from the main script.

GG Charts refuses scripts over 64 KB. This keeps every calculation of the main
script and only:
  * removes the Volume Profile module (off by default; heaviest drawing code),
  * removes the alert() delivery block and its section-9 toggles
    (every alertcondition() is kept),
  * strips comments, tooltips and status-line display arguments,
  * joins wrapped lines.
Run:  python3 pine/tools/build_gg.py
"""
import pathlib, re

root = pathlib.Path(__file__).resolve().parent.parent
src = (root / "AIO_Trading_Suite_K_v1.0.pine").read_text()
lines = src.split("\n")

def cut(lines, start_pred, end_pred):
    s = next(i for i, l in enumerate(lines) if start_pred(l))
    e = next(i for i in range(s + 1, len(lines)) if end_pred(lines[i]))
    return lines[:s] + lines[e:]

# Volume profile inputs (showVP .. vaCol) and section (header before `type Profile` .. 4H S/D header)
lines = cut(lines, lambda l: l.startswith("showVP ="), lambda l: l.startswith("// -- 4"))
i = next(i for i, l in enumerate(lines) if l.startswith("type Profile"))
start = i - 3  # three-line section header above `type Profile`
end = next(j for j in range(i, len(lines)) if lines[j].startswith("// 7 - 4H SUPPLY")) - 1
lines = lines[:start] + lines[end:]
# alert() toggles and alert() block
lines = cut(lines, lambda l: l.startswith("alMtf ="), lambda l: l.startswith("// -- 10"))
k = next(i for i, l in enumerate(lines) if l == "if barstate.isconfirmed" and "string tk" in lines[i + 1])
lines = lines[:k]
for name in ("const string G3 ", "const string G9 "):
    lines = [l for l in lines if not l.startswith(name)]

t = "\n".join(lines)
t = re.sub(r',\s*tooltip = "[^"]*"', "", t)
t = t.replace(", display = display.none", "").replace(", display = display.all - display.status_line", "")
t = t.replace('indicator("AIO Trading Suite [K] - Performance Edition"', 'indicator("AIO Trading Suite [K] - GG Charts Edition"')

out = []
for l in t.split("\n"):
    st = l.strip()
    if st.startswith("//") and not st.startswith("//@version"):
        continue
    code, in_s = "", False
    for j, c in enumerate(l):
        if c == '"':
            in_s = not in_s
        if not in_s and l[j:j + 2] == "//":
            break
        code += c
    code = code.rstrip()
    if not code:
        continue
    ind = len(code) - len(code.lstrip(" "))
    if ind % 4 and out:          # wrapped continuation line -> join
        out[-1] += " " + code.strip()
    else:
        out.append(code)

PUNCT = set("=:,+-*/%?()[]!")

def compact(line):
    """Drop optional spaces next to operators/commas, outside string literals."""
    ind = len(line) - len(line.lstrip(" "))
    body, res, in_s = line[ind:], [], False
    for j, c in enumerate(body):
        if c == '"':
            in_s = not in_s
        if c == " " and not in_s:
            prev = res[-1] if res else ""
            nxt = body[j + 1] if j + 1 < len(body) else ""
            keyword_paren = nxt in "([" and prev.isalnum()   # keep `not (`, `and (`
            if (prev in PUNCT or nxt in PUNCT) and not keyword_paren:
                continue
        res.append(c)
    return line[:ind] + "".join(res)

out = [compact(l) for l in out]

header = ("//@version=6\n"
          "// AIO Trading Suite [K] - GG Charts Edition (generated from AIO_Trading_Suite_K_v1.0.pine by tools/build_gg.py)\n"
          "// Same calculations as the TradingView build, minus the Volume Profile module and the alert() block.\n")
body = "\n".join(l for l in out if not l.startswith("//@version")) + "\n"
dst = root / "AIO_Trading_Suite_K_GGCharts.pine"
dst.write_text(header + body)
print(dst.name, len((header + body).encode()), "bytes")
