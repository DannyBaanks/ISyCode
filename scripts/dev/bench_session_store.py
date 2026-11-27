"""Benchmark ChatSessionStore on a fresh copy of real sessions. argv: repo src, source dir, work dir."""
import shutil, statistics, sys, time
from pathlib import Path
src, source, work = sys.argv[1:4]
sys.path.insert(0, src)
from isycode.chat_sessions import ChatSessionStore
w = Path(work); shutil.rmtree(w, ignore_errors=True); shutil.copytree(source, w); w.chmod(0o700)
CPU = []
def t(f):
    a = time.perf_counter(); c = time.process_time(); r = f()
    CPU.append((time.process_time() - c) * 1e3); return (time.perf_counter() - a) * 1e3, r
st = ChatSessionStore(w)
cold, L = t(st.list_sessions); cold_cpu = CPU[-1]
warm = statistics.median(t(st.list_sessions)[0] for _ in range(3))
big = max(L, key=lambda s: sum(len(m["content"]) for m in s.messages) + len(str(s.state)))
CPU.clear()
app = statistics.median(t(lambda: st.append(big.session_id, "user", "hola " * 20))[0] for _ in range(7))
app_cpu = statistics.median(CPU)
srch = statistics.median(t(lambda: st.search("zig"))[0] for _ in range(3))
print(f"sessions={len(L)} list_cold={cold:.0f}ms(cpu {cold_cpu:.0f}ms) list_warm={warm:.0f}ms append={app:.0f}ms(cpu {app_cpu:.0f}ms) search={srch:.0f}ms")
