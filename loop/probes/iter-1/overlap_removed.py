"""Evaluator probe (second path for DoD 2): lines each upstream PR added that the port's
v0.17.0..HEAD diff removes. Run from the repo root at the pin."""
import subprocess
def g(*a): return subprocess.run(["git",*a],capture_output=True,text=True).stdout
prs={"9048":"021d19951","9008":"06a055ac1","9005":"f651b5d6a","8672":"8bb13323f","8572":"61d96f74b","8745":"56272dfd7","8761":"ee3ca7cca","8516":"a16334f78","8523":"7cbad8613","9025":"106e2260b","9020":"6f9f8f838","8795":"1c0190294"}
removed={}; cur=None
for l in g("diff","-M","--no-color","v0.17.0","HEAD").splitlines():
    if l.startswith("--- a/"): cur=l[6:]
    elif l.startswith("--- /dev/null"): cur=None
    elif l.startswith("-") and not l.startswith("---") and cur: removed.setdefault(cur,set()).add(l[1:].strip())
for pr,c in prs.items():
    added={}; f=None
    for l in g("show","--no-color","--format=",c).splitlines():
        if l.startswith("+++ b/"): f=l[6:]
        elif l.startswith("+") and not l.startswith("+++") and f:
            s=l[1:].strip()
            if len(s)>8: added.setdefault(f,set()).add(s)
    hits=[(f,s) for f,ss in added.items() for s in ss if s in removed.get(f,())]
    print(f"#{pr} {c}: lines={sum(map(len,added.values()))} removed_by_port={len(hits)}")
