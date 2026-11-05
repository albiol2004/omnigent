"""Map docs/v21-report.md §1 ported/adapted rows (new sha on trio-v0.21.0rc1-fixes) onto trio-v0.21.0-fixes.
A row maps if HEAD (v0.21.0..HEAD) has a commit whose -x trailer names the row's fixes sha, or names the
first-parent merge of trio-v0.21.0rc1-fixes that brought it in (cherry-pick -m 1 squashes the merge)."""
import re, subprocess, sys
def git(*a): return subprocess.run(["git",*a],capture_output=True,text=True,check=True).stdout
FIX="trio-v0.21.0rc1-fixes"
fp=git("rev-list","--first-parent","--reverse",f"v0.21.0rc1..{FIX}").split()
fpset=set(fp)
trail={}
for rec in git("log","--format=%H%x00%B%x1e","v0.21.0..HEAD").split("\x1e"):
    rec=rec.strip("\n")
    if not rec: continue
    h,b=rec.split("\x00",1)
    for v in re.findall(r"\(cherry picked from commit ([0-9a-f]{40})\)",b): trail.setdefault(v,[]).append(h)
def carrier(full):
    if full in fpset: return full
    for m in fp:  # first first-parent merge containing it
        ps=git("rev-list","--parents","-n1",m).split()[1:]
        if len(ps)>1 and subprocess.run(["git","merge-base","--is-ancestor",full,m]).returncode==0 \
           and subprocess.run(["git","merge-base","--is-ancestor",full,ps[0]]).returncode!=0:
            return m
text=open("docs/v21-report.md").read()
sec=re.search(r"^## 1\..*?(?=^## 2\.)",text,re.S|re.M).group(0)
ok=bad=0; via_merge=0
for line in sec.split("\n"):
    cols=[c.strip() for c in line.strip().strip("|").split("|")]
    if len(cols)!=7 or not re.fullmatch(r"[0-9a-f]{7,40}",cols[1]) or cols[4] not in ("ported","adapted"): continue
    full=git("rev-parse",cols[5]+"^{commit}").strip()
    c=carrier(full)
    hits=trail.get(c,[]) if c else []
    if len(hits)==1 and subprocess.run(["git","merge-base","--is-ancestor",hits[0],"HEAD"]).returncode==0:
        ok+=1; via_merge+= c!=full
        print(f"OK row #{cols[0]} v17 {cols[1]} -> fixes {cols[5]} -> final {hits[0][:10]}" + (f" (via merge {c[:10]})" if c!=full else ""))
    else:
        bad+=1; print(f"FAIL row #{cols[0]} v17 {cols[1]} fixes {cols[5]}: carrier={c and c[:10]} hits={len(hits)}")
# every non-loop first-parent commit of fixes has exactly one pick on final
missing=[]
for c in fp:
    paths=[p for p in git("diff-tree","-m","--first-parent","--no-commit-id","--name-only","-r",c).split() if p]
    if paths and all(p.startswith(("loop/","loop-archive")) for p in paths): continue
    if len(trail.get(c,[]))!=1: missing.append(c[:10])
print(f"REMAP: rows ok={ok} fail={bad} (via merge squash: {via_merge}); fixes first-parent product commits without exactly one pick on final: {len(missing)} {' '.join(missing)}")
sys.exit(1 if bad or missing else 0)
