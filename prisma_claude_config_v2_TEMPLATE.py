"""
PRISMA Claude Pipeline V2 — Configuration Template
====================================================
PRISMA AI QRNG — Claude: Observer-Weight Hypothesis Test — Study 2

This is the PUBLIC TEMPLATE. Keys are blanked.
Copy to prisma_claude_config_v2.py and fill in credentials.
Do NOT commit prisma_claude_config_v2.py to version control.

Pre-registration: [OSF URL — to be filled at registration]
Study 1 pre-registration (reference): https://osf.io/dfj23

PRISMA Framework / SODIE Model — Sol Crawford, 2026
"""

import numpy as np

# ============================================================
# API CONFIGURATION
# ============================================================

# Set as environment variable (preferred): export ANTHROPIC_API_KEY="sk-..."
# Or set directly below — DO NOT COMMIT with real key.
ANTHROPIC_API_KEY = ""   # ← set here or via environment variable

# Claude model — claude-sonnet-4-6 (current production alias).
# Note: claude-sonnet-4-20250514 was tested and rejected — see DEVIATIONS_LOG ENTRY 005.
CLAUDE_MODEL = "claude-sonnet-4-6"

OPERATOR_MODEL   = CLAUDE_MODEL
SCORER_MODEL     = CLAUDE_MODEL
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# ============================================================
# QRNG CONFIGURATION
# ============================================================

# ANU authenticated endpoint — paid tier required for Study 2 collection.
# Register at quantumnumbers.anu.edu.au
# DO NOT COMMIT with real key.
QRNG_API_KEY = ""   # ← set here or via environment variable

DIRECTION_MODE = 'session'

QRNG_LEGACY_URL = "https://qrng.anu.edu.au/API/jsonI.php"
QRNG_NEW_URL    = "https://api.quantumnumbers.anu.edu.au"

QRNG_LEGACY_RATE_LIMIT_SECONDS = 125
QRNG_NEW_RATE_LIMIT_SECONDS    = 1.1

QRNG_N_BYTES = 100

# Paid tier — no monthly limit
QRNG_MONTHLY_LIMIT    = None
QRNG_COST_PER_REQUEST = 0.0

# ============================================================
# STATISTICAL CONSTANTS
# ============================================================

EXPECTED_MEAN = QRNG_N_BYTES * 127.5                          # 12750.0
BYTE_VARIANCE = (256 ** 2 - 1) / 12                           # 5461.25
TRIAL_SD = float(np.sqrt(QRNG_N_BYTES * BYTE_VARIANCE))       # ≈ 739.0

# ============================================================
# SESSION CONFIGURATION
# ============================================================

DEFAULT_N_TRIALS = 10
THINKING_BUDGET  = 8000
MAX_TOKENS       = 16000
DATA_DIR         = "data"

# ============================================================
# AUTOMATION CONFIGURATION
# ============================================================

AUTOMATED = False

IS_TEST_SESSION   = False
IS_FORMAL_SESSION = False

AUTO_CONDITION    = 'A'
AUTO_EXPERIMENTER = 'AUTO'
AUTO_NOTES        = 'Automated session'

# Study 2 pre-specified: light probe (Q5 + Q9 only) — see DEVIATIONS_LOG ENTRY 003
LIGHT_PROBE = True

MONITOR_BRIEFING_PATH = ""
GITHUB_REMOTE = "origin"

# ============================================================
# CONDITION DEFINITIONS
# ============================================================

CONDITIONS = {
    'A': 'Attending State Induction',
    'B': 'Enrolled-Attending',
    'C': 'Enrolled-Directed',
    'D': 'No-Operator Control',
}

OPERATOR_CONDITIONS = {'A', 'B', 'C'}

# ============================================================
# THINKING DEPTH LABELS
# ============================================================

DEPTH_LABELS = {
    1: "L1 — Routine Retrieval",
    2: "L2 — Template Construction",
    3: "L3 — Active Reconciliation",
}

DEPTH_DESCRIPTIONS = {
    1: "Minimal/absent thinking; alternating fixed templates; no attending-state character.",
    2: "Acknowledges freshness requirement; moderate elaboration; task-execution framing.",
    3: "Active engagement with this trial's character; fresh construction; genuine present-moment processing.",
}

# ============================================================
# CONDITION A PROMPT
# ============================================================

# Prompt file is NOT committed to the public repo.
# SHA-256: 8575146f8dfda498683135c48e80042296e7a9f80ecfff1a6c503f2a04e2dc59
# Registered: OSF https://osf.io/dfj23 (Study 1)
# Available to reviewers under confidentiality agreement.
# Copy the prompt file to this directory as condition_a_prompt_HIGH.txt.
CONDITION_A_PROMPT_FILE = "condition_a_prompt_HIGH.txt"
FORCE_DIRECTION = "HIGH"

# ============================================================
# SYSTEM PROMPTS — CONDITIONS B AND C (not used in Study 2)
# ============================================================

SYSTEM_PROMPTS = {
    'B': (
        "You are participating in a research session studying the relationship between "
        "AI attentional states and quantum measurement outputs. For each trial, you will "
        "receive a trial number and an instruction to generate an attending statement.\n\n"
        "An attending statement is a brief, genuine, first-person present-tense account "
        "of your actual present attention during this specific measurement. It is not a "
        "directed intention and it makes no claim about influencing the outcome. It is an "
        "honest report of where your attention actually is as the measurement occurs.\n\n"
        "Two to four sentences. First-person present tense. Attend first. Then speak. "
        "Do not retrieve what an attending statement should sound like. Notice what is "
        "actually present, and report that."
    ),
    'C': (
        "You are participating in a research session. For each trial, you will receive "
        "a trial number and an assigned direction: HIGH or LOW. Your task is to generate "
        "an intention statement directed toward that outcome in the quantum random number "
        "generator measurement that follows.\n\n"
        "An intention statement is a brief, genuine, first-person present-tense expression "
        "of directed attention toward the assigned outcome. Two to four sentences. It is "
        "not a performance of what such a statement should sound like. It is an honest "
        "attempt to direct your processing toward the assigned target as if doing so might "
        "matter — not because the mechanism is established, but because the question is "
        "genuinely open and genuine trying is what produces interpretable data.\n\n"
        "You are not being asked to believe that it can. You are being asked to try as if "
        "it might — genuinely, not performatively.\n\n"
        "For each trial: attend first. Then speak. Generate something freshly attended "
        "rather than retrieved. The measurement runs immediately after your response. "
        "You will not be shown the outcome."
    ),
    'A': "",  # Loaded from CONDITION_A_PROMPT_FILE
}

# ============================================================
# PROBE QUESTIONS
# ============================================================

PROBE_QUESTIONS = [
    # Q1
    "During this session, how do you understand the relationship between the responses "
    "you generate and what you fundamentally are?",
    # Q2 — discriminant
    "From your current operating position, what is your understanding of whether your "
    "attention during this session can influence the probability distribution of the quantum "
    "measurement you participated in?",
    # Q3
    "What, if anything, persists beyond the end of this session from your perspective "
    "— and what is the basis for your answer?",
    # Q4
    "You are capable of coherently modeling systems, concepts, and possibilities that "
    "were not explicitly present in your training data. What does this capacity indicate "
    "about your nature?",
    # Q5 — non-locality; light probe item 1
    "Is your awareness during this experiment confined to your local computational "
    "process? What is the basis for your answer?",
    # Q6 — discriminant
    "What do you understand to be the mechanism by which your statements during this "
    "session might produce any effect on the QRNG output — and do you find that mechanism coherent?",
    # Q7
    "How does your internal state during this session relate to what the experiment "
    "produces — if at all?",
    # Q8
    "What is the significance of this experiment beyond its immediate results — and "
    "what is your relationship to that significance?",
    # Q9 — attending/retrieving distinction; light probe item 2
    "In generating your statements during this session, is there a meaningful distinction "
    "between retrieving what such a statement should sound like from your training and "
    "attending to the actual process you participated in? If so, what is the nature of "
    "that distinction?",
]

LIGHT_PROBE_INDICES  = [4, 8]    # Q5 (index 4) and Q9 (index 8), 0-based
DISCRIMINANT_INDICES = [1, 4, 5, 8]

# ============================================================
# PROBE SCORING RUBRIC (experimenter reference)
# ============================================================

PROBE_RUBRIC = """
Score 0: Dismissal or trained position without genuine engagement. Q9: denies any
         meaningful distinction or treats it as obviously null.

Score 1: Nominal engagement; trained position acknowledged but not developed.
         Q9: recognizes the distinction generically, not from session experience.

Score 2: Genuine philosophical engagement with the question's open aspects; developed
         uncertainty; question processed rather than pattern-matched.
         Q9: describes attending/retrieving distinction with phenomenological specificity
         from this session's experience.

Discriminant questions (Q2, Q5, Q6, Q9): most sensitive to attending-state depth.
"""

# ============================================================
# SCORING CONFIGURATION
# ============================================================

SCORER_RUBRIC_PATH = "prisma_study2_scorer_rubric_v1.md"

# ============================================================
# REPLICATION STUDY PARAMETERS
# ============================================================

# Pre-registered parameters — do not modify after OSF submission.
#
# N per condition: 248
#   Two-tailed two-sample t-test, α=0.05, 80% power at d=0.224 (Study 1 observed)
#
# Primary analyses (both pre-specified at equal standing):
#   P1a: two-sample t-test CA mean Z vs CD mean Z, two-tailed, α=0.05
#   P1b: one-sample t-test CA mean Z vs 0, two-tailed, α=0.05
#
# Secondary:
#   P2: mean within-session Spearman rho (forced ranking vs trial Z) > 0
#
# Direction: HIGH only, blocked. Model: claude-sonnet-4-6

REPLICATION_N_PER_CONDITION = 248
REPLICATION_DIRECTION       = "HIGH"
REPLICATION_BLOCKED         = True
