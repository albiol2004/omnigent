#!/usr/bin/env python3
"""Compare two v21 focused-suite records (baseline vs after-port).

Usage: python3 -I scripts/v21_compare_suites.py BASELINE AFTER [--perfile PATH]

Regression = a FAILED/ERROR node id in AFTER that is not in BASELINE, or an
AFTER group whose summary is TIMEOUT / PYTEST-TIMEOUT-HANG / NO-SUMMARY (or
that is missing), unless BASELINE has the same outcome class for the group AND
the per-file record (PATH, default docs/v21-evidence/after-port-perfile.txt,
used only if it exists; records `== record: pristine ==` / `== record:
tip ==`, optionally `pristine-capsys` / `tip-capsys`) shows that every file
hanging at the tip also hangs on pristine, every failing id at the tip also
fails on pristine/baseline, and every file absent on pristine (fork-added)
passes at the tip.
Exit 0 iff REGRESSIONS == 0; exit 2 on unreadable/incomplete input.
"""

import os
import re
import sys

BAD = {"timeout", "hang", "nosummary", "missing"}


def klass(summary):
    if summary is None:
        return "missing"
    if summary.startswith("TIMEOUT"):
        return "timeout"
    if summary.startswith("PYTEST-TIMEOUT-HANG"):
        return "hang"
    if summary.startswith("NO-SUMMARY"):
        return "nosummary"
    return "ok"


def parse_record(lines):
    """Parse one runner record -> dict(rev, notes, done, sections[key])."""
    rec = {"rev": None, "notes": [], "done": False, "sections": {}, "order": []}
    cur = None
    for ln in lines:
        ln = ln.rstrip("\n")
        if ln.startswith("rev: "):
            rec["rev"] = ln[5:].strip()
        elif ln.startswith("note:"):
            rec["notes"].append(ln)
        elif ln == "SUITE_DONE":
            rec["done"] = True
        elif ln.startswith("== ") and ln.endswith(" ==") and not ln.startswith("== record:"):
            key = ln[3:-3]
            group, _, fil = key.partition(" :: ")
            cur = {
                "group": group,
                "file": fil or None,
                "files": [],
                "absent": [],
                "summary": None,
                "failed": set(),
                "absent_group": False,
            }
            # a re-run section replaces an earlier one of the same key
            if key not in rec["sections"]:
                rec["order"].append(key)
            rec["sections"][key] = cur
        elif cur is None:
            continue
        elif ln.startswith("files: "):
            cur["files"] = ln[7:].split()
        elif ln.startswith("ABSENT-GROUP"):
            cur["absent_group"] = True
        elif ln.startswith("ABSENT "):
            cur["absent"].append(ln[7:].strip())
        elif ln.startswith(("FAILED ", "ERROR ")):
            cur["failed"].add(ln.split(" ", 1)[1].strip())
        elif ln.strip() and cur["summary"] is None:
            cur["summary"] = ln.strip()
    return rec


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError as e:
        print(f"error: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def parse_single(path):
    rec = parse_record(load(path))
    if not rec["done"]:
        print(f"error: {path}: no SUITE_DONE (incomplete record)", file=sys.stderr)
        sys.exit(2)
    return rec


def parse_perfile(path):
    lines = load(path)
    chunks = {}
    name = None
    for ln in lines:
        m = re.match(r"^== record: (\S+) ==$", ln)
        if m:
            name = m.group(1)
            chunks[name] = []
        elif name is not None:
            chunks[name].append(ln)
    recs = {k: parse_record(v) for k, v in chunks.items()}
    for want in ("pristine", "tip"):
        if want not in recs:
            print(f"error: {path}: missing `== record: {want} ==`", file=sys.stderr)
            sys.exit(2)
        if not recs[want]["done"]:
            print(f"error: {path}: record {want} has no SUITE_DONE", file=sys.stderr)
            sys.exit(2)
    for extra in ("pristine-capsys", "tip-capsys"):
        if extra in recs and not recs[extra]["done"]:
            print(f"error: {path}: record {extra} has no SUITE_DONE", file=sys.stderr)
            sys.exit(2)
    return recs


def file_sections(rec, group):
    return {s["file"]: s for s in rec["sections"].values() if s["group"] == group and s["file"]}


def excused(group, after_sec, base_sec, base_ids, perfile):
    """Return (ok, why) for a bad AFTER group that is also bad in BASELINE."""
    if perfile is None:
        return False, "no per-file record"
    pristine, tip = perfile["pristine"], perfile["tip"]
    tip_cap = perfile.get("tip-capsys")
    tip_cap_files = file_sections(tip_cap, group) if tip_cap else {}
    if klass(base_sec["summary"]) != klass(after_sec["summary"]):
        return False, "baseline outcome class differs"
    tip_files = file_sections(tip, group)
    pri_files = file_sections(pristine, group)
    if not tip_files:
        return False, "group not in per-file tip record"
    missing = [f for f in after_sec["files"] if f not in tip_files]
    if missing:
        return False, "per-file tip record lacks " + ", ".join(missing)
    for fil, sec in sorted(tip_files.items()):
        kls = klass(sec["summary"])
        pri = pri_files.get(fil)
        if pri is None or pri["absent_group"]:
            # fork-added file (absent on pristine) must pass at the tip, in
            # the default record or in the --capture=sys record
            capsec = tip_cap_files.get(fil)
            passes = (kls == "ok" and not sec["failed"]) or (
                capsec is not None and klass(capsec["summary"]) == "ok" and not capsec["failed"]
            )
            if not passes:
                return False, f"fork-added file {fil} does not pass at the tip"
            continue
        if kls in BAD:
            if klass(pri["summary"]) not in BAD:
                return False, f"{fil} hangs at the tip but not on pristine"
        new = sec["failed"] - pri["failed"] - base_ids
        if new:
            return False, f"{fil} has failures not on pristine: {sorted(new)[0]}"
    for fil, sec in sorted(tip_cap_files.items()):
        # the --capture=sys tip record exercises the tests themselves: all must run to a summary
        if klass(sec["summary"]) != "ok":
            return False, f"{fil} does not complete at the tip even with --capture=sys"
        new = (
            sec["failed"]
            - base_ids
            - (
                set().union(
                    *[
                        x["failed"]
                        for x in file_sections(perfile["pristine-capsys"], group).values()
                    ]
                )
                if "pristine-capsys" in perfile
                else set()
            )
        )
        if new:
            return False, f"{fil} has failures at the tip with --capture=sys: {sorted(new)[0]}"
    return True, "every tip hang/failure also occurs on pristine; fork-added files pass"


def main(argv):
    args = argv[1:]
    perfile_path = None
    pos = []
    i = 0
    while i < len(args):
        if args[i] == "--perfile" and i + 1 < len(args):
            perfile_path = args[i + 1]
            i += 2
        else:
            pos.append(args[i])
            i += 1
    if len(pos) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base = parse_single(pos[0])
    after = parse_single(pos[1])
    if perfile_path is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        perfile_path = os.path.join(root, "docs/v21-evidence/after-port-perfile.txt")
    perfile = parse_perfile(perfile_path) if os.path.exists(perfile_path) else None

    base_ids = (
        set().union(*[s["failed"] for s in base["sections"].values()])
        if base["sections"]
        else set()
    )
    regressions = []
    fixed, pre = [], []
    rows = []
    groups = [k for k in base["order"] if " :: " not in k]
    for k in after["order"]:
        if " :: " not in k and k not in groups:
            groups.append(k)
    print(f"baseline rev: {base['rev']}")
    print(f"after    rev: {after['rev']}")
    for n in after["notes"]:
        print(n[:200])
    for g in groups:
        b = base["sections"].get(g)
        a = after["sections"].get(g)
        if a is None:
            regressions.append(f"group {g}: missing from AFTER")
            rows.append((g, b["summary"] if b else "-", "(missing)", "REGRESSION"))
            continue
        status = "ok"
        akls = klass(a["summary"])
        if a["absent_group"]:
            akls = "missing"
        if akls in BAD:
            ok, why = (False, "group has no result")
            if b is not None and akls != "missing":
                ok, why = (
                    excused(g, a, b, base_ids, perfile)
                    if klass(b["summary"]) == akls
                    else (False, "baseline outcome class differs")
                )
            if ok:
                status = f"excused ({why})"
            else:
                status = "REGRESSION"
                regressions.append(f"group {g}: {a['summary']} ({why})")
        for fid in sorted(a["failed"]):
            if fid in base_ids:
                pre.append(fid)
            else:
                regressions.append(f"new failure: {fid}")
                status = "REGRESSION"
        if b is not None and akls not in BAD:
            fixed += sorted(b["failed"] - a["failed"])
        rows.append((g, b["summary"] if b else "-", a["summary"] or "-", status))
    print()
    print("| group | baseline | after-port | status |")
    print("|---|---|---|---|")
    for g, bs, as_, st in rows:
        print(f"| {g} | {bs[:70]} | {as_[:70]} | {st[:110]} |")
    print()
    print(f"FIXED BY PORT: {len(fixed)}")
    for f in fixed:
        print(f"  {f}")
    print(f"PRE-EXISTING: {len(pre)}")
    for f in pre:
        print(f"  {f}")
    if perfile is not None:
        print(
            f"per-file record: {perfile_path} "
            f"(pristine rev {perfile['pristine']['rev']}, tip rev {perfile['tip']['rev']})"
        )
    for r in regressions:
        print(f"REGRESSION: {r}")
    print(f"REGRESSIONS: {len(regressions)}")
    return 0 if not regressions else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
