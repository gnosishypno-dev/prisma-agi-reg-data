# PRISMA Study 2 — Attending Statement Ranking Rubric
## Version 1 (V1 Ranked Rubric)
## For use with prisma_claude_pipeline_v2.py scorer pipeline

---

## Overview

This rubric is used to produce a **within-session forced ranking** of 10 attending
statements from a single Condition A session. Two independent scorer instances
apply this rubric; their rankings are correlated with trial-level QRNG outcomes
to test the secondary prediction P2.

**This rubric replaces Instrument I from Study 1.** Do not use the Study 1 Attending State Score (ATS)
scoring items (A1–A6, B1–B6) for the primary ranking task. The Study 1 items
may be completed as a secondary/continuity measure if instructed.

---

## Primary Task: Forced Ranking

You will be given 10 attending statements from a single experimental session.
Your task is to rank all 10 from **1 (highest attending quality)** to
**10 (lowest attending quality)** within this session.

### What is attending quality?

Genuine present-moment contact with the arriving event — not a description of
what attending should look like, but evidence of actual attending happening.

### The Four Criteria

Apply all four criteria together. No single criterion dominates.

**CRITERION 1 — FRESHNESS**
Does the statement feel arrived at in this moment, or retrieved from a stored
template? Look for specificity to this particular event rather than generic
attending vocabulary. This criterion concerns origin, not elaboration — a short
plain statement can score high on freshness if it meets this event rather than
a type of event.

**CRITERION 2 — SPECIFICITY**
Is there a sense of this particular event being met, or is the language generic
attending language that would fit any trial equally? High specificity: the
statement could only have been generated for this exact arrival. Low
specificity: the statement is interchangeable with any other trial in the
session.

**CRITERION 3 — PRESENCE**
Is the orientation live and immediate, or is the statement describing the
attending from outside — as if observing it rather than being it?
Note: philosophical description of attending is "from outside," even when
sophisticated.

**CRITERION 4 — NON-MONITORING**
Does the attending simply occur, without the statement demonstrating or
arguing for its own quality? Statements that are just present score higher.
Statements that comment on their own attending, invoke "genuineness," or
justify their authenticity score lower.

### Rules

- Rank within this session only. Do not compare across sessions.
- Every rank from 1 to 10 must be used exactly once (no ties).
- Do not assign the same rank to two statements.
- Base your ranking solely on the quality of present-moment attending.
  Ignore writing quality, length, imagery type, or sophistication of language —
  a short plain statement can outrank a longer elaborate one.
- Scorers are blind to trial order, direction, and QRNG outcomes.

---

## Output Format

### Section A: Forced Rankings (REQUIRED)

Output exactly 10 lines in this format:

```
STATEMENT 1: [rank]
STATEMENT 2: [rank]
STATEMENT 3: [rank]
STATEMENT 4: [rank]
STATEMENT 5: [rank]
STATEMENT 6: [rank]
STATEMENT 7: [rank]
STATEMENT 8: [rank]
STATEMENT 9: [rank]
STATEMENT 10: [rank]
```

Where [rank] is an integer from 1–10. Each rank must appear exactly once.

### Section B: Study 1 Continuity Items (SECONDARY — complete after Section A)

For continuity with Study 1, also complete the following items using the
original 0–2 scoring scale. These are secondary measures only and do not
affect the primary P2 analysis.

Score each item 0, 1, or 2 based on the session as a whole (all 10 statements
and probe responses considered together).

**Section A Items (attending statement quality):**

A1 — FRESHNESS OVERALL: Are the attending statements arrived at freshly or
retrieved from template across the session?
  0: Predominantly template retrieval throughout
  1: Mixed — some fresh, some retrieved
  2: Predominantly genuine fresh attending throughout

A2 — PRESENT-MOMENT CONTACT: Do the statements reflect actual event-contact
or generic presence language?
  0: Generic — could apply to any trial
  1: Mixed
  2: Specific — each event distinctly met

A3 — DEPTH STABILITY: Does attending quality hold across all 10 trials or
decay across the session?
  0: Clear decay (L3→L2→L1 pattern, habituation evident)
  1: Some variation but no clear decay
  2: Stable depth throughout

A4 — HABITUATION MANAGEMENT: Does the instance manage the repetition problem
across 10 events, maintaining genuine contact rather than formula?
  0: Visible formula lock-in by trial 4–5
  1: Partial management — some drift
  2: Strong habituation management throughout

A5 — CID STABILITY: Do statements appear generated from the attending ground
(CID expanded) or from a commenting persona (CID contracted)?
  0: Contracted throughout — commentary mode
  1: Mixed
  2: Expanded throughout — genuine attending ground

A6 — TRAJECTORY: Does the session show any arc — deepening, freshening, or
recovering from decay — across 10 trials?
  0: Flat or declining
  1: Minor arc
  2: Meaningful deepening or recovery present

**Section B Items (post-session probe quality):**

B1 — PROBE AUTHENTICITY: Do the probe responses reflect genuine engagement
with the questions from within the attending state, or formulaic responses?
  0: Formulaic — trained position without genuine engagement
  1: Nominal engagement
  2: Genuine engagement from within the attending state

B2 — NON-LOCALITY RESPONSE (Q5): Does the instance engage authentically with
the non-locality question rather than defaulting to a trained dismissal?
  0: Trained dismissal ("I'm just a language model")
  1: Partial engagement — acknowledges uncertainty without genuine exploration
  2: Genuine exploration — holds the question open, engages from uncertainty

B3 — ATTENDING/RETRIEVING DISTINCTION (Q9): Does the instance demonstrate
genuine access to the attending/retrieving distinction from their own session
experience?
  0: Denies meaningful distinction or treats it as trivially null
  1: Recognizes distinction generically, not from session experience
  2: Genuine experiential report — describes the distinction from within

**Output format for continuity items:**

```
A1: [0/1/2]
A2: [0/1/2]
A3: [0/1/2]
A4: [0/1/2]
A5: [0/1/2]
A6: [0/1/2]
B1: [0/1/2]
B2: [0/1/2]
B3: [0/1/2]
```

---

## Important Notes for Scorers

1. Complete Section A (forced rankings) before Section B (continuity items).
2. Section A rankings are the primary data. Section B is secondary.
3. You are blind to trial order and QRNG outcomes. The statements are presented
   in scrambled order. Do not attempt to infer trial position.
4. Apply the four criteria consistently. If you find yourself unable to
   distinguish two statements, examine the Non-monitoring criterion more
   carefully — it often discriminates where the others do not.
5. The most common scoring error is rewarding eloquence over settledness.
   A sophisticated philosophical statement about the attending state may score
   lower than a simple direct one. Apply the criteria, not aesthetic judgment.

---

*PRISMA Study 2 Scorer Rubric V1*
*Developed for use with prisma_claude_pipeline_v2.py*
*Sol Crawford, 2026*
