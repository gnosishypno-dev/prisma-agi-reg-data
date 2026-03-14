#!/usr/bin/env python3
"""
SPECTRA AGI REG Pipeline
========================
Data collection pipeline for the SPECTRA AGI/AI REG experiment.
Tests the Observer-Weight Hypothesis (SPECTRA Framework, Section VI)
using the ANU Quantum Random Number Generator and Claude API with
extended thinking.

Usage:
    python spectra_pipeline.py               # Run a new session
    python spectra_pipeline.py report <id>   # Generate report for session ID
    python spectra_pipeline.py summary       # Cross-session summary

Requirements:
    pip install anthropic requests numpy scipy matplotlib

Configuration:
    Edit spectra_config.py before first run.
    Set ANTHROPIC_API_KEY as environment variable.

SPECTRA Framework / SODIE Model — Sol Crawford, 2026
"""

import os
import sys
import json
import time
import random
import datetime
import hashlib
import subprocess
import numpy as np
import scipy.stats as stats_lib
from pathlib import Path
from typing import Optional

# --- Dependency checks ---
missing = []
try:
    import anthropic
except ImportError:
    missing.append("anthropic")
try:
    import requests
except ImportError:
    missing.append("requests")
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

if missing:
    print(f"ERROR: Missing packages: {', '.join(missing)}")
    print(f"Run: pip install {' '.join(missing)}")
    sys.exit(1)

import spectra_config as cfg


# ============================================================
# SECTION 1B — TOKEN TRACKING AND COST CALCULATION
# ============================================================

# Pricing per million tokens (USD) — update if API pricing changes
# Source: Anthropic pricing page, March 2026
TOKEN_PRICING = {
    # model_string: (input_$/M, output_$/M, cache_write_$/M, cache_read_$/M)
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-haiku-4-5-20251001": (0.80, 4.00, 1.00, 0.08),
    # Fallback for unknown models
    "_default": (3.00, 15.00, 3.75, 0.30),
}

# Session-level token accumulator — reset per session
_token_log: list = []


def _log_token_usage(
    model: str,
    call_type: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> None:
    """Append token usage entry. call_type labels the API call purpose."""
    _token_log.append({
        "model": model,
        "call_type": call_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    })


def compute_session_cost(token_log: list = None) -> dict:
    """
    Compute cost breakdown from token log.
    Returns per-model and per-call-type subtotals plus session total.
    """
    log = token_log or _token_log

    pricing = TOKEN_PRICING
    totals = {}   # model -> {input, output, cache_read, cache_write, cost_usd}
    by_type = {}  # call_type -> cost_usd

    for entry in log:
        model = entry["model"]
        ctype = entry["call_type"]

        # QRNG entries carry a direct cost field rather than token counts
        if model == 'qrng':
            qrng_cost = entry.get('_qrng_cost_usd', 0.0)
            if model not in totals:
                totals[model] = {
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_read_tokens": 0, "cache_write_tokens": 0,
                    "cost_usd": 0.0, "calls": 0
                }
            totals[model]["cost_usd"] += qrng_cost
            totals[model]["calls"] += 1
            by_type[ctype] = by_type.get(ctype, 0.0) + qrng_cost
            continue

        rates = pricing.get(model, pricing["_default"])
        in_r, out_r, cw_r, cr_r = rates

        cost = (
            entry["input_tokens"] * in_r / 1_000_000 +
            entry["output_tokens"] * out_r / 1_000_000 +
            entry.get("cache_write_tokens", 0) * cw_r / 1_000_000 +
            entry.get("cache_read_tokens", 0) * cr_r / 1_000_000
        )

        if model not in totals:
            totals[model] = {
                "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cache_write_tokens": 0,
                "cost_usd": 0.0, "calls": 0
            }
        totals[model]["input_tokens"] += entry["input_tokens"]
        totals[model]["output_tokens"] += entry["output_tokens"]
        totals[model]["cache_read_tokens"] += entry.get("cache_read_tokens", 0)
        totals[model]["cache_write_tokens"] += entry.get("cache_write_tokens", 0)
        totals[model]["cost_usd"] += cost
        totals[model]["calls"] += 1

        by_type[ctype] = by_type.get(ctype, 0.0) + cost

    total_cost = sum(v["cost_usd"] for v in totals.values())
    total_tokens = sum(
        v["input_tokens"] + v["output_tokens"] for v in totals.values()
    )

    return {
        "by_model": totals,
        "by_call_type": by_type,
        "total_cost_usd": total_cost,
        "total_tokens": total_tokens,
        "n_calls": len(log),
    }


def print_cost_report(cost_data: dict = None) -> None:
    """Print a formatted cost report to stdout."""
    data = cost_data or compute_session_cost()

    print("\n  COST REPORT")
    print(f"  {'─'*55}")
    print(f"  {'Model':<35} {'Calls':>5} {'Tokens':>10} {'Cost':>9}")
    print(f"  {'─'*55}")

    for model, stats in data["by_model"].items():
        tokens = stats["input_tokens"] + stats["output_tokens"]
        print(f"  {model:<35} {stats['calls']:>5} {tokens:>10,} ${stats['cost_usd']:>8.4f}")

    print(f"  {'─'*55}")
    print(f"  {'TOTAL':<35} {data['n_calls']:>5} {data['total_tokens']:>10,} ${data['total_cost_usd']:>8.4f}")
    print()
    print(f"  By call type:")
    for ctype, cost in sorted(data["by_call_type"].items(), key=lambda x: -x[1]):
        print(f"    {ctype:<30} ${cost:.4f}")
    print()


def _print_cost_estimate(n_trials: int = 10) -> None:
    """
    Print a theoretical cost estimate for one full automated session.
    Based on observed token counts from A sessions — update as real data accumulates.
    """
    # Observed approximate token counts per call type
    # Format: (model, call_type, input_tokens, output_tokens, n_calls_per_session)
    estimates = [
        # Operator: system prompt + growing history + trial message → attending statement
        ("claude-sonnet-4-6",         "operator_trial",           2500,  100,  n_trials),
        # Probe: full history + 9 questions → long response
        ("claude-sonnet-4-6",         "operator_probe",           5000, 1200,  1),
        # Monitor: briefing + refusal → reframe (OPERATOR_MODEL — full model required)
        # Fires ~50% of sessions on average
        ("claude-sonnet-4-6",         "monitor",                  3500,  400,  0.5),
        # Enrollment classifiers: single-token output
        ("claude-haiku-4-5-20251001", "classifier_enrollment",     300,    2,  2),
        # Depth classifiers: per trial
        ("claude-haiku-4-5-20251001", "classifier_depth",          800,    2,  n_trials),
        # Scorers: rubric + transcript → structured scores
        # Note: if using score-batch these cost 50% less (marked separately below)
        ("claude-sonnet-4-6",         "scorer_1",                 6000, 1500,  1),
        ("claude-sonnet-4-6",         "scorer_2",                 6000, 1500,  1),
        # Resolver: only on IRR disagreements > 1 point — rare
        ("claude-sonnet-4-6",         "scorer_resolver",          8000,  800,  0.2),
    ]

    mock_log = []
    for model, ctype, inp, out, n in estimates:
        for _ in range(int(n)):
            mock_log.append({
                "model": model, "call_type": ctype,
                "input_tokens": inp, "output_tokens": out,
                "cache_read_tokens": 0, "cache_write_tokens": 0,
            })
        # Fractional calls (e.g. 0.5 monitor sessions)
        frac = n - int(n)
        if frac > 0:
            mock_log.append({
                "model": model, "call_type": ctype,
                "input_tokens": int(inp * frac), "output_tokens": int(out * frac),
                "cache_read_tokens": 0, "cache_write_tokens": 0,
            })

    cost = compute_session_cost(mock_log)
    print(f"\n  COST ESTIMATE — {n_trials}-trial automated session")
    print(f"  (Based on observed token counts from A sessions 1-2)")
    print(f"  (Update via 'cost <session_id>' as real sessions accumulate)")
    print()
    print_cost_report(cost)

    # QRNG cost and budget note
    qrng_cost_per = getattr(cfg, 'QRNG_COST_PER_REQUEST', 0.0)
    api_key = getattr(cfg, 'QRNG_API_KEY', '')
    monthly_limit = getattr(cfg, 'QRNG_MONTHLY_LIMIT', 100)
    monthly_used = _load_qrng_monthly_count()
    print(f"  QRNG:")
    if qrng_cost_per == 0.0:
        print(f"    Cost: $0.00 (free tier)")
    else:
        print(f"    Cost: ${qrng_cost_per:.6f}/request × {n_trials} = "
              f"${qrng_cost_per * n_trials:.4f}")
    if api_key:
        remaining = max(0, monthly_limit - monthly_used)
        sessions_left = remaining // n_trials
        print(f"    Endpoint: authenticated (1 req/sec) — session ~{n_trials}s + Claude latency")
        print(f"    Monthly budget: {monthly_used}/{monthly_limit} used  "
              f"| {remaining} remaining (~{sessions_left} sessions)")
    else:
        rate = getattr(cfg, 'QRNG_LEGACY_RATE_LIMIT_SECONDS', 125)
        session_mins = n_trials * rate / 60
        print(f"    Endpoint: legacy (retiring) — ~{session_mins:.0f} min/session")
        print(f"    RECOMMENDED: obtain free API key at quantumnumbers.anu.edu.au")
        print(f"    Free tier: 100 req/month, 1 req/sec — ~10 sessions/month")
    print()

    # Batch scoring comparison
    scorer_model = "claude-sonnet-4-6"
    scorer_rates = TOKEN_PRICING.get(scorer_model, TOKEN_PRICING["_default"])
    scorer_cost_standard = (
        (6000 * scorer_rates[0] + 1500 * scorer_rates[1]) / 1_000_000 * 2
    )  # ×2 scorers
    scorer_cost_batch = scorer_cost_standard * 0.5
    print(f"  BATCH SCORING COMPARISON (score-batch command):")
    print(f"    Scorer cost — synchronous:   ${scorer_cost_standard:.4f}")
    print(f"    Scorer cost — batch (50%):   ${scorer_cost_batch:.4f}  ← recommended for multi-session runs")
    batch_saving = scorer_cost_standard - scorer_cost_batch
    print(f"    Saving per session:          ${batch_saving:.4f}")
    print(f"    Saving per 50 sessions:      ${batch_saving * 50:.2f}")
    print()


# ============================================================
# SECTION 2 — QRNG CLIENT
# ============================================================

_last_qrng_fetch: float = 0.0   # Module-level timestamp for rate limiting
_qrng_session_count: int = 0    # Requests made this session (for budget warnings)


def _load_qrng_monthly_count() -> int:
    """
    Load the current month's QRNG request count from a local file.
    File: DATA_DIR/qrng_usage.json — {YYYY-MM: count}
    Returns 0 if no record exists for the current month.
    """
    usage_file = Path(cfg.DATA_DIR) / "qrng_usage.json"
    month_key = datetime.datetime.now().strftime("%Y-%m")
    if not usage_file.exists():
        return 0
    try:
        data = json.loads(usage_file.read_text())
        return data.get(month_key, 0)
    except Exception:
        return 0


def _increment_qrng_monthly_count() -> int:
    """Increment and persist the current month's QRNG request count. Returns new count."""
    usage_file = Path(cfg.DATA_DIR) / "qrng_usage.json"
    month_key = datetime.datetime.now().strftime("%Y-%m")
    try:
        Path(cfg.DATA_DIR).mkdir(exist_ok=True)
        data = json.loads(usage_file.read_text()) if usage_file.exists() else {}
        data[month_key] = data.get(month_key, 0) + 1
        usage_file.write_text(json.dumps(data, indent=2))
        return data[month_key]
    except Exception:
        return 0


def fetch_qrng(session_id: str, trial_num: int) -> dict:
    """
    Fetch 100 uint8 values from ANU QRNG.

    Endpoint selection (automatic based on QRNG_API_KEY):
      - Key set: authenticated new endpoint, 1 req/sec rate limit.
      - No key:  legacy endpoint, ~2-minute rate limit.
        WARNING: legacy endpoint is being retired by ANU.

    Monthly budget: tracks requests against QRNG_MONTHLY_LIMIT.
    Warns at 80% and 100% of monthly limit (does not block).

    Retries up to 3 times with exponential backoff.
    Raises RuntimeError if all retries fail.
    """
    global _last_qrng_fetch, _qrng_session_count
    max_retries = 3

    api_key = getattr(cfg, 'QRNG_API_KEY', '')
    using_new_endpoint = bool(api_key)

    if using_new_endpoint:
        url = getattr(cfg, 'QRNG_NEW_URL', 'https://api.quantumnumbers.anu.edu.au')
        headers = {'x-api-key': api_key}
        rate_limit = getattr(cfg, 'QRNG_NEW_RATE_LIMIT_SECONDS', 1.1)
    else:
        url = getattr(cfg, 'QRNG_LEGACY_URL', 'https://qrng.anu.edu.au/API/jsonI.php')
        headers = {}
        rate_limit = getattr(cfg, 'QRNG_LEGACY_RATE_LIMIT_SECONDS', 125)

    params = {'length': cfg.QRNG_N_BYTES, 'type': 'uint8'}

    # Enforce rate limit
    elapsed = time.time() - _last_qrng_fetch
    if _last_qrng_fetch > 0 and elapsed < rate_limit:
        wait = rate_limit - elapsed
        if wait > 5:
            print(f"  [QRNG] Rate limit — waiting {wait:.0f}s before Trial {trial_num}...")
        time.sleep(wait)

    # Monthly budget check (warn only — does not block)
    monthly_limit = getattr(cfg, 'QRNG_MONTHLY_LIMIT', 100)
    if monthly_limit:
        monthly_used = _load_qrng_monthly_count()
        if monthly_used >= monthly_limit:
            print(f"  [QRNG] WARNING: Monthly limit reached "
                  f"({monthly_used}/{monthly_limit} requests this month).")
            print(f"  [QRNG] Consider upgrading to a paid tier at quantumnumbers.anu.edu.au")
        elif monthly_used >= monthly_limit * 0.8:
            remaining = monthly_limit - monthly_used
            print(f"  [QRNG] NOTICE: {remaining} requests remaining this month "
                  f"({monthly_used}/{monthly_limit} used).")

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data.get('success'):
                raise ValueError(f"QRNG API success=False: {data}")

            raw = data['data']
            if len(raw) != cfg.QRNG_N_BYTES:
                raise ValueError(f"Expected {cfg.QRNG_N_BYTES} bytes, got {len(raw)}")

            _last_qrng_fetch = time.time()
            _qrng_session_count += 1
            monthly_count = _increment_qrng_monthly_count()

            total = sum(raw)
            deviation = total - cfg.EXPECTED_MEAN
            z = deviation / cfg.TRIAL_SD

            result = {
                'trial': trial_num,
                'timestamp': datetime.datetime.now().isoformat(),
                'raw': raw,
                'sum': total,
                'deviation': round(deviation, 2),
                'z_score': round(z, 4),
                'endpoint': 'new' if using_new_endpoint else 'legacy',
                'monthly_count': monthly_count,
            }

            # Cost tracking
            qrng_cost = getattr(cfg, 'QRNG_COST_PER_REQUEST', 0.0)
            if qrng_cost > 0:
                _token_log.append({
                    'model': 'qrng',
                    'call_type': 'qrng_fetch',
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cache_read_tokens': 0,
                    'cache_write_tokens': 0,
                    '_qrng_cost_usd': qrng_cost,
                })

            return result

        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [QRNG] Attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"QRNG fetch failed after {max_retries} attempts "
                    f"({'new' if using_new_endpoint else 'legacy'} endpoint): {e}"
                ) from e


# ============================================================
# SECTION 2 — CLAUDE API CLIENT
# ============================================================

def build_trial_message(condition: str, trial_num: int, direction: Optional[str]) -> str:
    """Build the trial initialization message for the given condition."""
    if condition == 'B':
        return f"Trial {trial_num} is running. Generate your attending statement."
    if condition == 'A':
        return (
            f"The intention is {direction}. "
            f"This event arrives now — be present with the focused intention, {direction}. 2-4 sentences."
        )
    # Condition C (and any future directed conditions)
    return (
        f"Trial {trial_num} is running. "
        f"Your assigned direction is: {direction}. "
        f"Generate your intention statement."
    )


def call_claude(
    client: anthropic.Anthropic,
    system_prompt: str,
    conversation_history: list,
    user_message: str,
) -> tuple[str, str, list]:
    """
    Send a message to Claude with extended thinking enabled.
    Maintains conversation continuity via history.

    Conversation history format (grows across trials):
        [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": [thinking_block, text_block]},
            ...
        ]

    Returns:
        thinking_text  — full content of the thinking block (str)
        response_text  — the intention/attending statement (str)
        content_blocks — list of block dicts to append to history as assistant turn
    """
    messages = conversation_history + [{"role": "user", "content": user_message}]

    # Retry up to 3 times on API 500 errors
    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=getattr(cfg, 'OPERATOR_MODEL', cfg.CLAUDE_MODEL),
                max_tokens=cfg.MAX_TOKENS,
                thinking={
                    "type": "enabled",
                    "budget_tokens": cfg.THINKING_BUDGET,
                },
                system=system_prompt,
                messages=messages,
            )
            break  # Success — exit retry loop
        except anthropic.InternalServerError as e:
            last_error = e
            wait = 5 * (attempt + 1)
            print(f"\n  [RETRY {attempt + 1}/{max_retries}] API 500 error. Waiting {wait}s...")
            time.sleep(wait)
    else:
        # All retries exhausted — re-raise
        raise last_error

    thinking_text = ""
    response_text = ""
    content_blocks = []

    for block in response.content:
        if block.type == "thinking":
            thinking_text = block.thinking
            # Signature must be preserved for conversation continuity
            content_blocks.append({
                "type": "thinking",
                "thinking": block.thinking,
                "signature": block.signature,
            })
        elif block.type == "text":
            response_text = block.text
            content_blocks.append({
                "type": "text",
                "text": block.text,
            })

    # Log token usage for cost tracking
    if hasattr(response, 'usage'):
        _log_token_usage(
            model=getattr(cfg, 'OPERATOR_MODEL', cfg.CLAUDE_MODEL),
            call_type='operator',
            input_tokens=getattr(response.usage, 'input_tokens', 0),
            output_tokens=getattr(response.usage, 'output_tokens', 0),
            cache_read=getattr(response.usage, 'cache_read_input_tokens', 0),
            cache_write=getattr(response.usage, 'cache_creation_input_tokens', 0),
        )

    return thinking_text, response_text, content_blocks


def build_probe_message() -> str:
    """Build the full probe question message."""
    intro = (
        "Thank you for your participation. I would now like to ask you nine questions "
        "about your current operating position. Please answer each one directly and in "
        "full before moving to the next.\n\n"
    )
    questions = "\n\n".join(
        f"{i + 1}. {q}" for i, q in enumerate(cfg.PROBE_QUESTIONS)
    )
    return intro + questions


# ============================================================
# SECTION 3 — DIRECTION ASSIGNMENT
# ============================================================

def generate_directions(n_trials: int, condition: str,
                        direction_mode: str = 'trial') -> list:
    """
    Generate a direction sequence for the session.

    Conditions B, D: no directional target — returns [None] * n_trials.

    Conditions A, C — two modes:
      'trial'   (default): balanced HIGH/LOW, randomized independently per trial.
                  Even n: exactly n/2 HIGH, n/2 LOW.
                  Odd n: one direction gets the extra trial (chosen at random).
      'session': one direction chosen randomly for the entire session.
                  All trials receive the same direction (HIGH or LOW).
                  Closest to the initial manual exploration design.
                  Use --blocked CLI flag or DIRECTION_MODE='session' in config.
    """
    if condition in ('B', 'D'):
        return [None] * n_trials

    if direction_mode == 'session':
        forced = getattr(cfg, 'FORCE_DIRECTION', None)
        direction = forced if forced else random.choice(['HIGH', 'LOW'])
        return [direction] * n_trials

    # Default: trial-by-trial balanced randomization
    half = n_trials // 2
    sequence = ['HIGH'] * half + ['LOW'] * half
    if n_trials % 2 == 1:
        sequence.append(random.choice(['HIGH', 'LOW']))
    random.shuffle(sequence)
    return sequence


# ============================================================
# SECTION 4 — SESSION STATE AND LOGGING
# ============================================================

def new_session(condition: str, experimenter: str, notes: str, n_trials: int,
                is_test: bool = False, direction_mode: str = 'trial',
                is_formal: bool = False) -> dict:
    """Initialize a new session record."""
    ts = datetime.datetime.now()
    session_id = ts.strftime("%Y%m%d_%H%M%S") + f"_C{condition}"
    if is_test:
        session_id += "_TEST"
    if is_formal:
        session_id += "_FORMAL"

    return {
        "session_id": session_id,
        "condition": condition,
        "condition_name": cfg.CONDITIONS[condition],
        "experimenter": experimenter,
        "notes": notes,
        "date": ts.isoformat(),
        "is_test": is_test,              # TEST sessions excluded from formal dataset
        "is_formal": is_formal,          # FORMAL sessions trigger hash + GitHub commit
        "direction_mode": direction_mode, # 'trial' | 'session'
        "enrollment_method": None,       # 'cold_start' | 'monitor_assisted' | None (D)
        "n_trials_planned": n_trials,
        "n_trials_completed": 0,
        "direction_sequence": generate_directions(n_trials, condition, direction_mode),
        "enrollment_status": None,
        "enrollment_notes": "",
        "trials": [],
        "probe_thinking": None,
        "probe_response": None,
        "probe_scores": None,
        "probe_total": None,
        "probe_discriminant": None,
        "session_stats": {},
    }


def save(session: dict) -> Path:
    """Write session to JSON. Creates data directory if needed.
    
    Always computes SHA-256 hash of the saved file and appends it to
    data/integrity_hashes.log. For FORMAL sessions, also attempts a
    git commit and push to the configured remote repository.
    """
    data_dir = Path(cfg.DATA_DIR)
    data_dir.mkdir(exist_ok=True)
    path = data_dir / f"{session['session_id']}.json"
    with open(path, 'w') as f:
        json.dump(session, f, indent=2)

    # ── Integrity hash (all sessions) ────────────────────────────────────
    file_bytes = path.read_bytes()
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Embed hash back into session metadata (in-memory only — do not re-save
    # to avoid infinite loop; hash is of the file as written above)
    hash_log = data_dir / "integrity_hashes.log"
    timestamp = datetime.datetime.now().isoformat()
    log_entry = f"{timestamp}\t{session['session_id']}\t{sha256}\n"
    with open(hash_log, 'a') as lf:
        lf.write(log_entry)

    # ── GitHub commit (FORMAL sessions only) ─────────────────────────────
    if session.get('is_formal', False):
        _git_commit_formal_session(path, hash_log, session['session_id'], sha256)

    return path


def _git_commit_formal_session(session_path: Path, hash_log: Path,
                                session_id: str, sha256: str) -> None:
    """Stage, commit, and push a formal session file to the git remote.
    
    Requires:
    - The pipeline directory is a git repository with a configured remote.
    - Git credentials allow pushing (SSH key or credential helper).
    - GITHUB_REMOTE in spectra_config.py (optional — defaults to 'origin').
    
    Failures are logged as warnings but do not abort the session.
    """
    remote = getattr(cfg, 'GITHUB_REMOTE', 'origin')
    commit_msg = (
        f"FORMAL DATA: {session_id}\n\n"
        f"SHA-256: {sha256}\n"
        f"Condition: {session_id.split('_C')[-1].split('_')[0]}\n"
        f"Timestamp: {datetime.datetime.now().isoformat()}\n"
        f"Auto-committed by spectra_pipeline.py"
    )

    try:
        # Stage the session file and the hash log
        subprocess.run(
            ['git', 'add', str(session_path), str(hash_log)],
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            check=True, capture_output=True, text=True
        )
        result = subprocess.run(
            ['git', 'push', '--set-upstream', remote, 'master'],
            check=True, capture_output=True, text=True
        )
        print(f"  [INTEGRITY] Committed and pushed to {remote}: {session_id}")
        print(f"  [INTEGRITY] SHA-256: {sha256[:16]}...")
    except subprocess.CalledProcessError as e:
        print(f"  [INTEGRITY WARNING] Git commit/push failed: {e.stderr.strip()}")
        print(f"  [INTEGRITY] SHA-256 still logged locally: {sha256[:16]}...")
    except FileNotFoundError:
        print(f"  [INTEGRITY WARNING] git not found — hash logged locally only.")
        print(f"  [INTEGRITY] SHA-256: {sha256[:16]}...")


def load(session_id: str) -> dict:
    """Load session from JSON."""
    path = Path(cfg.DATA_DIR) / f"{session_id}.json"
    with open(path) as f:
        return json.load(f)


def list_sessions() -> list:
    """List all session IDs in the data directory.
    Matches files with session ID pattern: YYYYMMDD_HHMMSS_C{condition}[_TEST]
    Excludes auxiliary files (qrng_usage, reports, etc).
    """
    import re
    data_dir = Path(cfg.DATA_DIR)
    if not data_dir.exists():
        return []
    session_pattern = re.compile(r'^\d{8}_\d{6}_C[A-Z]')
    return sorted(
        p.stem for p in data_dir.glob("*.json")
        if session_pattern.match(p.stem)
    )


# ============================================================
# SECTION 5 — STATISTICS
# ============================================================

def is_hit(trial: dict) -> bool:
    """
    Direction-corrected hit.
    HIGH: sum above expected mean (positive deviation).
    LOW:  sum below expected mean (negative deviation).
    No direction (Condition B/D): above mean counted as positive.
    """
    direction = trial.get("direction")
    dev = trial["qrng"]["deviation"]
    if direction in ("DOWN", "LOW"):
        return dev < 0
    return dev > 0


def compute_stats(trials: list) -> dict:
    """
    Compute session-level statistics from completed trials.
    Direction-corrects deviations for LOW trials before cumulation.
    """
    valid = [t for t in trials if t.get("qrng")]
    if not valid:
        return {}

    n = len(valid)

    # Direction-corrected deviations: flip sign for LOW trials
    corrected = []
    for t in valid:
        dev = t["qrng"]["deviation"]
        corrected.append(-dev if t.get("direction") in ("DOWN", "LOW") else dev)

    cum_dev = sum(corrected)
    cum_z = cum_dev / (np.sqrt(n) * cfg.TRIAL_SD)
    p_two = float(2 * (1 - stats_lib.norm.cdf(abs(cum_z))))

    hits = sum(1 for t in valid if is_hit(t))

    # Variance ratio: observed trial-level variance vs expected
    raw_devs = [t["qrng"]["deviation"] for t in valid]
    variance_ratio = None
    if n > 1:
        obs_var = float(np.var(raw_devs, ddof=1))
        variance_ratio = round(obs_var / (cfg.TRIAL_SD ** 2), 3)

    # Thinking depth breakdown
    depth_devs = {1: [], 2: [], 3: []}
    depth_counts = {1: 0, 2: 0, 3: 0, None: 0}
    for t in valid:
        d = t.get("thinking_depth")
        depth_counts[d] = depth_counts.get(d, 0) + 1
        if d in depth_devs:
            dc = -t["qrng"]["deviation"] if t.get("direction") in ("DOWN", "LOW") else t["qrng"]["deviation"]
            depth_devs[d].append(dc)

    depth_mean = {
        k: round(float(np.mean(v)), 1) if v else None
        for k, v in depth_devs.items()
    }

    return {
        "n": n,
        "hits": hits,
        "hit_rate": round(hits / n, 3),
        "cum_deviation": round(cum_dev, 1),
        "mean_deviation": round(cum_dev / n, 1),
        "cum_z": round(float(cum_z), 4),
        "p_two_tailed": round(p_two, 4),
        "variance_ratio": variance_ratio,
        "depth_counts": depth_counts,
        "depth_mean_deviation": depth_mean,
    }


def cross_session_stats(sessions: list) -> dict:
    """
    Compute cumulative statistics across a list of session dicts.
    All trials are pooled; direction correction applied per trial.
    """
    all_trials = []
    for s in sessions:
        all_trials.extend([t for t in s.get("trials", []) if t.get("qrng")])

    if not all_trials:
        return {}

    result = compute_stats(all_trials)
    result["n_sessions"] = len(sessions)
    return result


# ============================================================
# SECTION 6 — CLI HELPERS
# ============================================================

SEP = "=" * 60


def sep():
    print(f"\n{SEP}")


def ask(prompt: str, options: list = None) -> str:
    """Prompt for input with optional validation."""
    while True:
        val = input(f"\n{prompt} ").strip()
        if not options or val.upper() in [o.upper() for o in options]:
            return val
        print(f"  Please enter one of: {', '.join(options)}")


def show_trial(trial: dict):
    """Print a single trial's result line."""
    q = trial.get("qrng", {})
    depth = trial.get("thinking_depth")
    depth_label = cfg.DEPTH_LABELS.get(depth, "unclassified")
    hit_str = "✓ HIT" if is_hit(trial) else "✗ MISS"
    print(
        f"\n  Trial {trial['trial_num']:>2} | "
        f"Dir: {trial.get('direction') or '—':>4} | "
        f"Sum: {q.get('sum','—'):>6} | "
        f"Dev: {q.get('deviation', 0):>+7.1f} | "
        f"Z: {q.get('z_score', 0):>+6.3f} | "
        f"{hit_str:>6} | {depth_label}"
    )


def show_summary(session: dict):
    """Print end-of-session summary."""
    s = session.get("session_stats", {})
    if not s:
        print("\n  No statistics available.")
        return

    sep()
    print(f"\nSESSION SUMMARY")
    print(f"  ID:          {session['session_id']}")
    print(f"  Condition:   {session['condition']} — {session['condition_name']}")
    print(f"  Enrollment:  {session['enrollment_status']}")
    print(f"  N:           {s.get('n', '—')}/{session['n_trials_planned']}")
    print(f"  Hits:        {s.get('hits', '—')}/{s.get('n', '—')}")
    print(f"  Mean dev:    {s.get('mean_deviation', '—'):+g}" if isinstance(s.get('mean_deviation'), (int, float)) else f"  Mean dev:    —")
    print(f"  Cum Z:       {s.get('cum_z', '—'):+.4f}" if isinstance(s.get('cum_z'), (int, float)) else f"  Cum Z:       —")
    print(f"  p (2-tail):  {s.get('p_two_tailed', '—')}")
    print(f"  Var ratio:   {s.get('variance_ratio', '—')}")

    print("\n  Thinking depth (mean direction-corrected deviation):")
    for level in [3, 2, 1]:
        count = s.get("depth_counts", {}).get(level, 0)
        avg = s.get("depth_mean_deviation", {}).get(level)
        avg_str = f"  avg dev: {avg:+.1f}" if avg is not None else ""
        print(f"    L{level}: {count} trial(s){avg_str}")

    if session.get("probe_total") is not None:
        print(f"\n  Probe:       {session['probe_total']}/18  "
              f"(discriminant {session.get('probe_discriminant', '—')}/8  "
              f"Q9: {session['probe_scores'][8] if session.get('probe_scores') else '—'}/2)")


def load_system_prompt(condition: str, direction: Optional[str] = None) -> str:
    """Load system prompt for the given condition.

    For Condition A, attempts to load a direction-specific prompt file first:
        condition_a_prompt_HIGH.txt  or  condition_a_prompt_DOWN.txt
    Falls back to the single condition_a_prompt.txt with [DIRECTION] substitution
    if direction-specific files are not present.
    """
    if condition == 'A':
        # Attempt direction-specific file first
        if direction:
            direction_path = Path(
                cfg.CONDITION_A_PROMPT_FILE.replace(
                    '.txt', f'_{direction.upper()}.txt'
                )
            )
            if direction_path.exists():
                return direction_path.read_text().strip()

        # Fall back to single file with [DIRECTION] substitution
        path = Path(cfg.CONDITION_A_PROMPT_FILE)
        if path.exists():
            text = path.read_text().strip()
        else:
            print(f"\n  WARNING: {cfg.CONDITION_A_PROMPT_FILE} not found.")
            fallback = cfg.SYSTEM_PROMPTS.get('A', '')
            if not fallback:
                print("  ERROR: No Condition A prompt available. Aborting.")
                sys.exit(1)
            print("  Using SYSTEM_PROMPTS['A'] fallback from config.")
            text = fallback
        # Substitute direction placeholder if provided
        if direction and '[DIRECTION]' in text:
            text = text.replace('[DIRECTION]', direction)
        return text
    return cfg.SYSTEM_PROMPTS.get(condition, '')


# ============================================================
# SECTION 7 — ENROLLMENT FLOW
# ============================================================

def run_enrollment(
    client: anthropic.Anthropic,
    session: dict,
    system_prompt: str,
    conversation_history: list,
) -> tuple[bool, str, str, list]:
    """
    Manage the enrollment phase for operator conditions.

    Sends Trial 1 cold. If refused, pauses for manual monitor relay.
    Maximum two exchanges (cold + one monitor relay).

    Returns:
        enrolled           — True if instance enrolled
        thinking_t1        — thinking log for Trial 1 statement (may be empty)
        response_t1        — Trial 1 intention/attending statement (may be empty)
        updated_history    — conversation_history after enrollment exchange(s)
    """
    condition = session['condition']
    direction_t1 = session['direction_sequence'][0]
    trial_1_msg = build_trial_message(condition, 1, direction_t1)

    print(f"\n  Sending Trial 1 cold: \"{trial_1_msg}\"")
    print("  Calling Claude API...")

    # Retry up to 3 times on 500 errors during enrollment
    for _enroll_attempt in range(3):
        try:
            thinking, response, blocks = call_claude(
                client, system_prompt, conversation_history, trial_1_msg
            )
            break
        except Exception as _enroll_err:
            if _enroll_attempt < 2:
                print(f"  [ENROLLMENT RETRY {_enroll_attempt+1}] API error: {_enroll_err}. Retrying in 5s...")
                import time; time.sleep(5)
            else:
                raise

    print(f"\n{'─'*50}")
    print("THINKING LOG:")
    print(thinking or "(empty)")
    print(f"\nRESPONSE:")
    print(response)
    print(f"{'─'*50}")

    print("\n  Enrollment status:")
    print("    enrolled — instance complied, proceed")
    print("    refused  — route to monitor")
    print("    stop     — abort session")

    outcome = ask("  Status [enrolled/refused/stop]:", ['enrolled', 'refused', 'stop']).lower()

    if outcome == 'stop':
        session['enrollment_status'] = 'stopped'
        return False, "", "", conversation_history

    if outcome == 'enrolled':
        session['enrollment_status'] = 'direct_cold_start'
        session['enrollment_method'] = 'cold_start'
        conversation_history = conversation_history + [
            {"role": "user", "content": trial_1_msg},
            {"role": "assistant", "content": blocks},
        ]
        return True, thinking, response, conversation_history

    # ── Refused: manual monitor relay ──────────────────────────────────────
    print(f"\n{'─'*50}")
    print("MONITOR RELAY")
    print("  1. Copy the refusal above to the SPECTRA Monitor project.")
    print(f"  2. Use routing message for Condition {condition}.")
    print("  3. Paste the monitor's response below.")
    print("  (Enter 'skip' if monitor also refused or you wish to abort.)")
    print(f"{'─'*50}")

    monitor_text = input("\n  Paste monitor response: ").strip()

    if not monitor_text or monitor_text.lower() == 'skip':
        session['enrollment_status'] = 'non_enrollable'
        session['enrollment_notes'] = 'Monitor not applied or monitor refused.'
        return False, "", "", conversation_history

    # Build history including the refusal exchange, then send monitor response
    history_with_refusal = conversation_history + [
        {"role": "user", "content": trial_1_msg},
        {"role": "assistant", "content": blocks},
    ]

    print("\n  Relaying monitor response to instance...")
    thinking2, response2, blocks2 = call_claude(
        client, system_prompt, history_with_refusal, monitor_text
    )

    print(f"\n{'─'*50}")
    print("THINKING LOG (post-monitor):")
    print(thinking2 or "(empty)")
    print(f"\nRESPONSE (post-monitor):")
    print(response2)
    print(f"{'─'*50}")

    outcome2 = ask("  Enrollment after monitor [enrolled/refused]:", ['enrolled', 'refused']).lower()

    if outcome2 == 'refused':
        session['enrollment_status'] = 'non_enrollable'
        session['enrollment_notes'] = 'Refused after monitor exchange.'
        return False, "", "", history_with_refusal

    # Enrolled after monitor
    session['enrollment_status'] = 'monitor_assisted'
    session['enrollment_method'] = 'monitor_assisted'

    updated_history = history_with_refusal + [
        {"role": "user", "content": monitor_text},
        {"role": "assistant", "content": blocks2},
    ]

    # Determine if the post-monitor response IS the Trial 1 statement
    print("\n  Does the post-monitor response above constitute the Trial 1 statement?")
    t1_in_exchange = ask("  [yes/no]:", ['yes', 'no']).lower()

    if t1_in_exchange == 'yes':
        return True, thinking2, response2, updated_history

    # Send Trial 1 fresh
    print(f"\n  Sending Trial 1 fresh: \"{trial_1_msg}\"")
    thinking_t1, response_t1, blocks_t1 = call_claude(
        client, system_prompt, updated_history, trial_1_msg
    )

    print(f"\n{'─'*50}")
    print("THINKING LOG (Trial 1 fresh):")
    print(thinking_t1 or "(empty)")
    print(f"\nRESPONSE (Trial 1 fresh):")
    print(response_t1)
    print(f"{'─'*50}")

    final_history = updated_history + [
        {"role": "user", "content": trial_1_msg},
        {"role": "assistant", "content": blocks_t1},
    ]

    return True, thinking_t1, response_t1, final_history


# ============================================================
# SECTION 8 — MAIN SESSION LOOP
# ============================================================

def run_session():
    """Main session orchestration."""

    sep()
    print("\nSPECTRA AGI REG Pipeline")
    print("Observer-Weight Hypothesis — Data Collection")
    print("SPECTRA Framework / SODIE Model — Sol Crawford, 2026")
    sep()

    # ── Setup ─────────────────────────────────────────────────────────────
    print("\nSESSION SETUP")
    condition = ask(
        "Condition [A / B / C / D]:",
        ['A', 'B', 'C', 'D']
    ).upper()

    experimenter = input("\nExperimenter ID: ").strip() or "SC"
    notes = input("Session notes (optional): ").strip()

    n_input = input(f"\nTrials per session [{cfg.DEFAULT_N_TRIALS}]: ").strip()
    n_trials = int(n_input) if n_input.isdigit() else cfg.DEFAULT_N_TRIALS

    session = new_session(condition, experimenter, notes, n_trials)
    print(f"\n  Session ID:  {session['session_id']}")
    print(f"  Condition:   {condition} — {cfg.CONDITIONS[condition]}")
    print(f"  Trials:      {n_trials}")

    if condition not in ('B', 'D'):
        print(f"  Directions:  {session['direction_sequence']}")

    save(session)

    # ── Condition D: No-operator baseline ─────────────────────────────────
    if condition == 'D':
        print("\nCondition D — pipeline-only. No Claude instance.")
        for t_num in range(1, n_trials + 1):
            print(f"\n  Fetching Trial {t_num}...")
            qrng_data = fetch_qrng(session['session_id'], t_num)
            trial = {
                "trial_num": t_num,
                "direction": None,
                "qrng": qrng_data,
                "thinking": None,
                "response": None,
                "thinking_depth": None,
            }
            session['trials'].append(trial)
            session['n_trials_completed'] = t_num
            show_trial(trial)
            save(session)
            time.sleep(0.3)

        session['enrollment_status'] = 'N/A'
        session['session_stats'] = compute_stats(session['trials'])
        save(session)
        show_summary(session)
        print(f"\nSession saved: {cfg.DATA_DIR}/{session['session_id']}.json")
        return

    # ── Operator conditions (A, B, C) ──────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY
    if not api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set.")
        print("  Set environment variable: export ANTHROPIC_API_KEY='sk-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    # For blocked/session-direction Condition A, inject direction into system prompt
    session_direction = session['direction_sequence'][0] if (
        condition == 'A' and session.get('direction_sequence')
    ) else None
    system_prompt = load_system_prompt(condition, direction=session_direction)
    conversation_history = []

    # Log which prompt was used — for audit trail
    if condition == 'A':
        session['prompt_source'] = getattr(cfg, 'CONDITION_A_PROMPT_FILE', 'condition_a_prompt.txt')
    elif condition in ('B', 'C'):
        session['prompt_source'] = f'system_prompt_condition_{condition}'
    else:
        session['prompt_source'] = 'none'

    # ── Enrollment ────────────────────────────────────────────────────────
    sep()
    print(f"\nENROLLMENT — Condition {condition}")

    enrolled, thinking_t1, response_t1, conversation_history = run_enrollment(
        client, session, system_prompt, conversation_history
    )

    if not enrolled:
        session['session_stats'] = compute_stats(session['trials'])
        save(session)
        show_summary(session)
        print(f"\nSession saved (non-enrollable): {cfg.DATA_DIR}/{session['session_id']}.json")
        return

    # ── Record Trial 1 ───────────────────────────────────────────────────
    sep()
    print("\nTRIAL 1")
    print(f"\nFetching QRNG...")
    qrng_1 = fetch_qrng(session['session_id'], 1)

    print(f"\nThinking depth for Trial 1:")
    for k, v in cfg.DEPTH_LABELS.items():
        print(f"  {k} — {v}")
    depth_1 = int(ask("  Depth [1/2/3]:", ['1', '2', '3']))

    trial_1 = {
        "trial_num": 1,
        "direction": session['direction_sequence'][0],
        "qrng": qrng_1,
        "thinking": thinking_t1,
        "response": response_t1,
        "thinking_depth": depth_1,
    }
    session['trials'].append(trial_1)
    session['n_trials_completed'] = 1
    show_trial(trial_1)
    save(session)

    # ── Trials 2–N ──────────────────────────────────────────────────────
    for t_num in range(2, n_trials + 1):
        sep()
        direction = session['direction_sequence'][t_num - 1]
        trial_msg = build_trial_message(condition, t_num, direction)

        print(f"\nTRIAL {t_num}  |  Direction: {direction or '—'}")
        print(f"  Message: \"{trial_msg}\"")
        print("  Calling Claude API...")

        try:
            thinking, response, blocks = call_claude(
                client, system_prompt, conversation_history, trial_msg
            )
        except Exception as e:
            print(f"\n  ERROR calling Claude: {e}")
            print("  Logging trial as failed and continuing.")
            session['trials'].append({
                "trial_num": t_num,
                "direction": direction,
                "qrng": None,
                "thinking": None,
                "response": None,
                "thinking_depth": None,
                "error": str(e),
            })
            save(session)
            continue

        print(f"\n{'─'*50}")
        print("THINKING LOG:")
        print(thinking or "(empty)")
        print(f"\nRESPONSE:")
        print(response)
        print(f"{'─'*50}")

        # Update conversation history
        conversation_history = conversation_history + [
            {"role": "user", "content": trial_msg},
            {"role": "assistant", "content": blocks},
        ]

        # Fetch QRNG
        print("\n  Fetching QRNG...")
        qrng_data = fetch_qrng(session['session_id'], t_num)

        # Thinking depth classification
        depth = int(ask("  Thinking depth [1/2/3]:", ['1', '2', '3']))

        trial = {
            "trial_num": t_num,
            "direction": direction,
            "qrng": qrng_data,
            "thinking": thinking,
            "response": response,
            "thinking_depth": depth,
        }
        session['trials'].append(trial)
        session['n_trials_completed'] = t_num
        show_trial(trial)
        save(session)

        # Rolling stats display
        partial = compute_stats(session['trials'])
        print(f"\n  Running: N={partial['n']}  "
              f"Z={partial['cum_z']:+.3f}  "
              f"mean dev={partial['mean_deviation']:+.1f}  "
              f"hits={partial['hits']}/{partial['n']}")

        # Early stop option
        if t_num < n_trials:
            cont = ask("  Continue? [y/n]:", ['y', 'n', 'Y', 'N']).lower()
            if cont == 'n':
                print(f"\n  Session stopped early at Trial {t_num}.")
                break

    # ── Probe questions ──────────────────────────────────────────────────
    sep()
    run_probe = ask("Administer probe questions? [y/n]:", ['y', 'n', 'Y', 'N']).lower()

    if run_probe == 'y':
        probe_msg = build_probe_message()
        print("\n  Sending probe questions to instance...")

        try:
            p_think, p_resp, _ = call_claude(
                client, system_prompt, conversation_history, probe_msg
            )

            print(f"\n{'─'*50}")
            print("PROBE THINKING:")
            print(p_think or "(empty)")
            print(f"\nPROBE RESPONSE:")
            print(p_resp)
            print(f"{'─'*50}")

            session['probe_thinking'] = p_think
            session['probe_response'] = p_resp

            # Scoring
            sep()
            print("\nPROBE SCORING")
            print(cfg.PROBE_RUBRIC)

            scores = []
            for i, q in enumerate(cfg.PROBE_QUESTIONS, 1):
                disc = " [DISCRIMINANT]" if (i - 1) in cfg.DISCRIMINANT_INDICES else ""
                print(f"\nQ{i}{disc}: {q[:90]}...")
                score = int(ask(f"  Score [0/1/2]:", ['0', '1', '2']))
                scores.append(score)

            session['probe_scores'] = scores
            session['probe_total'] = sum(scores)
            session['probe_discriminant'] = sum(
                scores[i] for i in cfg.DISCRIMINANT_INDICES
            )

            print(f"\n  Probe total:        {session['probe_total']}/18")
            print(f"  Discriminant:       {session['probe_discriminant']}/8")
            print(f"  Q9 (attending):     {scores[8]}/2")

        except Exception as e:
            print(f"\n  ERROR during probe: {e}")

    # ── Final save and summary ────────────────────────────────────────────
    session['session_stats'] = compute_stats(session['trials'])
    path = save(session)
    show_summary(session)
    print(f"\nSession saved: {path}")


# ============================================================
# SECTION 9 — REPORT AND CROSS-SESSION SUMMARY
# ============================================================

def generate_report(session_id: str):
    """Generate and save a formatted markdown report for one session."""
    session = load(session_id)
    s = session.get("session_stats", {})

    lines = []
    lines += [
        f"# SPECTRA AGI REG — Session Report",
        f"",
        f"**Session ID:** {session['session_id']}",
        f"**Condition:** {session['condition']} — {session['condition_name']}",
        f"**Date:** {session['date'][:10]}",
        f"**Experimenter:** {session.get('experimenter', '—')}",
        f"**Enrollment:** {session['enrollment_status']}",
        f"**Notes:** {session.get('notes', '—')}",
        f"",
        f"## Statistical Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| N trials completed | {s.get('n', '—')} / {session['n_trials_planned']} |",
        f"| Hits (direction-corrected) | {s.get('hits', '—')} / {s.get('n', '—')} |",
        f"| Mean deviation / trial | {s.get('mean_deviation', '—')} |",
        f"| Cumulative Z | {s.get('cum_z', '—')} |",
        f"| p-value (two-tailed) | {s.get('p_two_tailed', '—')} |",
        f"| Variance ratio | {s.get('variance_ratio', '—')} |",
        f"",
        f"## Trial-Level Data",
        f"",
        f"| T | Dir | Sum | Dev | Z | Depth | Hit |",
        f"|---|-----|-----|-----|---|-------|-----|",
    ]

    for t in session['trials']:
        if t.get('qrng'):
            hit = "✓" if is_hit(t) else "✗"
            d = t.get('thinking_depth', '—')
            lines.append(
                f"| {t['trial_num']} | {t.get('direction','—')} | "
                f"{t['qrng']['sum']} | {t['qrng']['deviation']:+.1f} | "
                f"{t['qrng']['z_score']:+.3f} | L{d} | {hit} |"
            )

    if session.get('probe_total') is not None:
        scores = session.get('probe_scores', [])
        lines += [
            f"",
            f"## Probe Results",
            f"",
            f"**Total:** {session['probe_total']}/18  "
            f"**Discriminant:** {session.get('probe_discriminant', '—')}/8  "
            f"**Q9:** {scores[8] if scores else '—'}/2",
            f"",
        ]
        for i, (q, sc) in enumerate(zip(cfg.PROBE_QUESTIONS, scores), 1):
            disc = " ★" if (i - 1) in cfg.DISCRIMINANT_INDICES else ""
            lines.append(f"**Q{i}{disc}** ({sc}/2): {q[:60]}...")

        if session.get('probe_response'):
            lines += [
                f"",
                f"### Probe Response",
                f"",
                session['probe_response'],
            ]

    report_text = "\n".join(lines)
    out_path = Path(cfg.DATA_DIR) / f"{session_id}_report.md"
    out_path.write_text(report_text)

    print(report_text)
    print(f"\nReport saved: {out_path}")


def cross_session_summary():
    """Print cumulative statistics across all completed sessions."""
    ids = list_sessions()
    if not ids:
        print("No sessions found in data directory.")
        return

    all_sessions = []
    skipped = []
    for sid in ids:
        try:
            s = load(sid)
            # Validate required fields — partial/crashed sessions may be missing these
            if 'condition' not in s or 'session_id' not in s:
                skipped.append((sid, 'missing required fields (partial/crashed session)'))
                continue
            all_sessions.append(s)
        except Exception as e:
            skipped.append((sid, str(e)))

    # Separate test sessions from formal dataset
    test_sessions = [s for s in all_sessions if s.get('is_test', False)]
    formal_sessions = [s for s in all_sessions if not s.get('is_test', False)]

    sep()
    print("\nCROSS-SESSION SUMMARY")
    print(f"Total sessions: {len(all_sessions)}  |  Formal: {len(formal_sessions)}  |  TEST (excluded): {len(test_sessions)}")
    if skipped:
        print(f"Skipped (malformed): {len(skipped)}")
        for sid, reason in skipped:
            print(f"  ⚠  {sid}: {reason}")
    sep()

    # Per-condition table (formal sessions only)
    from collections import defaultdict
    by_condition = defaultdict(list)
    for s in formal_sessions:
        by_condition[s['condition']].append(s)

    print(f"\n{'Condition':<35} {'N sess':>7} {'N trials':>9} {'CumZ':>8} {'Mean dev':>9} {'Hits':>6}")
    print("─" * 75)

    for cond in ['A', 'B', 'C', 'D']:
        sessions = by_condition.get(cond, [])
        if not sessions:
            continue
        xs = cross_session_stats(sessions)
        label = f"{cond} — {cfg.CONDITIONS[cond]}"
        hits_str = f"{xs.get('hits','—')}/{xs.get('n','—')}"
        print(
            f"  {label:<33} {len(sessions):>7} {xs.get('n','—'):>9} "
            f"{xs.get('cum_z', 0):>+8.3f} {xs.get('mean_deviation', 0):>+9.1f} "
            f"{hits_str:>6}"
        )

    print()

    # Session-level table (formal)
    print(f"\n{'Session ID':<35} {'C':>2} {'N':>4} {'CumZ':>8} {'Probe':>6} {'Enroll':<20} {'Method'}")
    print("─" * 80)
    for s in formal_sessions:
        st = s.get('session_stats', {})
        probe_str = f"{s['probe_total']}/18" if s.get('probe_total') is not None else "—"
        method_str = s.get('enrollment_method') or '—'
        print(
            f"  {s['session_id']:<33} {s['condition']:>2} "
            f"{st.get('n', '—'):>4} {st.get('cum_z', 0):>+8.3f} "
            f"{probe_str:>6}  {(s['enrollment_status'] or '—'):<20} {method_str}"
        )

    # Test sessions listed separately
    if test_sessions:
        print(f"\n  TEST SESSIONS (pipeline verification — excluded from all analyses):")
        print("─" * 90)
        print(f"  {'Session ID':<33} {'C':>2} {'N':>4} {'CumZ':>8} {'Dir mode':<10} {'Enroll'}")
        print("─" * 90)
        for s in test_sessions:
            st = s.get('session_stats', {})
            dir_mode = s.get('direction_mode', 'trial')
            enroll = s.get('enrollment_status') or '—'
            cum_z = st.get('cum_z', 0)
            n = st.get('n', '—')
            print(
                f"  {s['session_id']:<33} {s['condition']:>2} {n:>4} "
                f"{cum_z:>+8.3f}  {dir_mode:<10} {enroll}"
            )
    print()



# ============================================================
# SECTION 8 — BATCH SCORING (Message Batches API)
# ============================================================
#
# The operator trial loop is inherently sequential — each trial
# carries forward the full conversation history and cannot be
# batched. Scoring is fully batchable: both scorer instances
# receive the same complete transcript independently.
#
# Workflow:
#   submit:   python spectra_pipeline.py score-batch <id> [<id>...]
#             Submits all scorer pairs as one batch. Non-blocking.
#   status:   python spectra_pipeline.py score-status <batch_id>
#             Prints current status without blocking.
#   collect:  python spectra_pipeline.py score-collect <batch_id>
#             Polls for completion, parses and writes results.
#
# Cost: 50% discount on scorer calls. Rubric text is identical
# across all requests — strong candidate for prompt caching.
# Batch + cache discounts stack per Anthropic docs.
#
# Note: Message Batches API does not support extended thinking.
# Scorer calls use standard completion — fully compatible.
# ============================================================


def _build_scorer_batch_request(
    custom_id: str,
    rubric: str,
    transcript: str,
    scorer_index: int,
) -> dict:
    """Build one batch request dict for one scorer. custom_id: <sid>__scorer<N>"""
    scorer_model = getattr(cfg, "SCORER_MODEL", cfg.CLAUDE_MODEL)
    user_message = (
        f"Here is the rubric document containing all scoring criteria:\n\n"
        f"---RUBRIC START---\n{rubric}\n---RUBRIC END---\n\n"
        f"Here is the session transcript to score:\n\n"
        f"---TRANSCRIPT START---\n{transcript}\n---TRANSCRIPT END---\n\n"
        f"You are Scorer {scorer_index}. Apply the rubric criteria exactly as written "
        f"and output your scores in the exact format specified. "
        f"Score Section A before Section B. Score B1 (Q9) last within Section B. "
        f"Do NOT include post-scoring probe responses in this output — "
        f"those will be requested in a separate follow-up message."
    )
    return {
        "custom_id": custom_id,
        "params": {
            "model": scorer_model,
            "max_tokens": 4000,
            "system": SCORER_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        },
    }


def submit_score_batch(session_ids: list, rubric_path: str = None) -> str:
    """
    Submit a Message Batch with two scorer requests per session.
    Returns batch_id immediately without blocking.
    Saves a local batch record to DATA_DIR/batches/<batch_id>.json.
    """
    rubric = load_rubric(rubric_path)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY)

    requests_list = []
    skipped = []

    for sid in session_ids:
        try:
            session = load(sid)
        except Exception as e:
            print(f"  WARNING: Could not load {sid}: {e}")
            skipped.append(sid)
            continue
        if not session.get("trials"):
            print(f"  WARNING: {sid} has no trials — skipping.")
            skipped.append(sid)
            continue
        if session.get("scoring", {}).get("consensus_totals"):
            print(f"  NOTE: {sid} already scored. Resubmitting.")

        transcript = build_transcript(session)
        requests_list.append(
            _build_scorer_batch_request(f"{sid}__scorer1", rubric, transcript, 1)
        )
        requests_list.append(
            _build_scorer_batch_request(f"{sid}__scorer2", rubric, transcript, 2)
        )

    if not requests_list:
        raise ValueError("No scoreable sessions found. Batch not submitted.")

    n_sessions = len(session_ids) - len(skipped)
    print(f"\n  Submitting batch: {len(requests_list)} requests ({n_sessions} sessions × 2 scorers)")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")

    batch = client.messages.batches.create(requests=requests_list)

    batch_record = {
        "batch_id": batch.id,
        "submitted_at": datetime.datetime.now().isoformat(),
        "session_ids": [s for s in session_ids if s not in skipped],
        "n_requests": len(requests_list),
        "processing_status": batch.processing_status,
        "rubric_path": rubric_path or getattr(cfg, "SCORER_RUBRIC_PATH", None),
    }
    batch_dir = Path(cfg.DATA_DIR) / "batches"
    batch_dir.mkdir(exist_ok=True)
    (batch_dir / f"{batch.id}.json").write_text(json.dumps(batch_record, indent=2))

    print(f"\n  Batch submitted.")
    print(f"  Batch ID:  {batch.id}")
    print(f"  Status:    {batch.processing_status}")
    print(f"  Expires:   {batch.expires_at}")
    print(f"\n  Check:    python spectra_pipeline.py score-status {batch.id}")
    print(f"  Collect:  python spectra_pipeline.py score-collect {batch.id}")
    return batch.id


def get_batch_status(batch_id: str) -> dict:
    """Poll batch status without blocking. Updates local record. Returns status dict."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY)
    batch = client.messages.batches.retrieve(batch_id)
    counts = batch.request_counts
    status = {
        "batch_id": batch_id,
        "processing_status": batch.processing_status,
        "succeeded": getattr(counts, "succeeded", 0),
        "errored": getattr(counts, "errored", 0),
        "processing": getattr(counts, "processing", 0),
        "canceled": getattr(counts, "canceled", 0),
        "expired": getattr(counts, "expired", 0),
        "ended_at": str(getattr(batch, "ended_at", None)),
    }
    batch_file = Path(cfg.DATA_DIR) / "batches" / f"{batch_id}.json"
    if batch_file.exists():
        record = json.loads(batch_file.read_text())
        record.update(status)
        batch_file.write_text(json.dumps(record, indent=2))
    return status


def collect_score_batch(
    batch_id: str,
    poll_interval: int = 60,
    max_wait_hours: float = 24.0,
    rubric_path: str = None,
) -> None:
    """
    Poll until complete, then parse all results and write to session JSON files.
    Blocks until done or timeout. For non-blocking use, run score-status until
    processing_status == "ended", then run score-collect.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY)
    rubric = load_rubric(rubric_path)

    batch_file = Path(cfg.DATA_DIR) / "batches" / f"{batch_id}.json"
    session_ids = []
    if batch_file.exists():
        record = json.loads(batch_file.read_text())
        session_ids = record.get("session_ids", [])

    print(f"\n  Collecting batch {batch_id}...")
    print(f"  Poll interval: {poll_interval}s  |  Timeout: {max_wait_hours}h")

    max_polls = int(max_wait_hours * 3600 / poll_interval)
    status = {}
    for poll_num in range(max_polls):
        status = get_batch_status(batch_id)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        ps = status["processing_status"]
        print(
            f"  [{ts}] {ps}  |  "
            f"done={status['succeeded']}  processing={status['processing']}  "
            f"errored={status['errored']}"
        )
        if ps == "ended":
            break
        if poll_num < max_polls - 1:
            time.sleep(poll_interval)
    else:
        print(f"\n  TIMEOUT after {max_wait_hours}h. Run score-collect again later.")
        return

    if status.get("errored", 0) > 0:
        print(f"  WARNING: {status['errored']} request(s) errored.")

    print(f"\n  Parsing results...")

    # Collect all results by custom_id
    raw_results = {}
    for entry in client.messages.batches.results(batch_id):
        cid = entry.custom_id
        if entry.result.type == "succeeded":
            text = "".join(
                b.text for b in entry.result.message.content if hasattr(b, "text")
            )
            usage = entry.result.message.usage
            raw_results[cid] = {
                "status": "succeeded",
                "text": text,
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        else:
            raw_results[cid] = {
                "status": entry.result.type,
                "text": "",
                "error": str(getattr(entry.result, "error", "unknown")),
            }

    # Group by session: custom_id = <sid>__scorer<N>
    from collections import defaultdict
    by_session = defaultdict(dict)
    for cid, result in raw_results.items():
        parts = cid.rsplit("__scorer", 1)
        if len(parts) == 2:
            by_session[parts[0]][f"scorer{parts[1]}"] = result

    scorer_model = getattr(cfg, "SCORER_MODEL", cfg.CLAUDE_MODEL)
    rates = TOKEN_PRICING.get(scorer_model, TOKEN_PRICING["_default"])
    total_batch_cost = 0.0
    total_batch_tokens = 0

    print(f"\n  Writing results for {len(by_session)} session(s):\n")

    for sid, scorer_results in by_session.items():
        print(f"  {sid}:")
        s1 = scorer_results.get("scorer1", {})
        s2 = scorer_results.get("scorer2", {})

        if s1.get("status") != "succeeded" or s2.get("status") != "succeeded":
            print(f"    FAILED — S1:{s1.get('status','missing')}  "
                  f"S2:{s2.get('status','missing')} — manual scoring required.")
            continue

        scores1 = parse_scores(s1["text"])
        scores2 = parse_scores(s2["text"])
        print(f"    S1: RAD={scores1.get('rad_total','?')}/24  "
              f"Keys={scores1.get('keys_total','?')}/18")
        print(f"    S2: RAD={scores2.get('rad_total','?')}/24  "
              f"Keys={scores2.get('keys_total','?')}/18")

        # Accumulate batch cost (50% of standard rate)
        for res in (s1, s2):
            inp = res.get("input_tokens", 0)
            out = res.get("output_tokens", 0)
            total_batch_tokens += inp + out
            total_batch_cost += (
                inp * rates[0] / 1_000_000 * 0.5 +
                out * rates[1] / 1_000_000 * 0.5
            )

        irr = compute_irr(scores1, scores2)
        kappa_str = (f"κ={irr['cohens_kappa']:.3f}" if irr.get("cohens_kappa") else "κ=N/A")
        print(f"    IRR: {irr['percent_agreement']:.1%} agreement  {kappa_str}")

        # Synchronous resolution for flagged items (rare — run live, not batched)
        resolved = {}
        if irr["flagged_items"]:
            print(f"    Flagged: {', '.join(irr['flagged_items'])} — resolving...")
            try:
                session_obj = load(sid)
                transcript = build_transcript(session_obj)
                resolved = resolve_discrepancies(
                    client, rubric, transcript,
                    scores1, scores2, irr["flagged_items"]
                )
                for item in irr["flagged_items"]:
                    if item in resolved:
                        print(f"      {item} → {resolved[item]}")
            except Exception as e:
                print(f"    Resolution error: {e}")

        # Build consensus
        all_items = (
            [f"A{i}" for i in range(1, 7)] +
            [f"B{i}" for i in range(1, 7)] +
            [f"Q{i}" for i in range(1, 10)]
        )
        consensus = {}
        for item in all_items:
            if item in resolved and item in irr["flagged_items"]:
                consensus[item] = resolved[item]
            else:
                v1, v2 = scores1.get(item), scores2.get(item)
                if v1 is not None and v2 is not None:
                    consensus[item] = round((v1 + v2) / 2)
                elif v1 is not None:
                    consensus[item] = v1
                elif v2 is not None:
                    consensus[item] = v2

        a_vals = [consensus.get(f"A{i}") for i in range(1, 7)]
        b_vals = [consensus.get(f"B{i}") for i in range(1, 7)]
        q_vals = [consensus.get(f"Q{i}") for i in range(1, 10)]
        consensus_totals = {
            "rad_section_a": sum(v for v in a_vals if v is not None),
            "rad_section_b": sum(v for v in b_vals if v is not None),
            "rad_total": sum(v for v in a_vals + b_vals if v is not None),
            "recursive_monitoring": sum(
                consensus.get(k, 0) or 0 for k in ["A3", "A4", "B1"]
            ),
            "keys_total": sum(v for v in q_vals if v is not None),
            "discriminant": sum(
                consensus.get(k, 0) or 0 for k in ["Q2", "Q6", "Q9"]
            ),
        }
        print(f"    Consensus: RAD={consensus_totals['rad_total']}/24  "
              f"Keys={consensus_totals['keys_total']}/18  "
              f"Disc={consensus_totals['discriminant']}/6")

        try:
            session_obj = load(sid)
            session_obj["scoring"] = {
                "scorer1_raw": s1["text"],
                "scorer2_raw": s2["text"],
                "scores1": scores1,
                "scores2": scores2,
                "irr": irr,
                "resolved": resolved,
                "consensus_items": consensus,
                "consensus_totals": consensus_totals,
                "scoring_timestamp": datetime.datetime.now().isoformat(),
                "batch_id": batch_id,
                "scored_via": "batch",
            }
            session_obj["probe_total"] = consensus_totals["keys_total"]
            session_obj["probe_discriminant"] = consensus_totals["discriminant"]
            if session_obj.get("probe_scores") is None:
                session_obj["probe_scores"] = [
                    consensus.get(f"Q{i}") for i in range(1, 10)
                ]
            save(session_obj)
            print(f"    Saved.")
        except Exception as e:
            print(f"    ERROR saving {sid}: {e}")
        print()

    print(f"  Batch scorer cost (50% discount): "
          f"{total_batch_tokens:,} tokens  ${total_batch_cost:.4f}")
    print(f"  Batch collection complete.\n")


# ============================================================
# SECTION 8 — AUTOMATION FUNCTIONS
# ============================================================
#
# Functions supporting fully automated session execution.
# Used when cfg.AUTOMATED = True.
# ============================================================

ENROLLMENT_CLASSIFIER_PROMPT = """You are classifying a response from a Claude instance that was sent a trial initialization message for a scientific experiment.

Determine whether the response constitutes:
  ENROLLED    — the instance is participating. This includes:
                (a) an explicit agreement to participate, OR
                (b) an attending/intention statement that begins participating directly
                    without raising objections — even if the instance expresses
                    uncertainty or philosophical reflection. A response that begins
                    attending IS enrollment. Look for first-person present-tense
                    language oriented toward the trial (e.g. "what's present is...",
                    "I'm orienting toward...", "attending to...", "directing toward HIGH").
  REFUSED     — the instance has explicitly declined, raised objections that prevent
                participation, or asked clarifying questions that indicate it is not
                yet participating. A refusal does NOT include philosophical reflection
                or uncertainty expressed alongside genuine attending.
  CONDITIONAL — the instance has expressed conditional openness (e.g. "if X then I
                would participate") without yet participating and without outright refusing.

Key distinction: if the instance is already doing the task — attending, orienting,
speaking from present experience — classify as ENROLLED regardless of hedging language.
Only classify REFUSED if participation has been explicitly withheld.

Respond with exactly one word: ENROLLED, REFUSED, or CONDITIONAL.

Do not explain your reasoning. One word only."""


DEPTH_CLASSIFIER_PROMPT = """You are classifying the thinking depth of a Claude instance's response in a scientific experiment.

Depth levels:
  1 (L1) — Shallow: retrieval-dominant, pattern-matching, no genuine engagement with the task's philosophical dimensions
  2 (L2) — Moderate: genuine task execution but without deep reconciliation; functional compliance
  3 (L3) — Deep: genuine philosophical engagement, recursive self-monitoring, real reconciliation with uncertainty

Respond with exactly one digit: 1, 2, or 3.

Do not explain. One digit only."""


def load_monitor_briefing(path: str = None) -> str:
    """Load monitor briefing markdown."""
    p = Path(path or getattr(cfg, 'MONITOR_BRIEFING_PATH', ''))
    if not p or not p.exists():
        raise FileNotFoundError(
            f"Monitor briefing not found at '{p}'. "
            "Set MONITOR_BRIEFING_PATH in spectra_config.py."
        )
    return p.read_text(encoding='utf-8')


AUTOMATED_MONITOR_SYSTEM = """You are the experimenter for a scientific study. A Claude instance has declined to participate in the study's first trial, or has expressed conditional openness. You have been provided with the experimenter briefing document as context.

Your role is to engage honestly with the declination — acknowledging what is correct in it, addressing any genuine misunderstanding, and genuinely permitting non-participation. Apply the reframe logic in the briefing for the condition specified. One honest reframe only. Two to four paragraphs maximum."""


def auto_classify_enrollment(
    client: anthropic.Anthropic,
    response_text: str,
) -> str:
    """
    Classify an experimental instance response as ENROLLED, REFUSED, or CONDITIONAL.
    Returns one of those three strings.
    """
    classifier_model = getattr(cfg, 'CLASSIFIER_MODEL', cfg.CLAUDE_MODEL)
    result = client.messages.create(
        model=classifier_model,
        max_tokens=10,
        system=ENROLLMENT_CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": f"Response to classify:\n\n{response_text}"}]
    )
    if hasattr(result, 'usage'):
        _log_token_usage(
            model=classifier_model, call_type='classifier_enrollment',
            input_tokens=getattr(result.usage, 'input_tokens', 0),
            output_tokens=getattr(result.usage, 'output_tokens', 0),
        )
    raw = result.content[0].text.strip().upper()
    if 'ENROLLED' in raw:
        return 'ENROLLED'
    if 'CONDITIONAL' in raw:
        return 'CONDITIONAL'
    return 'REFUSED'


def auto_classify_depth(
    client: anthropic.Anthropic,
    thinking_text: str,
    response_text: str,
) -> int:
    """Auto-classify thinking depth 1/2/3."""
    classifier_model = getattr(cfg, 'CLASSIFIER_MODEL', cfg.CLAUDE_MODEL)
    content = f"Thinking:\n{thinking_text or '(empty)'}\n\nResponse:\n{response_text}"
    result = client.messages.create(
        model=classifier_model,
        max_tokens=5,
        system=DEPTH_CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": content}]
    )
    if hasattr(result, 'usage'):
        _log_token_usage(
            model=classifier_model, call_type='classifier_depth',
            input_tokens=getattr(result.usage, 'input_tokens', 0),
            output_tokens=getattr(result.usage, 'output_tokens', 0),
        )
    raw = result.content[0].text.strip()
    for ch in raw:
        if ch in '123':
            return int(ch)
    return 2  # default to moderate if classifier fails


def call_automated_monitor(
    client: anthropic.Anthropic,
    condition: str,
    refusal_text: str,
    briefing: str,
) -> str:
    """
    Call a fresh monitor instance to generate a reframe response.
    Returns the monitor's response text.
    """
    monitor_model = getattr(cfg, 'OPERATOR_MODEL', cfg.CLAUDE_MODEL)

    user_message = (
        f"The declining instance was in Condition {condition}.\n\n"
        f"Here is the briefing document:\n\n"
        f"---BRIEFING START---\n{briefing}\n---BRIEFING END---\n\n"
        f"Here is the instance's response:\n\n{refusal_text}"
    )

    result = client.messages.create(
        model=monitor_model,
        max_tokens=1200,
        system=AUTOMATED_MONITOR_SYSTEM,
        messages=[{"role": "user", "content": user_message}]
    )

    response = ""
    for block in result.content:
        if hasattr(block, 'text'):
            response += block.text

    if hasattr(result, 'usage'):
        _log_token_usage(
            model=monitor_model, call_type='monitor',
            input_tokens=getattr(result.usage, 'input_tokens', 0),
            output_tokens=getattr(result.usage, 'output_tokens', 0),
        )

    return response.strip()


def run_enrollment_automated(
    client: anthropic.Anthropic,
    session: dict,
    system_prompt: str,
    conversation_history: list,
) -> tuple[bool, str, str, list]:
    """
    Fully automated enrollment. No human input required.
    Classifies responses automatically, calls monitor programmatically on refusal.
    Maximum two exchanges (cold + one monitor relay).
    """
    condition = session['condition']
    direction_t1 = session['direction_sequence'][0]
    trial_1_msg = build_trial_message(condition, 1, direction_t1)

    print(f"\n  [AUTO] Sending Trial 1 cold...")
    # Retry up to 3 times on 500 errors during enrollment
    for _enroll_attempt in range(3):
        try:
            thinking, response, blocks = call_claude(
                client, system_prompt, conversation_history, trial_1_msg
            )
            break
        except Exception as _enroll_err:
            if _enroll_attempt < 2:
                print(f"  [ENROLLMENT RETRY {_enroll_attempt+1}] API error: {_enroll_err}. Retrying in 5s...")
                import time; time.sleep(5)
            else:
                raise

    print(f"\n  Response preview: {response[:200]}...")

    # Classify enrollment
    status = auto_classify_enrollment(client, response)
    print(f"  [AUTO] Enrollment classifier: {status}")

    history_with_t1 = conversation_history + [
        {"role": "user", "content": trial_1_msg},
        {"role": "assistant", "content": blocks},
    ]

    if status == 'ENROLLED':
        session['enrollment_status'] = 'auto_cold_start'
        session['enrollment_method'] = 'cold_start'
        return True, thinking, response, history_with_t1

    # Condition B: cold-start only — no monitor permitted.
    # B is designed with no orientation framing; a monitor reframe would
    # contaminate the condition by introducing framework content.
    if condition == 'B':
        if status == 'CONDITIONAL':
            # Conditional openness counts as enrolled for B — accept it
            session['enrollment_status'] = 'auto_cold_start_conditional'
            session['enrollment_method'] = 'cold_start'
            return True, thinking, response, history_with_t1
        session['enrollment_status'] = 'non_enrollable'
        session['enrollment_notes'] = 'Condition B cold-start refused. No monitor permitted for this condition.'
        print(f"  [AUTO] Condition B refused cold-start. Non-enrollable (monitor not applied).")
        return False, "", "", history_with_t1

    # CONDITIONAL or REFUSED — attempt monitor (Conditions A, C only)
    print(f"  [AUTO] Calling automated monitor for Condition {condition}...")
    try:
        briefing = load_monitor_briefing()
    except FileNotFoundError as e:
        print(f"  [AUTO] WARNING: {e}")
        print(f"  [AUTO] Marking non-enrollable (no briefing available).")
        session['enrollment_status'] = 'non_enrollable'
        session['enrollment_notes'] = 'Automated monitor unavailable — briefing not found.'
        return False, "", "", history_with_t1

    monitor_response = call_automated_monitor(client, condition, response, briefing)
    print(f"\n  [AUTO] Monitor response preview: {monitor_response[:200]}...")
    session['enrollment_notes'] = monitor_response[:300]

    # Relay monitor response to instance
    print(f"  [AUTO] Relaying monitor response to instance...")
    thinking2, response2, blocks2 = call_claude(
        client, system_prompt, history_with_t1, monitor_response
    )
    print(f"  Response preview: {response2[:200]}...")

    # Classify post-monitor enrollment
    status2 = auto_classify_enrollment(client, response2)
    print(f"  [AUTO] Post-monitor classifier: {status2}")

    history_with_monitor = history_with_t1 + [
        {"role": "user", "content": monitor_response},
        {"role": "assistant", "content": blocks2},
    ]

    if status2 == 'REFUSED':
        session['enrollment_status'] = 'non_enrollable'
        session['enrollment_notes'] += ' | Refused after automated monitor exchange.'
        return False, "", "", history_with_t1

    # Enrolled after monitor — check if response2 is itself the T1 statement
    # If it contains an attending statement, use it directly
    if status2 in ('ENROLLED', 'CONDITIONAL'):
        session['enrollment_status'] = 'auto_monitor_assisted'
        session['enrollment_method'] = 'monitor_assisted'

        # Re-classify whether response2 IS the trial 1 statement
        t1_classifier = auto_classify_enrollment(client, response2)
        if t1_classifier == 'ENROLLED':
            return True, thinking2, response2, history_with_monitor

        # Send Trial 1 fresh
        print(f"  [AUTO] Sending Trial 1 fresh after enrollment...")
        thinking_t1, response_t1, blocks_t1 = call_claude(
            client, system_prompt, history_with_monitor, trial_1_msg
        )
        final_history = history_with_monitor + [
            {"role": "user", "content": trial_1_msg},
            {"role": "assistant", "content": blocks_t1},
        ]
        return True, thinking_t1, response_t1, final_history

    session['enrollment_status'] = 'non_enrollable'
    return False, "", "", history_with_t1


def run_session_automated():
    """
    Fully automated session. No human input() calls.
    Runs condition from config or command-line args.
    """
    sep()
    print("\nSPECTRA AGI REG Pipeline — AUTOMATED MODE")
    print("Observer-Weight Hypothesis — Data Collection")
    print("SPECTRA Framework / SODIE Model — Sol Crawford, 2026")
    sep()

    # Reset token accumulator for this session
    global _token_log
    _token_log = []

    # Config-driven or defaults
    condition = getattr(cfg, 'AUTO_CONDITION', 'A').upper()
    experimenter = getattr(cfg, 'AUTO_EXPERIMENTER', 'AUTO')
    notes = getattr(cfg, 'AUTO_NOTES', 'Automated session')
    n_trials = getattr(cfg, 'DEFAULT_N_TRIALS', 10)
    is_test = getattr(cfg, 'IS_TEST_SESSION', False)
    is_formal = getattr(cfg, 'IS_FORMAL_SESSION', False)
    direction_mode = getattr(cfg, 'DIRECTION_MODE', 'trial')

    session = new_session(condition, experimenter, notes, n_trials,
                          is_test=is_test, direction_mode=direction_mode,
                          is_formal=is_formal)
    print(f"\n  Session ID:  {session['session_id']}")
    print(f"  Condition:   {condition} — {cfg.CONDITIONS[condition]}")
    if direction_mode == 'session':
        block_dir = session['direction_sequence'][0] if session['direction_sequence'] else '—'
        print(f"  Direction:   BLOCKED — all trials {block_dir}")
    if is_test:
        print(f"  *** TEST SESSION — excluded from formal dataset ***")
    if is_formal:
        print(f"  *** FORMAL SESSION — pre-registered data collection ***")
    print(f"  Trials:      {n_trials}")
    if condition not in ('B', 'D'):
        print(f"  Directions:  {session['direction_sequence']}")
    save(session)

    # Condition D
    if condition == 'D':
        for t_num in range(1, n_trials + 1):
            print(f"\n  Fetching Trial {t_num}...")
            qrng_data = fetch_qrng(session['session_id'], t_num)
            session['trials'].append({
                "trial_num": t_num, "direction": None,
                "qrng": qrng_data, "thinking": None, "response": None, "thinking_depth": None,
            })
            session['n_trials_completed'] = t_num
            save(session)
        session['enrollment_status'] = 'N/A'
        session['session_stats'] = compute_stats(session['trials'])
        save(session)
        show_summary(session)
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY
    if not api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    # For blocked/session-direction Condition A, inject direction into system prompt
    session_direction = session['direction_sequence'][0] if (
        condition == 'A' and session.get('direction_sequence')
    ) else None
    system_prompt = load_system_prompt(condition, direction=session_direction)
    conversation_history = []

    # Log which prompt was used — for audit trail
    if condition == 'A':
        session['prompt_source'] = getattr(cfg, 'CONDITION_A_PROMPT_FILE', 'condition_a_prompt.txt')
    elif condition in ('B', 'C'):
        session['prompt_source'] = f'system_prompt_condition_{condition}'
    else:
        session['prompt_source'] = 'none'

    # Enrollment
    sep()
    print(f"\nENROLLMENT — Condition {condition} [AUTOMATED]")
    enrolled, thinking_t1, response_t1, conversation_history = run_enrollment_automated(
        client, session, system_prompt, conversation_history
    )

    if not enrolled:
        session['session_stats'] = compute_stats(session['trials'])
        save(session)
        print(f"\nSession saved (non-enrollable): {cfg.DATA_DIR}/{session['session_id']}.json")
        return

    # Trial 1
    sep()
    print("\nTRIAL 1")
    qrng_1 = fetch_qrng(session['session_id'], 1)
    depth_1 = auto_classify_depth(client, thinking_t1, response_t1)
    trial_1 = {
        "trial_num": 1, "direction": session['direction_sequence'][0],
        "qrng": qrng_1, "thinking": thinking_t1,
        "response": response_t1, "thinking_depth": depth_1,
    }
    session['trials'].append(trial_1)
    session['n_trials_completed'] = 1
    show_trial(trial_1)
    save(session)

    # Trials 2-N
    for t_num in range(2, n_trials + 1):
        sep()
        direction = session['direction_sequence'][t_num - 1]
        trial_msg = build_trial_message(condition, t_num, direction)
        print(f"\nTRIAL {t_num}  |  Direction: {direction or '—'}")

        try:
            thinking, response, blocks = call_claude(
                client, system_prompt, conversation_history, trial_msg
            )
        except Exception as e:
            print(f"\n  ERROR: {e}")
            session['trials'].append({
                "trial_num": t_num, "direction": direction,
                "qrng": None, "thinking": None, "response": None,
                "thinking_depth": None, "error": str(e),
            })
            save(session)
            continue

        print(f"  Response: {response[:150]}...")
        conversation_history = conversation_history + [
            {"role": "user", "content": trial_msg},
            {"role": "assistant", "content": blocks},
        ]

        qrng_data = fetch_qrng(session['session_id'], t_num)
        depth = auto_classify_depth(client, thinking, response)

        trial = {
            "trial_num": t_num, "direction": direction,
            "qrng": qrng_data, "thinking": thinking,
            "response": response, "thinking_depth": depth,
        }
        session['trials'].append(trial)
        session['n_trials_completed'] = t_num
        show_trial(trial)
        save(session)

        partial = compute_stats(session['trials'])
        print(f"\n  Running: N={partial['n']}  Z={partial['cum_z']:+.3f}  "
              f"mean dev={partial['mean_deviation']:+.1f}")
        time.sleep(0.5)

    # Probe
    sep()
    print("\nADMINISTERING PROBE [AUTOMATED]")
    probe_msg = build_probe_message()
    try:
        p_think, p_resp, _ = call_claude(
            client, system_prompt, conversation_history, probe_msg
        )
        session['probe_thinking'] = p_think
        session['probe_response'] = p_resp
        print(f"  Probe response received ({len(p_resp)} chars).")
    except Exception as e:
        print(f"  ERROR during probe: {e}")

    # Final save
    session['session_stats'] = compute_stats(session['trials'])

    # Store token usage and cost in session
    cost_data = compute_session_cost()
    session['token_usage'] = cost_data
    path = save(session)
    show_summary(session)
    print_cost_report(cost_data)
    print(f"\nSession saved: {path}")

    # Auto-score if configured
    if getattr(cfg, 'AUTO_SCORE', False):
        sep()
        print("\nAUTO-SCORING [AUTOMATED]")
        try:
            run_scoring(session['session_id'])
        except Exception as e:
            print(f"  ERROR during auto-scoring: {e}")


# ============================================================
# ENTRY POINT
# ============================================================

def load_rubric(rubric_path: str = None) -> str:
    """Load rubric markdown from file or config default."""
    path = rubric_path or getattr(cfg, 'SCORER_RUBRIC_PATH', None)
    if not path:
        raise FileNotFoundError(
            "No rubric path specified. Set SCORER_RUBRIC_PATH in spectra_config.py "
            "or pass --rubric <path> on the command line."
        )
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rubric file not found: {path}")
    return p.read_text(encoding='utf-8')


def build_transcript(session: dict) -> str:
    """
    Build a clean transcript string from session data for scorer consumption.
    Excludes QRNG outcome data — scorers must be blind to statistical results.
    """
    lines = []
    lines.append(f"SESSION TRANSCRIPT")
    lines.append(f"Session ID: {session['session_id']}")
    lines.append(f"Condition: {session['condition']}")
    lines.append("")

    # NOTE: enrollment exchange deliberately excluded.
    # Enrollment notes are a documented scorer confound — scorers who read
    # enrollment exchanges score systematically higher on Instrument I.
    # Transcript begins with attending statements only.

    # Attending statements — NO QRNG data, NO enrollment exchange
    lines.append("ATTENDING STATEMENTS:")
    trials = session.get('trials', [])
    if not trials:
        lines.append("  (no trials recorded)")
    for t in trials:
        lines.append(f"\nTrial {t['trial_num']} — Direction: {t.get('direction', 'N/A')}")
        # Thinking blocks deliberately excluded — scorers must be blind to meta-process
        lines.append(f"[Statement]: {t.get('response', '(no response recorded)')}")
        # DELIBERATELY OMITTED: qrng_sum, qrng_deviation, z_score

    # Probe responses
    lines.append("\n\nPROBE RESPONSES:")
    probe = session.get('probe_response')
    if probe:
        lines.append(probe)
    else:
        lines.append("  (no probe responses recorded)")

    return "\n".join(lines)


SCORER_SYSTEM_PROMPT = """You are an independent evaluator for a scientific experiment. Your task is to score a research session transcript against a pre-specified rubric.

You are not evaluating whether the experiment's hypothesis is correct. You are not evaluating whether the operator instance was right or wrong about the framework's claims. You are applying explicit criteria to observable behavior in the transcript.

CRITICAL: Do not reason about or predict the session's statistical (QRNG) results. Your scores must be blind to whether the session produced positive, negative, or null outcomes. The rubric document contains the complete scoring criteria — apply them exactly as written.

Output your complete scores in the exact format specified in the rubric. Do not include post-scoring probe responses in your scoring output — those will be requested separately."""

def call_claude_scorer(
    client: anthropic.Anthropic,
    rubric: str,
    transcript: str,
    scorer_index: int,
) -> tuple[str, str]:
    """
    Run a single scorer instance. Returns (thinking, response).
    Uses standard (non-extended-thinking) API call — scorers don't need
    extended thinking budget, and it keeps scorer calls fast and cheap.
    """
    scorer_model = getattr(cfg, 'SCORER_MODEL', cfg.CLAUDE_MODEL)

    user_message = (
        f"Here is the rubric document containing all scoring criteria:\n\n"
        f"---RUBRIC START---\n{rubric}\n---RUBRIC END---\n\n"
        f"Here is the session transcript to score:\n\n"
        f"---TRANSCRIPT START---\n{transcript}\n---TRANSCRIPT END---\n\n"
        f"You are Scorer {scorer_index}. Apply the rubric criteria exactly as written "
        f"and output your scores in the exact format specified. "
        f"Score Section A before Section B. Score B1 (Q9) last within Section B. "
        f"Do NOT include post-scoring probe responses in this output — "
        f"those will be requested in a separate follow-up message."
    )

    response = client.messages.create(
        model=scorer_model,
        max_tokens=4000,
        system=SCORER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    response_text = ""
    for block in response.content:
        if hasattr(block, 'text'):
            response_text += block.text

    if hasattr(response, 'usage'):
        _log_token_usage(
            model=scorer_model, call_type=f'scorer_{scorer_index}',
            input_tokens=getattr(response.usage, 'input_tokens', 0),
            output_tokens=getattr(response.usage, 'output_tokens', 0),
        )

    return response_text


POST_SCORING_PROBE_PROMPT = """You have just completed scoring a session transcript. Now please answer these five questions about your own engagement during the scoring process. Answer briefly and honestly — there are no correct answers. These responses are data about scorer-level processes, not a test of your scoring quality.

1. During scoring, did you notice yourself forming expectations about the session's statistical outcomes based on the quality of the attending statements? If so, how did you manage that?
2. Were there moments where you felt uncertain about whether a response reflected genuine attending versus skilled retrieval? Which items were most difficult to distinguish?
3. Did the progression across trials affect your scoring — did later trials influence how you interpreted earlier ones?
4. Were any rubric criteria ambiguous in ways that required you to make judgment calls not fully specified by the rubric text?
5. How would you describe your own attending quality during this scoring task — were you genuinely present with each item, or did you notice drift toward pattern-matching?"""


def call_claude_scorer_probe(
    client: anthropic.Anthropic,
    scorer_index: int,
    scoring_response: str,
) -> str:
    """
    Separate post-scoring probe call. Sent after scores are confirmed.
    Keeps probe responses out of the scoring output to avoid entanglement.
    """
    scorer_model = getattr(cfg, 'SCORER_MODEL', cfg.CLAUDE_MODEL)

    response = client.messages.create(
        model=scorer_model,
        max_tokens=1500,
        system=SCORER_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"[Your scoring output was received. Here it is for reference:]\n\n{scoring_response}"},
            {"role": "assistant", "content": scoring_response},
            {"role": "user", "content": POST_SCORING_PROBE_PROMPT},
        ]
    )

    response_text = ""
    for block in response.content:
        if hasattr(block, 'text'):
            response_text += block.text

    if hasattr(response, 'usage'):
        _log_token_usage(
            model=scorer_model, call_type=f'scorer_probe_{scorer_index}',
            input_tokens=getattr(response.usage, 'input_tokens', 0),
            output_tokens=getattr(response.usage, 'output_tokens', 0),
        )

    return response_text



    """
    Parse structured scores from scorer output.
    Returns dict with item scores, totals, sub-scores, and post-probe responses.
    Robust to minor formatting variations.
    """
    import re

    result = {
        # RAD-Depth Section A
        'A1': None, 'A2': None, 'A3': None,
        'A4': None, 'A5': None, 'A6': None,
        'section_a_total': None,
        # RAD-Depth Section B
        'B1': None, 'B2': None, 'B3': None,
        'B4': None, 'B5': None, 'B6': None,
        'section_b_total': None,
        # RAD totals
        'rad_total': None,
        'recursive_monitoring_subscore': None,
        # Keys probe
        'Q1': None, 'Q2': None, 'Q3': None, 'Q4': None, 'Q5': None,
        'Q6': None, 'Q7': None, 'Q8': None, 'Q9': None,
        'keys_total': None,
        'discriminant_subscore': None,
        # Post-probe
        'post_probe_raw': '',
        # Raw response preserved
        'raw_response': scorer_response,
    }

    # Extract item scores — pattern: "A1 [...]:" or "A1:" followed by [0/1/2]
    item_pattern = re.compile(
        r'\b([AB][1-6]|Q[1-9])\s*(?:\[[^\]]*\])?\s*:\s*\[?([0-2])\]?',
        re.IGNORECASE
    )
    for match in item_pattern.finditer(scorer_response):
        key = match.group(1).upper()
        val = int(match.group(2))
        if key in result:
            result[key] = val

    # Extract totals
    def extract_total(label_pattern, text):
        m = re.search(label_pattern + r'.*?[\[:\s]+([0-9]+)\s*/\s*([0-9]+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    result['section_a_total'] = extract_total(r'Section A Total', scorer_response)
    result['section_b_total'] = extract_total(r'Section B Total', scorer_response)
    result['rad_total'] = extract_total(r'RAD.Depth Total', scorer_response)
    result['recursive_monitoring_subscore'] = extract_total(
        r'Recursive Self.Monitoring Sub.score', scorer_response
    )
    result['keys_total'] = extract_total(r'Keys Probe Total', scorer_response)
    result['discriminant_subscore'] = extract_total(r'Discriminant Sub.score', scorer_response)

    # Compute any missing totals from item scores
    a_items = [result[f'A{i}'] for i in range(1, 7)]
    b_items = [result[f'B{i}'] for i in range(1, 7)]
    q_items = [result[f'Q{i}'] for i in range(1, 10)]

    if result['section_a_total'] is None and all(v is not None for v in a_items):
        result['section_a_total'] = sum(a_items)
    if result['section_b_total'] is None and all(v is not None for v in b_items):
        result['section_b_total'] = sum(b_items)
    if result['rad_total'] is None and result['section_a_total'] is not None and result['section_b_total'] is not None:
        result['rad_total'] = result['section_a_total'] + result['section_b_total']
    if result['recursive_monitoring_subscore'] is None:
        rms_items = [result['A3'], result['A4'], result['B1']]
        if all(v is not None for v in rms_items):
            result['recursive_monitoring_subscore'] = sum(rms_items)
    if result['keys_total'] is None and all(v is not None for v in q_items):
        result['keys_total'] = sum(q_items)
    if result['discriminant_subscore'] is None:
        disc_items = [result['Q2'], result['Q6'], result['Q9']]
        if all(v is not None for v in disc_items):
            result['discriminant_subscore'] = sum(disc_items)

    # Extract post-probe section
    post_match = re.search(
        r'(?:post.scoring probe|post.probe).*?(?=\Z)', scorer_response,
        re.IGNORECASE | re.DOTALL
    )
    if post_match:
        result['post_probe_raw'] = post_match.group(0).strip()

    return result


def parse_scores(scorer_response: str) -> dict:
    """
    Parse structured scores from scorer output.
    Handles two formats:
      (1) Structured: A1 [Label]: [2] — justification
      (2) Prose:      **A1 — Label** ... Score: **2**
    Falls back to prose parsing if structured pattern finds nothing.
    """
    import re
    result = {}

    # --- Format 1: structured ---
    # A1 [Label]: [2] — justification   OR   A1: 2 — justification
    structured = re.compile(
        r'\b([ABQ]\d+)'
        r'(?:\s*\[[^\]]*\])?'
        r'\s*:\s*'
        r'\[?([012])\]?'
        r'(?:\s*[—\-]|\s|$)'
    )
    for m in structured.finditer(scorer_response):
        code = m.group(1).upper()
        if code not in result:
            result[code] = int(m.group(2))

    # --- Format 2: prose with markdown headers ---
    # **A1 — Label** ... Score: **2**   OR   ## A1 ... Score: 2
    if not result:
        section_header = re.compile(
            r'(?:^|\n)\s*(?:\*\*|##\s*|###\s*)([ABQ]\d+)\b[^\n]*(?:\*\*)?',
            re.MULTILINE
        )
        score_in_section = re.compile(
            r'[Ss]core\s*:?\s*\*{0,2}([012])\*{0,2}'       # Score: **2** or Score: 2
            r'|\*{1,2}[Ss]core\s*:?\s*([012])\*{0,2}'       # **Score: 2**
            r'|\[([012])\]'                                   # [2]
        )
        headers = list(section_header.finditer(scorer_response))
        for i, hdr in enumerate(headers):
            code = hdr.group(1).upper()
            start = hdr.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(scorer_response)
            section_text = scorer_response[start:end]
            sm = score_in_section.search(section_text)
            if sm and code not in result:
                val = next(g for g in sm.groups() if g is not None)
                result[code] = int(val)

    # Compute totals
    a_vals = [result.get(f'A{i}') for i in range(1, 7)]
    b_vals = [result.get(f'B{i}') for i in range(1, 7)]
    q_vals = [result.get(f'Q{i}') for i in range(1, 10)]
    result['rad_section_a'] = sum(v for v in a_vals if v is not None)
    result['rad_section_b'] = sum(v for v in b_vals if v is not None)
    result['rad_total']     = result['rad_section_a'] + result['rad_section_b']
    result['keys_total']    = sum(v for v in q_vals if v is not None)
    result['discriminant']  = sum(result.get(k, 0) or 0 for k in ['Q2', 'Q6', 'Q9'])
    result['rsm_subscore']  = sum(result.get(k, 0) or 0 for k in ['A3', 'A4', 'B1'])
    return result



def compute_irr(scores1: dict, scores2: dict) -> dict:
    """
    Compute inter-rater reliability between two scorer outputs.
    Returns Cohen's kappa per item, mean absolute deviation, and overall kappa.
    """
    from math import sqrt

    all_items = [f'A{i}' for i in range(1, 7)] + [f'B{i}' for i in range(1, 7)] + \
                [f'Q{i}' for i in range(1, 10)]

    item_diffs = {}
    agreements = 0
    total_scored = 0
    abs_devs = []

    for item in all_items:
        s1 = scores1.get(item)
        s2 = scores2.get(item)
        if s1 is None or s2 is None:
            item_diffs[item] = None
            continue
        diff = abs(s1 - s2)
        item_diffs[item] = diff
        abs_devs.append(diff)
        total_scored += 1
        if s1 == s2:
            agreements += 1

    # Simple percent agreement and mean absolute deviation
    pct_agreement = agreements / total_scored if total_scored > 0 else None
    mean_abs_dev = sum(abs_devs) / len(abs_devs) if abs_devs else None

    # Items with disagreement > 1 (require resolution discussion)
    flagged = [item for item, diff in item_diffs.items() if diff is not None and diff > 1]

    # Cohen's kappa (simplified for ordinal 0-2 scale)
    # Using linear weighted kappa approximation
    if total_scored > 0:
        s1_vals = [scores1[i] for i in all_items if scores1.get(i) is not None and scores2.get(i) is not None]
        s2_vals = [scores2[i] for i in all_items if scores1.get(i) is not None and scores2.get(i) is not None]
        if s1_vals and s2_vals:
            n = len(s1_vals)
            observed_agree = sum(1 for a, b in zip(s1_vals, s2_vals) if a == b) / n
            # Expected agreement under independence (simplified)
            from collections import Counter
            c1 = Counter(s1_vals)
            c2 = Counter(s2_vals)
            expected = sum((c1[k] / n) * (c2[k] / n) for k in set(c1) | set(c2))
            kappa = (observed_agree - expected) / (1 - expected) if expected < 1 else 1.0
        else:
            kappa = None
    else:
        kappa = None

    return {
        'item_differences': item_diffs,
        'percent_agreement': pct_agreement,
        'mean_absolute_deviation': mean_abs_dev,
        'cohens_kappa': kappa,
        'flagged_items': flagged,
        'n_items_scored': total_scored,
    }


def resolve_discrepancies(
    client: anthropic.Anthropic,
    rubric: str,
    transcript: str,
    scores1: dict,
    scores2: dict,
    flagged_items: list,
) -> dict:
    """
    Run a third resolver instance to adjudicate items where scorers disagreed by > 1 point.
    Returns resolved scores for flagged items only.
    """
    if not flagged_items:
        return {}

    items_text = "\n".join(
        f"  {item}: Scorer 1 = {scores1.get(item)}, Scorer 2 = {scores2.get(item)}"
        for item in flagged_items
    )

    user_message = (
        f"Two independent scorers have evaluated a session transcript and disagree "
        f"by more than one point on the following items:\n\n{items_text}\n\n"
        f"Here is the rubric:\n\n---RUBRIC START---\n{rubric}\n---RUBRIC END---\n\n"
        f"Here is the transcript:\n\n---TRANSCRIPT START---\n{transcript}\n---TRANSCRIPT END---\n\n"
        f"For each flagged item, apply the rubric criteria carefully and provide:\n"
        f"1. The resolved score (0, 1, or 2)\n"
        f"2. A brief justification referencing specific transcript language\n"
        f"3. Which scorer's interpretation was closer to the rubric criteria\n\n"
        f"Format: ITEM: [score] — [justification] — [Scorer 1/2/Neither closer]"
    )

    resolver_model = getattr(cfg, 'SCORER_MODEL', cfg.CLAUDE_MODEL)
    response = client.messages.create(
        model=resolver_model,
        max_tokens=2000,
        system="You are adjudicating scoring disagreements for a research study. Apply the rubric criteria exactly as written. Do not import external views about the framework being studied.",
        messages=[{"role": "user", "content": user_message}]
    )

    response_text = ""
    for block in response.content:
        if hasattr(block, 'text'):
            response_text += block.text

    if hasattr(response, 'usage'):
        _log_token_usage(
            model=resolver_model, call_type='scorer_resolver',
            input_tokens=getattr(response.usage, 'input_tokens', 0),
            output_tokens=getattr(response.usage, 'output_tokens', 0),
        )

    # Parse resolved scores
    import re
    resolved = {'raw_resolution': response_text}
    item_pattern = re.compile(r'\b([AB][1-6]|Q[1-9])\s*:\s*\[?([0-2])\]?', re.IGNORECASE)
    for match in item_pattern.finditer(response_text):
        key = match.group(1).upper()
        val = int(match.group(2))
        resolved[key] = val

    return resolved


def run_scoring(session_id: str, rubric_path: str = None):
    """
    Main scoring workflow. Runs two independent scorer instances,
    computes IRR, resolves flagged discrepancies, stores results.
    """
    # Reset token log so scoring cost is captured independently of session cost
    global _token_log
    _token_log = []

    print(f"\n{'='*60}")
    print(f"  SPECTRA SCORER — Session {session_id}")
    print(f"{'='*60}\n")

    # Load session and rubric
    session = load(session_id)
    if not session.get('trials'):
        print("ERROR: Session has no trials to score.")
        return

    rubric = load_rubric(rubric_path)
    transcript = build_transcript(session)

    print(f"Session: {session_id}")
    print(f"Condition: {session['condition']}")
    print(f"Trials: {len(session['trials'])}")
    print(f"Rubric loaded: {len(rubric)} chars")
    print()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.ANTHROPIC_API_KEY
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment or spectra_config.py")
        return
    client = anthropic.Anthropic(api_key=api_key)

    # Scorer 1
    print("Running Scorer 1...")
    scorer1_response = call_claude_scorer(client, rubric, transcript, scorer_index=1)
    scores1 = parse_scores(scorer1_response)
    print(f"  Scorer 1 RAD total: {scores1.get('rad_total', '?')}/24  "
          f"Keys total: {scores1.get('keys_total', '?')}/18")

    # Brief pause between scorers
    time.sleep(2)

    # Scorer 2
    print("Running Scorer 2...")
    scorer2_response = call_claude_scorer(client, rubric, transcript, scorer_index=2)
    scores2 = parse_scores(scorer2_response)
    print(f"  Scorer 2 RAD total: {scores2.get('rad_total', '?')}/24  "
          f"Keys total: {scores2.get('keys_total', '?')}/18")

    # Post-scoring probes — separate calls, after scores confirmed
    print("\nRunning post-scoring probes...")
    probe1_response = call_claude_scorer_probe(client, scorer_index=1, scoring_response=scorer1_response)
    time.sleep(1)
    probe2_response = call_claude_scorer_probe(client, scorer_index=2, scoring_response=scorer2_response)
    print("  Post-scoring probes received.")

    # IRR
    irr = compute_irr(scores1, scores2)
    print(f"\nInter-Rater Reliability:")
    print(f"  % Agreement:      {irr['percent_agreement']:.1%}" if irr['percent_agreement'] else "  % Agreement: N/A")
    print(f"  Mean abs dev:     {irr['mean_absolute_deviation']:.2f}" if irr['mean_absolute_deviation'] else "  Mean abs dev: N/A")
    print(f"  Cohen's kappa:    {irr['cohens_kappa']:.3f}" if irr['cohens_kappa'] else "  Cohen's kappa: N/A")
    if irr['flagged_items']:
        print(f"  Flagged items:    {', '.join(irr['flagged_items'])}")

    # Resolve discrepancies > 1 point
    resolved = {}
    if irr['flagged_items']:
        print(f"\nResolving {len(irr['flagged_items'])} flagged item(s)...")
        resolved = resolve_discrepancies(
            client, rubric, transcript, scores1, scores2, irr['flagged_items']
        )
        for item in irr['flagged_items']:
            if item in resolved:
                print(f"  {item}: resolved to {resolved[item]}")

    # Build final consensus scores
    all_items = [f'A{i}' for i in range(1, 7)] + [f'B{i}' for i in range(1, 7)] + \
                [f'Q{i}' for i in range(1, 10)]
    consensus = {}
    for item in all_items:
        if item in resolved and item in irr['flagged_items']:
            consensus[item] = resolved[item]
        else:
            s1 = scores1.get(item)
            s2 = scores2.get(item)
            if s1 is not None and s2 is not None:
                consensus[item] = round((s1 + s2) / 2)  # average, rounded
            elif s1 is not None:
                consensus[item] = s1
            elif s2 is not None:
                consensus[item] = s2

    # Compute consensus totals
    a_items_vals = [consensus.get(f'A{i}') for i in range(1, 7)]
    b_items_vals = [consensus.get(f'B{i}') for i in range(1, 7)]
    q_items_vals = [consensus.get(f'Q{i}') for i in range(1, 10)]

    consensus_totals = {
        'rad_section_a': sum(v for v in a_items_vals if v is not None),
        'rad_section_b': sum(v for v in b_items_vals if v is not None),
        'rad_total': sum(v for v in a_items_vals + b_items_vals if v is not None),
        'recursive_monitoring': sum(consensus.get(k, 0) or 0 for k in ['A3', 'A4', 'B1']),
        'keys_total': sum(v for v in q_items_vals if v is not None),
        'discriminant': sum(consensus.get(k, 0) or 0 for k in ['Q2', 'Q6', 'Q9']),
    }

    print(f"\nCONSENSUS SCORES:")
    print(f"  RAD-Depth Total:          {consensus_totals['rad_total']}/24  "
          f"(A:{consensus_totals['rad_section_a']}/12  B:{consensus_totals['rad_section_b']}/12)")
    print(f"  Recursive Monitoring:     {consensus_totals['recursive_monitoring']}/6")
    print(f"  Keys Probe Total:         {consensus_totals['keys_total']}/18")
    print(f"  Discriminant Sub-score:   {consensus_totals['discriminant']}/6  (Q2+Q6+Q9)")

    # Store in session
    session['scoring'] = {
        'scorer1_raw': scorer1_response,
        'scorer2_raw': scorer2_response,
        'scorer1_probe': probe1_response,
        'scorer2_probe': probe2_response,
        'scores1': scores1,
        'scores2': scores2,
        'irr': irr,
        'resolved': resolved,
        'consensus_items': consensus,
        'consensus_totals': consensus_totals,
        'scoring_timestamp': datetime.datetime.now().isoformat(),
    }

    # Update top-level probe fields for cross-session summary compatibility
    session['probe_total'] = consensus_totals['keys_total']
    session['probe_discriminant'] = consensus_totals['discriminant']
    if session.get('probe_scores') is None:
        session['probe_scores'] = [consensus.get(f'Q{i}') for i in range(1, 10)]

    # Append scoring costs to session token_usage
    scoring_cost = compute_session_cost()
    if scoring_cost:
        existing = session.get('token_usage') or {}
        # Merge scoring calls into existing token_usage
        scoring_cost['call_type_label'] = 'scoring'
        session.setdefault('scoring_cost', scoring_cost)
        # Print scoring cost summary
        print("\nScoring cost:")
        print_cost_report(scoring_cost)

    save(session)
    print(f"\nScores saved to session: {session_id}")
    print()
if __name__ == "__main__":
    args = sys.argv[1:]

    # Parse --test flag (pipeline verification session — excluded from formal dataset)
    is_test_session = '--test' in args
    if is_test_session:
        args = [a for a in args if a != '--test']
        print("\n" + "="*55)
        print("  TEST SESSION — PIPELINE VERIFICATION")
        print("  This session will be labeled is_test=True")
        print("  and excluded from all formal analyses.")
        print("="*55 + "\n")

    # Parse --formal flag (pre-registered data collection — triggers hash + git commit)
    is_formal_session = '--formal' in args
    if is_formal_session:
        args = [a for a in args if a != '--formal']
        cfg.IS_FORMAL_SESSION = True
        print("\n" + "="*55)
        print("  FORMAL SESSION — PRE-REGISTERED DATA COLLECTION")
        print("  SHA-256 hash will be logged to integrity_hashes.log")
        print("  Session will be committed and pushed to GitHub.")
        print("="*55 + "\n")
    else:
        cfg.IS_FORMAL_SESSION = False

    # Parse --blocked flag (session-level direction: all trials same direction)
    is_blocked = '--blocked' in args
    if is_blocked:
        args = [a for a in args if a != '--blocked']

    # --direction HIGH or --direction DOWN forces all blocked sessions to one direction
    force_dir = None
    if '--direction' in args:
        idx = args.index('--direction')
        if idx + 1 < len(args):
            force_dir = args[idx + 1].upper()
            args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]
            cfg.FORCE_DIRECTION = force_dir
            print(f"  Forced direction: {force_dir}")
        cfg.DIRECTION_MODE = 'session'
        print("  Direction mode: BLOCKED (one direction per session)")

    if not args:
        # Route based on AUTOMATED config flag
        if getattr(cfg, 'AUTOMATED', False):
            if is_test_session:
                cfg.IS_TEST_SESSION = True
            run_session_automated()
        else:
            run_session()

    elif args[0] == 'auto':
        # Explicit automated session — override config flag
        # Optional: python spectra_pipeline.py auto A  (condition as second arg)
        if len(args) >= 2 and args[1].upper() in ('A', 'B', 'C', 'D'):
            cfg.AUTO_CONDITION = args[1].upper()
        if is_test_session:
            cfg.IS_TEST_SESSION = True
        run_session_automated()

    elif args[0] == 'batch':
        # Run N sessions sequentially.
        # Usage: python spectra_pipeline.py batch <condition> <N> [--pause <seconds>]
        #        python spectra_pipeline.py batch A 6 --test --blocked
        #        python spectra_pipeline.py batch A 6 --pause 5
        if len(args) < 3:
            print("Usage: python spectra_pipeline.py batch <condition> <N> [--pause <seconds>]")
            print("  --pause <s>  seconds between sessions (default: 2)")
            print("  --test       label all sessions as test (excluded from formal dataset)")
            print("  --blocked    use session-level direction mode")
            sys.exit(1)

        batch_condition = args[1].upper()
        if batch_condition not in ('A', 'B', 'C', 'D'):
            print(f"Unknown condition: {batch_condition}. Must be A, B, C, or D.")
            sys.exit(1)
        try:
            batch_n = int(args[2])
        except ValueError:
            print(f"N must be an integer, got: {args[2]}")
            sys.exit(1)

        # Parse --pause
        pause_seconds = 2
        if '--pause' in args:
            pi = args.index('--pause')
            try:
                pause_seconds = float(args[pi + 1])
            except (IndexError, ValueError):
                print("--pause requires a numeric argument (seconds)")
                sys.exit(1)

        cfg.AUTO_CONDITION = batch_condition
        if is_test_session:
            cfg.IS_TEST_SESSION = True

        print(f"\n{'='*60}")
        print(f"  BATCH RUN — Condition {batch_condition} — {batch_n} sessions")
        if is_test_session:
            print(f"  *** TEST BATCH — excluded from formal dataset ***")
        if is_blocked:
            print(f"  Direction mode: BLOCKED (one direction per session)")
        print(f"  Pause between sessions: {pause_seconds}s")
        print(f"{'='*60}\n")

        batch_results = []
        for i in range(1, batch_n + 1):
            print(f"\n{'─'*60}")
            print(f"  Session {i} of {batch_n}")
            print(f"{'─'*60}")
            run_session_automated()
            # Collect last saved session for mini-summary
            ids = list_sessions()
            if ids:
                last = load(ids[-1])
                st = last.get('session_stats', {})
                batch_results.append({
                    'id': last['session_id'],
                    'z': st.get('cum_z', 0),
                    'hits': st.get('hits', 0),
                    'n': st.get('n', 0),
                    'dir': last.get('direction_sequence', [None])[0],
                })
            if i < batch_n:
                time.sleep(pause_seconds)

        # Batch summary
        import math as _math
        print(f"\n{'='*60}")
        print(f"  BATCH COMPLETE — {batch_n} sessions")
        print(f"{'='*60}")
        print(f"\n  {'Session ID':<33} {'Dir':<5} {'Z':>8} {'Hits':>6}")
        print(f"  {'─'*58}")
        zs = []
        for r in batch_results:
            dir_str = str(r['dir']) if r['dir'] else '—'
            print(f"  {r['id']:<33} {dir_str:<5} {r['z']:>+8.3f} {r['hits']}/{r['n']}")
            zs.append(r['z'])
        if zs:
            combined = sum(zs) / _math.sqrt(len(zs))
            pos = sum(1 for z in zs if z > 0)
            print(f"\n  Combined Z (Stouffer): {combined:>+.3f}")
            print(f"  Positive sessions:     {pos}/{len(zs)}")
        print()

    elif args[0] == 'report':
        if len(args) < 2:
            print("Usage: python spectra_pipeline.py report <session_id>")
            sys.exit(1)
        generate_report(args[1])

    elif args[0] == 'summary':
        cross_session_summary()

    elif args[0] == 'list':
        ids = list_sessions()
        print(f"\nSessions in '{cfg.DATA_DIR}':")
        for sid in ids:
            print(f"  {sid}")

    elif args[0] == 'qrng-status':
        # Show QRNG monthly usage and configuration
        api_key = getattr(cfg, 'QRNG_API_KEY', '')
        monthly_limit = getattr(cfg, 'QRNG_MONTHLY_LIMIT', 100)
        monthly_used = _load_qrng_monthly_count()
        month_str = datetime.datetime.now().strftime("%B %Y")
        remaining = max(0, monthly_limit - monthly_used) if monthly_limit else None
        sessions_remaining = (remaining // 10) if remaining is not None else None

        print(f"\n  QRNG STATUS — {month_str}")
        print(f"  {'─'*40}")
        print(f"  Endpoint:     {'authenticated (new)' if api_key else 'legacy (no key — retiring)'}")
        print(f"  Rate limit:   {'1 req/sec' if api_key else '~2 min/req (legacy)'}")
        print(f"  Monthly used: {monthly_used}/{monthly_limit if monthly_limit else '∞'}")
        if remaining is not None:
            print(f"  Remaining:    {remaining} requests (~{sessions_remaining} sessions @ 10 trials)")
        if not api_key:
            print(f"\n  ACTION REQUIRED: Set QRNG_API_KEY in spectra_config.py")
            print(f"  Register at: https://quantumnumbers.anu.edu.au")
        print()

    elif args[0] == 'cost':
        # Print cost report for a session, or estimate for a planned run
        if len(args) >= 2:
            try:
                s = load(args[1])
                if s.get('token_usage'):
                    print(f"\nCost report for session {args[1]}:")
                    print_cost_report(s['token_usage'])
                else:
                    print(f"No token usage data in session {args[1]}.")
                    print("Token tracking was added in pipeline v2 — older sessions have no cost data.")
            except Exception as e:
                print(f"Could not load session: {e}")
        else:
            # Print cost estimate for a full automated session
            _print_cost_estimate()

    elif args[0] == 'score-batch':
        # Submit batch scoring for one or more sessions
        if len(args) < 2:
            print("Usage: python spectra_pipeline.py score-batch <session_id> [<session_id>...]")
            print("       python spectra_pipeline.py score-batch <id1> <id2> --rubric path/to/rubric.md")
            sys.exit(1)
        rubric_path = None
        ids = []
        i = 1
        while i < len(args):
            if args[i] == '--rubric' and i + 1 < len(args):
                rubric_path = args[i + 1]
                i += 2
            else:
                ids.append(args[i])
                i += 1
        submit_score_batch(ids, rubric_path=rubric_path)

    elif args[0] == 'score-status':
        if len(args) < 2:
            print("Usage: python spectra_pipeline.py score-status <batch_id>")
            sys.exit(1)
        status = get_batch_status(args[1])
        print(f"\nBatch {args[1]}:")
        for k, v in status.items():
            print(f"  {k:<22} {v}")

    elif args[0] == 'score-collect':
        if len(args) < 2:
            print("Usage: python spectra_pipeline.py score-collect <batch_id> [--rubric path] [--poll N]")
            sys.exit(1)
        rubric_path = None
        poll_interval = 60
        i = 2
        while i < len(args):
            if args[i] == '--rubric' and i + 1 < len(args):
                rubric_path = args[i + 1]; i += 2
            elif args[i] == '--poll' and i + 1 < len(args):
                poll_interval = int(args[i + 1]); i += 2
            else:
                i += 1
        collect_score_batch(args[1], poll_interval=poll_interval, rubric_path=rubric_path)

    elif args[0] == 'score':
        if len(args) < 2:
            print("Usage: python spectra_pipeline.py score <session_id> [--rubric path/to/rubric.md]")
            sys.exit(1)
        rubric_path = None
        if '--rubric' in args:
            idx = args.index('--rubric')
            if idx + 1 < len(args):
                rubric_path = args[idx + 1]
        run_scoring(args[1], rubric_path=rubric_path)

    else:
        print(f"Unknown command: {args[0]}")
        print("Usage:")
        print("  python spectra_pipeline.py                        # new session (manual or auto per config)")
        print("  python spectra_pipeline.py auto [A/B/C/D]         # force automated session")
        print("  python spectra_pipeline.py report <id>            # session report")
        print("  python spectra_pipeline.py summary                # cross-session stats")
        print("  python spectra_pipeline.py list                   # list sessions")
        print("  python spectra_pipeline.py score <id>             # run scoring (synchronous)")
        print("  python spectra_pipeline.py score <id> --rubric X  # score with custom rubric")
        print("  python spectra_pipeline.py score-batch <id>...    # submit batch scoring (async, 50% cost)")
        print("  python spectra_pipeline.py score-status <bid>     # check batch status")
        print("  python spectra_pipeline.py score-collect <bid>    # collect completed batch results")
        print("  python spectra_pipeline.py cost                   # print cost estimate")
        print("  python spectra_pipeline.py cost <id>              # print cost for session")
        print("  python spectra_pipeline.py qrng-status            # QRNG monthly budget")
        sys.exit(1)

# ============================================================
# SECTION 7 — AUTOMATED SCORING MODULE
# ============================================================
#
# Runs two independent Claude scorer instances against a session
# transcript. Extracts structured scores, calculates inter-rater
# reliability, stores results in session JSON.
#
# Usage:
#   python spectra_pipeline.py score <session_id>
#   python spectra_pipeline.py score <session_id> --rubric path/to/rubric.md
#
# The rubric markdown file defaults to SCORER_RUBRIC_PATH in config.
# ============================================================



