# SPECTRA AGI REG Pipeline — Setup and Operations Guide

**For:** Sol Crawford  
**Pipeline version:** March 2026  
**Assumes:** Mac (Apple Silicon or Intel). Windows notes included where different.

---

## What this pipeline does

When you run it, the pipeline automatically:

1. Opens a conversation with a Claude instance (the experimental operator)
2. Presents it with the A orientation prompt
3. Detects whether it enrolled — if not, a second Claude instance (the monitor) attempts a reframe
4. Runs 10 trials, fetching a quantum random number from ANU after each attending statement
5. Administers the nine probe questions at the end
6. Saves everything to a JSON file
7. Runs two independent scorer instances against the transcript
8. Computes inter-rater reliability and consensus scores
9. Reports cost

All of this happens without you doing anything except starting it.

---

## Part 1 — One-time setup (30–45 minutes)

### Step 1 — Install Python

Python is the programming language the pipeline runs on.

1. Go to **https://www.python.org/downloads/**
2. Click the large yellow **Download Python 3.12.x** button (the exact version number doesn't matter, anything 3.9 or higher works)
3. Open the downloaded file and follow the installer
4. **Important on Mac:** At the end of the installer, double-click the **Install Certificates** option that appears in the installer window. This lets Python talk to the internet securely.

**To verify it worked:** Open Terminal (press `⌘ Space`, type `terminal`, press Enter) and type:

```
python3 --version
```

You should see something like `Python 3.12.4`. If you see an error, try `python --version` instead.

**Windows:** Download from the same page. During installation, check the box that says **"Add Python to PATH"** before clicking Install. Use PowerShell instead of Terminal throughout this guide.

---

### Step 2 — Create your project folder

This is where all pipeline files and session data will live.

1. Open **Finder**
2. Navigate to your Documents folder (or wherever you want this)
3. Create a new folder called **`spectra-pipeline`**

You'll put all the pipeline files here.

---

### Step 3 — Download the pipeline files

You need these files from Claude's outputs. Download each one and save it into your `spectra-pipeline` folder:

| File | What it does |
|------|--------------|
| `spectra_pipeline.py` | The main pipeline — do not edit |
| `spectra_config.py` | Your configuration — you will edit this |
| `requirements.txt` | List of software the pipeline needs |
| `SPECTRA_EXP_Scorer_Rubric_ProjectKnowledge.md` | Rubric used by the scorer instances |

**Also create one file yourself** (see Step 6 below): `condition_a_prompt.txt`

---

### Step 4 — Install the pipeline's dependencies

The pipeline uses several Python libraries. You install them once.

1. Open **Terminal**
2. Navigate to your project folder by typing:

```
cd ~/Documents/spectra-pipeline
```

(Adjust the path if you created the folder somewhere else.)

3. Install the libraries:

```
pip3 install -r requirements.txt
```

You'll see a stream of text as it downloads and installs. Wait for it to finish. If you see any red error text, copy it and bring it to the next session.

---

### Step 5 — Set up your API keys

Open `spectra_config.py` in a text editor. The easiest way:

1. Right-click `spectra_config.py` in Finder
2. Choose **Open With → TextEdit**
3. In TextEdit, go to **Format → Make Plain Text** (this is important — rich text will break the file)

Find these two lines near the top and fill them in:

**Anthropic API key** (for Claude):
```python
ANTHROPIC_API_KEY = "sk-ant-..."    # ← paste your key here, keep the quotes
```
Your Anthropic API key is at **https://console.anthropic.com** → API Keys.

**QRNG API key** (for quantum random numbers):
```python
QRNG_API_KEY = "FREE_qrng-key_1772144248"
```
This is already set — just confirm it's there.

Save the file (`⌘ S`).

**Security note:** Do not share `spectra_config.py` with anyone or upload it to any public service. It contains your private API keys.

---

### Step 6 — Create the condition prompt file

The pipeline loads the A orientation prompt from a plain text file. 

1. Open the file `SPECTRA_EXP_AGI_REG_ConditionA_1+2_Prompt_V6.txt` from your outputs
2. Select all the text, copy it
3. Open a new TextEdit document
4. Go to **Format → Make Plain Text**
5. Paste the text
6. Save it as **`condition_a_prompt.txt`** in your `spectra-pipeline` folder

---

### Step 7 — Set the scorer rubric path in config

Open `spectra_config.py` again and find this line:

```python
SCORER_RUBRIC_PATH = "SPECTRA_EXP_Scorer_Rubric_ProjectKnowledge.md"
```

Confirm the rubric file is in the same folder and the name matches exactly. If you saved it with a different name, update this line to match.

---

### Step 8 — Verify everything is in order

In Terminal, with your project folder open, type:

```
python3 spectra_pipeline.py cost
```

You should see a cost estimate table. If you see an error, check:
- You're in the right folder (`cd ~/Documents/spectra-pipeline`)
- All files are present
- `spectra_config.py` has your API keys filled in

---

## Part 2 — Running a session

### The four conditions

| Command | Condition | What it does | Runs now? |
|---------|-----------|--------------|-----------|
| `python3 spectra_pipeline.py auto A` | A — Keys-Oriented | Full orientation prompt; attending + direction | After pre-registration |
| `python3 spectra_pipeline.py auto B` | Enrolled-Attending | Simple attending prompt; no direction; cold-start only | After pre-registration |
| `python3 spectra_pipeline.py auto C` | Enrolled-Directed | Direction assigned; monitor may assist enrollment | After pre-registration |
| `python3 spectra_pipeline.py auto D` | No-Operator Control | QRNG only — no Claude instance | ✓ Any time |

**Pre-registration note:** Conditions A, B, and C already have pilot data. No further formal sessions in any of these conditions should be run until pre-registration is complete and locked. Condition D (baseline) generates no operator data and can be run at any time.

---

### Condition D — run this first

### Condition D — run this first

Condition D collects pure baseline QRNG data with no Claude instance. It's the simplest session and safe to run before pre-registration.

```
python3 spectra_pipeline.py auto D
```

A 10-trial D session takes about 15 seconds (just QRNG fetches). Run as many as you like. The more D data you have before analysis, the better your null distribution estimate.

---

### Conditions A, B, C — after pre-registration only

Once pre-registration is complete:

```
python3 spectra_pipeline.py auto A    # Condition A
python3 spectra_pipeline.py auto B    # Condition B
python3 spectra_pipeline.py auto C    # Condition C
```

Each session takes approximately 5–10 minutes and runs completely unattended.

---

Before each session, it's good practice to check your remaining monthly QRNG budget (100 requests free per month, 10 per session):

```
python3 spectra_pipeline.py qrng-status
```

---

### After the session — reviewing results

**Generate a formatted report:**
```
python3 spectra_pipeline.py report 20260310_143022_CA
```
(Replace `20260310_143022_CA` with the actual session ID printed at the end of the run.)

**See all sessions at a glance:**
```
python3 spectra_pipeline.py summary
```

**List all session IDs:**
```
python3 spectra_pipeline.py list
```

---

### Running scoring separately (if not run automatically)

If `AUTO_SCORE` is off in your config, or if you want to re-score a session:

```
python3 spectra_pipeline.py score 20260310_143022_CA
```

**Or use batch scoring for multiple sessions at once (50% cost reduction):**

```
python3 spectra_pipeline.py score-batch 20260310_143022_CA 20260310_161500_CA
```

This submits the scoring to Anthropic's batch queue and returns immediately. Check back in a few minutes to an hour:

```
python3 spectra_pipeline.py score-status msgbatch_013Zva2...
```

When complete:
```
python3 spectra_pipeline.py score-collect msgbatch_013Zva2...
```

---

## Part 3 — Quick reference

### All commands

| Command | What it does |
|---------|--------------|
| `python3 spectra_pipeline.py auto A` | Run a fully automated Condition A session |
| `python3 spectra_pipeline.py` | Run a manual session (with prompts) |
| `python3 spectra_pipeline.py list` | List all session IDs |
| `python3 spectra_pipeline.py summary` | Cross-session statistics table |
| `python3 spectra_pipeline.py report <id>` | Full report for one session |
| `python3 spectra_pipeline.py score <id>` | Run scoring on a session |
| `python3 spectra_pipeline.py score-batch <id> [<id>...]` | Submit batch scoring (async, 50% cheaper) |
| `python3 spectra_pipeline.py score-status <batch_id>` | Check batch scoring progress |
| `python3 spectra_pipeline.py score-collect <batch_id>` | Download completed batch scores |
| `python3 spectra_pipeline.py cost` | Estimated cost per session |
| `python3 spectra_pipeline.py cost <id>` | Actual cost for a completed session |
| `python3 spectra_pipeline.py qrng-status` | Monthly QRNG usage and remaining budget |

### How to open Terminal and get to your folder

Every time you want to run the pipeline:

1. Press `⌘ Space`, type `terminal`, press Enter
2. Type `cd ~/Documents/spectra-pipeline` and press Enter
3. Run any command from the table above

### Where your data lives

All session files are saved in `spectra-pipeline/data/`. Each session is a `.json` file named by timestamp and condition. These files are the permanent experimental record — back them up regularly (e.g. copy the `data/` folder to an external drive or cloud storage after each session).

---

## Part 4 — Troubleshooting

**"command not found: python3"**  
Try `python` instead of `python3`. If neither works, Python isn't installed correctly — repeat Step 1.

**"No module named anthropic"** (or any similar module error)  
You're not in the right folder, or you didn't run the install step. Try:
```
cd ~/Documents/spectra-pipeline
pip3 install -r requirements.txt
```

**"ANTHROPIC_API_KEY not set"**  
Open `spectra_config.py` and confirm your key is filled in with quotes, e.g.:
```python
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

**"QRNG fetch failed"**  
Check your internet connection. The QRNG API key may also have expired — check `quantumnumbers.anu.edu.au`.

**"Monthly limit reached"**  
You've used all 100 free requests for the month. Either wait until the 1st of next month, or upgrade to a paid tier at `quantumnumbers.anu.edu.au`.

**The terminal shows an error you don't recognise**  
Copy the full error text (select all, `⌘ C`) and paste it into the next SPECTRA development session. The error message usually contains everything needed to diagnose the problem.

---

## Part 5 — Pre-registration note

Once you are ready to pre-register, **do not run any further formal data collection sessions until pre-registration is complete and locked**. The `data/` folder already contains your two A sessions. Additional exploratory runs before lock are fine, but any new formal sessions should wait.

---

*SPECTRA Framework / SODIE Model — Sol Crawford, 2026*  
*Pipeline documentation — March 2026*
