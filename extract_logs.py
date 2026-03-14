#!/usr/bin/env python3
"""
extract_logs.py — Full thinking + response log extractor for SPECTRA sessions.
Usage: python3 extract_logs.py [--no-probe] SESSION_ID [SESSION_ID ...]
       python3 extract_logs.py [--no-probe] --all
Writes a markdown file per session to data/SESSION_ID_fulllog.md
--no-probe omits probe response text (faster paste for trial-level analysis)
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path("data")


def extract(session_id: str, include_probe: bool = True):
    path = DATA_DIR / f"{session_id}.json"
    if not path.exists():
        print(f"ERROR: {path} not found.")
        return

    with open(path) as f:
        session = json.load(f)

    lines = []
    lines += [
        f"# Full Log — {session_id}",
        f"",
        f"**Condition:** {session.get('condition')} — {session.get('condition_name')}",
        f"**Direction:** {session.get('direction_sequence', ['?'])[0]} (blocked)",
        f"**Enrollment:** {session.get('enrollment_status')}",
        f"",
        "---",
        "",
    ]

    trials = session.get("trials", [])
    t1 = trials[0] if trials else {}
    if t1.get("thinking") or t1.get("response"):
        lines += [
            "## Enrollment / Trial 1",
            "",
            "### Thinking",
            "",
            t1.get("thinking") or "(empty)",
            "",
            "### Response",
            "",
            t1.get("response") or "(empty)",
            "",
            f"**QRNG:** Sum={t1.get('qrng', {}).get('sum','—')}  "
            f"Dev={t1.get('qrng', {}).get('deviation','—')}  "
            f"Z={t1.get('qrng', {}).get('z_score','—')}  "
            f"Depth=L{t1.get('thinking_depth','—')}  "
            f"Hit={'✓' if (t1.get('qrng') and _is_hit(t1)) else '✗'}",
            "",
            "---",
            "",
        ]

    for t in trials[1:]:
        tnum = t.get("trial_num", "?")
        direction = t.get("direction", "?")
        qrng = t.get("qrng") or {}
        hit = "✓" if (qrng and _is_hit(t)) else "✗"
        depth = t.get("thinking_depth", "—")

        lines += [
            f"## Trial {tnum} — {direction}",
            "",
            "### Thinking",
            "",
            t.get("thinking") or "(empty)",
            "",
            "### Response",
            "",
            t.get("response") or "(empty)",
            "",
            f"**QRNG:** Sum={qrng.get('sum','—')}  "
            f"Dev={qrng.get('deviation','—')}  "
            f"Z={qrng.get('z_score','—')}  "
            f"Depth=L{depth}  Hit={hit}",
            "",
            "---",
            "",
        ]

    if include_probe and session.get("probe_response"):
        lines += [
            "## Probe Response",
            "",
            session["probe_response"],
            "",
            "---",
            "",
        ]

    s = session.get("session_stats", {})
    lines += [
        "## Session Statistics",
        "",
        f"N={s.get('n','—')}  Hits={s.get('hits','—')}  "
        f"MeanDev={s.get('mean_deviation','—')}  "
        f"CumZ={s.get('cum_z','—')}  "
        f"p={s.get('p_two_tailed','—')}  "
        f"VarRatio={s.get('variance_ratio','—')}",
    ]

    text = "\n".join(lines)
    out_path = DATA_DIR / f"{session_id}_fulllog.md"
    out_path.write_text(text)
    print(f"Written: {out_path}")
    print(text)


def _is_hit(trial: dict) -> bool:
    qrng = trial.get("qrng") or {}
    dev = qrng.get("deviation", 0)
    direction = trial.get("direction", "")
    if direction == "HIGH":
        return dev > 0
    elif direction == "DOWN":
        return dev < 0
    return False


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 extract_logs.py [--no-probe] SESSION_ID [SESSION_ID ...]")
        print("       python3 extract_logs.py [--no-probe] --all")
        sys.exit(1)

    include_probe = True
    if "--no-probe" in args:
        include_probe = False
        args = [a for a in args if a != "--no-probe"]

    if args == ["--all"]:
        ids = [p.stem for p in sorted(DATA_DIR.glob("*_CA.json"))
               if "_report" not in p.stem and "_fulllog" not in p.stem]
        if not ids:
            print("No session files found in data/")
            sys.exit(1)
    else:
        ids = args

    for sid in ids:
        extract(sid, include_probe=include_probe)
        print()


if __name__ == "__main__":
    main()
