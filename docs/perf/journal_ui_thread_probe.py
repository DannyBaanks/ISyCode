import asyncio, threading, traceback, collections, atexit, os
from isycode import action_audit
hits = collections.Counter()
orig = action_audit.ActionAuditJournal._append
def _append(self, body):
    if threading.current_thread() is threading.main_thread():
        try:
            asyncio.get_running_loop(); on_loop = True
        except RuntimeError:
            on_loop = False
        if on_loop:
            st = [f for f in traceback.extract_stack()[:-1] if "/isycode/" in f.filename]
            key = " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in reversed(st[-6:]))
            hits[(body.get("kind"), body.get("action"), key)] += 1
    return orig(self, body)
action_audit.ActionAuditJournal._append = _append
@atexit.register
def dump():
    with open(os.environ["PROBE_OUT"], "w") as fh:
        for (k, a, key), n in hits.most_common():
            fh.write(f"{n}\t{k}\t{a}\t{key}\n")
