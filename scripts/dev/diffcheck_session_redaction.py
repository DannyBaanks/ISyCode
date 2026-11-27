"""Differential check old vs new redaction/validation. argv: old src, new src, sessions root."""
import importlib, json, random, sys
from pathlib import Path
def load(src):
    for m in [k for k in sys.modules if k.startswith("isycode")]: del sys.modules[m]
    sys.path.insert(0, src)
    cs = importlib.import_module("isycode.chat_sessions"); th = importlib.import_module("isycode.tool_history")
    sys.path.pop(0); return cs.ChatSessionStore, th
OS, OT = load(sys.argv[1]); NS, NT = load(sys.argv[2])
strings, states = [], []
def walk(v):
    if isinstance(v, str): strings.append(v)
    elif isinstance(v, dict): [walk(k) or walk(x) for k, x in v.items()]
    elif isinstance(v, list): [walk(x) for x in v]
for f in Path(sys.argv[3]).glob("*/*.json"):
    d = json.loads(f.read_bytes()); walk(d); states.append(d.get("state", {}))
rnd = random.Random(7)
atoms = ["Bearer ", "bearer abcdefghijklmnop123", "api_key", "API-KEY", "Authorization: ", "sk-", "SK-abcdefghijk",
         "sk-abc_def-12345678", "secret", "password=", "'x y'", '"q\\"z"', ":", "=", " ", ",", ";", "{", "}", "[", "]",
         "refresh_token", "access-token", "\"", "'", "\n", "ñ", "abc", "12345678901234", "{\"secret\":\"v\"}", "ſecret", "ſk-abcdefghij", "pasſword", "api_\u212aey", "authorızation", "AUTHORİZATION", "\\u0073ecret", "{\"a\":\"\\u0073k-abcdefghij\"}", "{\"pa\\u0073sword\":1}"]
fuzz = ["".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 12))) for _ in range(60000)]
def doc(d=0):
    r = rnd.random()
    if d > 3 or r < 0.3: return "".join(rnd.choice(atoms) for _ in range(rnd.randint(0, 5)))
    if r < 0.4: return rnd.choice([1, 2.5, None, True, float("nan")])
    if r < 0.7: return [doc(d + 1) for _ in range(rnd.randint(0, 4))]
    return {"".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 3))): doc(d + 1) for _ in range(rnd.randint(0, 4))}
for _ in range(20000):
    fuzz.append(json.dumps(doc(), ensure_ascii=rnd.random() < 0.5))
for depth in (50, 400, 900, 990, 1000, 1100, 3000, 10000):
    for leaf in ('"x"', '"secret"', '{"api_key": NaN}', '"\\u0073k-abcdefghij"'):
        fuzz.append("[" * depth + leaf + "]" * depth)
        fuzz.append('{"a":' * depth + leaf + "}" * depth)
bad = 0
for s in strings + fuzz:
    if OS._sanitize_text(s) != NS._sanitize_text(s): bad += 1
    if OT.sanitize_historical_text(s) != NT.sanitize_historical_text(s): bad += 1
def outcome(f, st):
    try: return json.dumps(f(st), sort_keys=True)
    except Exception as e: return "ERR:" + type(e).__name__ + str(e)
for st in states:
    if outcome(OS.validate_state, st) != outcome(NS.validate_state, st): bad += 1
print(f"real_strings={len(strings)} fuzz={len(fuzz)} states={len(states)} mismatches={bad}")
sys.exit(1 if bad else 0)
