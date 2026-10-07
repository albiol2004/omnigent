"""Evaluator probe (DoD 1): every ported/adapted row of docs/v17-report.md -> new sha carries
`cherry picked from commit <full v16 sha>` and is an ancestor of HEAD."""
import subprocess,re
rows=[l for l in open('docs/v17-report.md') if re.match(r'\| \d+ \| [0-9a-f]{9} ',l)]
bad=[];c={}
for l in rows:
    f=[x.strip() for x in l.strip().strip('|').split('|')]
    v16,disp,new=f[1],f[4],f[5]; c[disp]=c.get(disp,0)+1
    if disp in('ported','adapted'):
        full=subprocess.run(['git','rev-parse',v16],capture_output=True,text=True).stdout.strip()
        msg=subprocess.run(['git','log','-1','--format=%B',new],capture_output=True,text=True).stdout
        anc=subprocess.run(['git','merge-base','--is-ancestor',new,'HEAD']).returncode
        if f'cherry picked from commit {full}' not in msg or anc: bad.append((v16,new))
print(len(rows),c,'bad=',bad)
