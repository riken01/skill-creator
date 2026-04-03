---
name: skill-creator
description: Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
---

# Skill Creator

A skill for creating new skills and iteratively improving them.

The process looks like this:

- **Talk to the user first** — understand what they want before writing anything
- Write a draft of the skill
- **Ask the user if they want evals** — get explicit consent
- If yes: propose test cases, run both with-skill and without-skill, grade via `agents/grader.md`, aggregate via `scripts/aggregate_benchmark`, present benchmark report
- Iterate until satisfied
- Optionally optimize description via `scripts/run_loop.py`

**Common failure modes (hard rules — violating any of these is a bug):**
1. **Writing without talking to the user first** — Step 1 is not optional.
2. **Skipping the eval consent question** — After drafting the skill you MUST ask "Would you like me to run evaluations?" and wait for an answer. This is the single most frequently skipped step.
3. **Skipping grading/aggregation or doing it manually** — After runs complete, you MUST grade every run via `agents/grader.md` and aggregate via `scripts.aggregate_benchmark`. This is the most commonly skipped substep. If you find yourself presenting results without `grading.json` files and a `benchmark.md`, STOP — you skipped grading. Go back and do it.

---

## Step 1: Capture intent (do NOT skip)

**Before writing anything**, talk to the user. Extract what you can from the conversation — tools used, steps taken, corrections made — then fill in gaps by asking:

1. What should this skill do? When should it trigger?
2. What's the expected output?
3. Edge cases, input formats, or dependencies?

Surface things the user might not have considered: failure modes, what "done" looks like. Research similar skills/patterns if helpful. Only move to writing once aligned.

---

## Step 2: Write the SKILL.md

Components:

- **name**: Skill identifier
- **description**: When to trigger and what it does. This is the primary triggering mechanism — all "when to use" guidance goes here, not in the body. Make it slightly "pushy": instead of "Builds dashboards for internal data", write "Builds dashboards for internal data. Use whenever the user mentions dashboards, metrics, or wants to display company data — even if they don't say 'dashboard' explicitly."
- **the rest of the skill**

Key principles:
- Explain *why* behind instructions — LLMs generalize better with intent.
- Keep it lean. Under 300 lines. Move supplementary reference material to `references/`.
- Use imperative form. Include examples where helpful.
- When a skill supports multiple domains, organize by variant in `references/` (e.g. `aws.md`, `gcp.md`).

---

## Step 3: Ask about evaluation, then propose test cases (do NOT skip)

**MANDATORY CHECKPOINT — DO NOT SKIP THIS STEP.**

After drafting the skill, you MUST stop and explicitly ask the user whether they want to run evals. Do not assume yes. Do not assume no. Do not silently move on. You must wait for an answer before proceeding.

Ask exactly this (or equivalent):

> "The skill draft is ready. Would you like me to run evaluations to test it?"

- **Yes**: proceed to propose test cases and run them (Steps 3a–4).
- **No**: skip to Step 5 (or Description Optimization). Do not run evals silently.

**If you find yourself moving to Step 5 without having asked this question, STOP — you skipped this step. Go back and ask.**

### Step 3a: Propose test cases

Propose 2–3 realistic test prompts. For each test case, also draft expectations — objectively verifiable success criteria with clear names. Present prompts and expectations together to the user and wait for confirmation before running:

> "Here are a few test cases and the expectations I'll grade them on. Do these look right, or do you want to change any?"

Save to `evals/evals.json` (see `references/schemas.md` for full schema including `expectations`).

---

## Step 4: Run the evals

Complete every substep (4a–4b) before moving on. Every test case needs **both** a with-skill run and a baseline run (without-skill for new skills, old-skill for existing skill improvements) from actual subagent execution. Never fabricate results. Never present results without running the grader and aggregate script. **Runs without grading are worthless — Step 4b is not optional.**

Results go in `<skill-name>-workspace/iteration-<N>/eval-<N>/`.

### 4a: For each test case — write metadata, run both configs, capture timing

Process each test case **sequentially and completely** before moving to the next. For each test case:

**1. Write `eval_metadata.json`** in the eval directory (`eval-<N>/eval_metadata.json`). Copy the expectations confirmed in Step 3a — do not re-draft, use what the user already approved. Ensure `evals/evals.json` is also up to date.
```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "expectations": []
}
```

**2. Run with-skill subagent.** Provide the skill path, task prompt, input files, and output directory (`with_skill/outputs/`). Include in the prompt: "You are running non-interactively — no human will provide stdin. Feed expected inputs via heredoc/pipe. Never leave a command waiting for stdin."

**3. IMMEDIATELY save `with_skill/timing.json`.** Do this the moment the subagent finishes — this data cannot be recovered later. Do NOT defer this to a later step.
```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

**4. Run baseline subagent.** The baseline depends on the scenario:
- **New skill**: Run the same prompt *without* the skill path. Save to `without_skill/outputs/`.
- **Improving an existing skill**: Snapshot the old skill first (copy to a temp location), then run the baseline subagent *with the old skill snapshot*. Save to `old_skill/outputs/`. Do NOT run a no-skill baseline — the comparison must be old version vs new version.

**5. IMMEDIATELY save baseline `timing.json`** (in `without_skill/` or `old_skill/` depending on scenario). Same rule — capture it right now, not later.

If a run fails: diagnose and retry. Do not proceed to grading with missing runs.

### 4b: Grade, aggregate, and present — MANDATORY, DO NOT SKIP

**THIS IS A HARD CHECKPOINT.** You may NOT present results, move to Step 5, or claim the eval is complete until every run has a `grading.json` and `benchmark.md` exists. If you are about to summarize eval results without having graded, STOP — you are skipping grading.

Complete all substeps below before moving on.

**1. Grade each run via grader subagent (serial, one at a time) — NO EXCEPTIONS:**
The grader prompt must instruct the subagent to **read `agents/grader.md` first and follow it exactly**. Pass it: expectations from `eval_metadata.json`, transcript path, outputs directory. Output: `grading.json` in the run directory (schema in `references/schemas.md`). **Wait until every run has a valid `grading.json`. Do not proceed without them.**

**2. Aggregate via script (mandatory — no manual substitute):**
```bash
cd ~/.openclaw/workspace/skills/skill-creator && python3 -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
```
Produces `benchmark.json` and `benchmark.md`. **Verify both files exist before proceeding.** If either is missing, the eval is incomplete.

**3. Analyst pass:** Read `benchmark.md`, surface patterns per `agents/analyzer.md`.

**4. Present results:** Walk through each test case: prompt, with-skill vs. baseline comparison (pass rates, timing, tokens), key excerpts, deltas, `eval_feedback`. Ask "Any feedback?" per case. Show overall summary from `benchmark.md` at the end.

**Self-check before presenting:** Confirm that (a) every run directory contains `grading.json`, (b) `benchmark.md` exists, (c) you are presenting graded scores, not your own assessment. If any of these are false, go back and fix it.

---

## Step 5: Improve and iterate

1. **Read the transcripts**, not just final outputs. Trim unproductive steps the skill caused.
2. **Generalize** — avoid narrow fixes that only work for tested examples.
3. **Explain the why** — don't just add rules; explain why they matter.
4. **Bundle repeated work** — if all runs wrote the same helper, put it in `scripts/`.
5. Apply improvements, rerun into `iteration-<N+1>/`, repeat until the user is satisfied or feedback is empty.

---

## Advanced: Blind comparison

For rigorous A/B comparison between two skill versions, read `agents/comparator.md` and `agents/analyzer.md`. Optional — the human review loop is usually enough.

---

## Description Optimization

After finishing the skill, offer to optimize the description. When the user accepts, follow this protocol strictly. See `references/description-optimization.md` for query quality guidelines.

### D1: Create 12 eval queries

6 should-trigger and 6 should-not-trigger. Queries must be realistic and detailed (file paths, casual speech, typos — not generic). Save as JSON:
```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

### D2: Review with the user

Present queries grouped by category, get user edits, confirm final set. Save to `<workspace>/trigger_eval.json`. Do not proceed until confirmed.

### D3: Run `run_loop.py` (mandatory — no manual alternative)

Follow the exact run command and output handling instructions in `references/description-optimization.md` Step 3. **Critical:** all stdout/stderr must be redirected to files — never capture loop output directly into the conversation, or the context will overflow.

### D5: Present and apply

Show original vs. best description, train/test scores, iteration count, key observations. If user approves, update SKILL.md frontmatter. Point user to the HTML report.

---

## Packaging

If you have access to the `present_files` tool, package the skill and present it to the user:

```bash
python3 -m scripts.package_skill <path/to/skill-folder>
```

---

## OpenClaw-Specific Notes

OpenClaw loads skills from `~/.openclaw/workspace/skills/`. Newly installed skills are available in the next conversation turn.

- **Skill injection for eval**: Temporary skills go in `~/.openclaw/workspace/skills/<unique-name>/` and are cleaned up automatically by `run_eval.py`.
- **Description optimization**: Creates a new agent for each query to achieve session isolation. This is handled by `run_eval.py` — no manual session management needed.
- **Updating an existing skill**: Preserve the original directory name and `name` frontmatter. Copy to `/tmp/skill-name/` before editing if the installed path is read-only.

---

## Reference files

- `agents/grader.md` — Grading expectations against outputs
- `agents/comparator.md` — Blind A/B comparison
- `agents/analyzer.md` — Analyzing benchmark results
- `references/description-optimization.md` — Full description optimization process
- `references/schemas.md` — JSON schemas for evals.json, grading.json, etc.
