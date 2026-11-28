import os, sys, time, hashlib, secrets, tempfile, statistics
from pathlib import Path
src=sys.argv[1]; label=sys.argv[2]
sys.path.insert(0, src)
base=Path(tempfile.mkdtemp(dir=os.environ["BENCH_DIR"]))
os.environ["XDG_STATE_HOME"]=str(base/"state")
from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ActionReceipt, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
root=base/"ws"; root.mkdir()
auth=WorkspaceAuthority(root, state_directory=base/"auth")
auth.set_grant("provider.request", enabled=True, network_hosts=["api.example.com"])
gate=ProductActionGate(root, auth, owner_id="provider_network")
def eff(n):
    r=ActionRequest("provider.request", root, "api.example.com", {"url":"https://api.example.com/v1","n":n}, execution_owner="provider_network")
    gate.authorize(r)
    gate.persist_receipt(r, ActionReceipt("rcpt_"+secrets.token_hex(8), r.action_id, r.digest, "ALLOW","SUCCESS", hashlib.sha256(str(n).encode()).hexdigest()))
n=0
while gate.audit.path.stat().st_size < 3_900_000 if gate.audit.path.exists() else True:
    eff(n); n+=1
    if n>20000: break
cpu=[]; wall=[]
for i in range(40):
    t=time.process_time(); w=time.perf_counter(); eff(n+i); cpu.append(time.process_time()-t); wall.append(time.perf_counter()-w)
print(f"{label}: segment={gate.audit.path.stat().st_size/1e6:.2f}MB per-action cpu median={1000*statistics.median(cpu):.1f}ms wall median={1000*statistics.median(wall):.1f}ms p90={1000*sorted(wall)[35]:.1f}ms")
