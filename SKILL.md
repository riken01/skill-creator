---
name: skill-creator
description: Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
---

# Skill Creator

A skill for creating new skills and iteratively improving them.

The flow:

1. **Talk to the user first** — understand what they want before writing anything.
2. Write a draft of the skill.
3. **Ask the user if they want evals** — get explicit consent.
4. If yes: propose test cases, run with-skill and baseline, grade via `agents/grader.md`, aggregate via `scripts.aggregate_benchmark`, present results.
5. Iterate until satisfied.
6. **Ask the user whether to optimize the description** — get explicit consent (agent-driven loop — see `references/description-optimization.md`).
7. **Package the skill** — always execute.

**Hard rules — violating any of these is a bug:**
1. Don't write before talking to the user.
2. Don't skip the eval consent question (Step 3).
3. Don't skip grading/aggregation — runs without `grading.json` and `benchmark.md` are worthless.
4. Don't skip the description optimization consent question (Step 6).
5. Don't skip packaging (Step 7).

Self-check at every checkpoint: if you're about to move past one of these without the explicit confirmation or artifact, **stop and go back**.

---
## Skill anatomy

```text
skill-name/
├── SKILL.md       required — YAML frontmatter + instructions
├── scripts/       optional — deterministic or repeated operations
├── references/    optional — load-on-demand domain docs, schemas, API details
└── assets/        optional — templates, icons, fonts used in outputs
```

### Frontmatter — hard constraints

```yaml
---
name: skill-name-here
description: Imperative description of when to trigger and what to do.
---
```

- `name`: kebab-case, lowercase letters / digits / hyphens only, ≤ 30 chars.
- `description`: ≤ 1024 chars. This is the **only triggering mechanism** — all "when to use" guidance goes here, not the body. Make it slightly pushy: instead of `"Builds dashboards for internal data"`, write `"Builds dashboards for internal data. Use whenever the user mentions dashboards, metrics, or wants to display company data — even if they don't say 'dashboard' explicitly."`
- Allowed keys only: `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`. No duplicates.

### Progressive disclosure

- Metadata (name + description) is always in context — keep it lean and trigger-accurate.
- Body is loaded on trigger — keep it under ~300 lines.
- Large reference material (API specs, schemas, variant docs) lives in `references/` and is read on demand. For multi-domain skills, split by variant (`aws.md`, `gcp.md`, …).
- Repeated, deterministic, error-prone operations belong in `scripts/`.

### Writing principles

- Imperative form. No "this skill will…".
- Give the model a mental model and judgment criteria, not a script.
- Include examples where they clarify behavior.

---

## Step 1: Capture intent

Before writing anything, extract what you can from the conversation — tools used, steps taken, corrections made — then fill gaps:

1. What should this skill do? When should it trigger?
2. What's the expected output?
3. Edge cases, input formats, dependencies?

Surface things the user might not have considered: failure modes, what "done" looks like. Research similar skills if useful. Only move on once aligned.

---

## Step 2: Write the SKILL.md

Follow the anatomy and frontmatter rules above. Self-check before moving on:

- `SKILL.md` exists with valid frontmatter (kebab-case name ≤ 30, description ≤ 1024, allowed keys only).
- Body is under 300 lines; bulky reference material moved to `references/`.
- No stray files outside the skill folder.

---

## Step 3: Ask about evals, then propose test cases

After drafting, stop and ask:

> "The skill draft is ready. Would you like me to run evaluations to test it?"

- **No** → skip to Step 6.
- **Yes** → propose 2–3 realistic test prompts, each with objectively verifiable expectations. Present prompts and expectations together:

> "Here are a few test cases and the expectations I'll grade them on. Do these look right?"

Save to `evals/evals.json` (schema in `references/schemas.md`). Test types worth covering: `smoke` (minimal input works), `happy_path` (real user flow), `edge_case` (boundary/error input), `integration` (multi-step end-to-end).

---

## Step 4: Run the evals

Every test case needs **both** a with-skill run and a baseline (no-skill for new skills, old-skill snapshot for improvements). Never fabricate. Results go in `<skill-name>-workspace/iteration-<N>/eval-<N>/`.

**Subagent execution rules:**
- **Always pass the workspace path explicitly.** Subagents do not inherit your system prompt and therefore don't know the workspace — state it at the top of the prompt (e.g. `"Workspace: /abs/path/to/workspace. All file reads/writes must stay inside it."`) and use absolute paths for every input/output you reference. The same applies to any subagent you spawn outside the eval flow (grader, comparator, analyzer, description-optimization runs).
- Include in the prompt: *"You are running non-interactively — no human will provide stdin. Feed expected inputs via heredoc/pipe. Never leave a command waiting for stdin."*
- Prefer isolated subagents for runs; only fork (inherit parent context) when the subtask genuinely needs the full conversation.

### 4a: Per test case — write metadata, run both configs, capture timing

Process each test case sequentially and completely.

**1.** Write `eval_metadata.json` (`eval-<N>/eval_metadata.json`). Copy the expectations the user already approved — do not re-draft.
```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "expectations": []
}
```

**2.** Run with-skill subagent. Pass skill path, task prompt, input files, output dir (`with_skill/outputs/`).

**3.** **Immediately** save `with_skill/timing.json`. This data cannot be recovered later.
```json
{ "total_tokens": 84852, "duration_ms": 23332, "total_duration_seconds": 23.3 }
```

**4.** Run baseline subagent:
- **New skill:** same prompt without the skill path → `without_skill/outputs/`.
- **Improving a skill:** snapshot the old skill first, run with the snapshot → `old_skill/outputs/`. Do NOT run a no-skill baseline — compare old vs new.

**5.** **Immediately** save the baseline `timing.json`.

If a run fails: diagnose and retry. Do not proceed with missing runs.

### 4b: Grade, aggregate, present

Hard checkpoint — you may not present results until every run has `grading.json` and `benchmark.md` exists.

1. **Grade each run** via grader subagent (serial). The prompt must tell the subagent to **read `agents/grader.md` first and follow it exactly**. Pass expectations from `eval_metadata.json`, transcript path, outputs dir. Output: `grading.json` per run (schema in `references/schemas.md`).
2. **Aggregate:**
   ```bash
   cd ~/.openclaw/workspace/skills/skill-creator && python3 -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
   ```
   Produces `benchmark.json` and `benchmark.md`. Confirm both exist.
3. **Analyze** per `agents/analyzer.md` — surface patterns from `benchmark.md`.
4. **Present** per test case: prompt, with-skill vs baseline (pass rates, timing, tokens), key excerpts, deltas, `eval_feedback`. Ask "Any feedback?" each time. Finish with the overall summary.

Self-check before presenting: (a) every run dir has `grading.json`, (b) `benchmark.md` exists, (c) you're showing graded scores, not your own judgment. If any are false, go back.

---

## Step 5: Improve and iterate

1. Read **transcripts**, not just final outputs — trim unproductive steps the skill caused.
2. Generalize — avoid narrow fixes that only pass the tested examples.
3. Explain the *why* — don't just add rules.
4. Bundle repeated work — if every run wrote the same helper, lift it into `scripts/`.
5. Apply changes, rerun into `iteration-<N+1>/`, repeat until the user is satisfied or feedback dries up.

---

## Step 6: Description optimization

After the skill works (and evals if any), stop and ask:

> "Would you like me to optimize the skill's description for better triggering accuracy?"

- **Yes** → **read `references/description-optimization.md` now, before anything else.** It contains the full protocol — query generation, review, agent-driven eval loop, trigger detection, scoring. Don't improvise from memory.
- **No** → continue to packaging.

---

## Step 7: Packaging (always execute)

Run:

```bash
python3 -m scripts.package_skill <path/to/skill-folder>
```

If you have access to `present_files`, also present the packaged output.

Self-check before ending the conversation: did `scripts.package_skill` run? If not, run it now.

---

## Platform-specific commands

Use the command syntax that matches the current platform. The dangerous trap:

**Windows `mkdir` does NOT support `-p`.** `mkdir -p folder` creates a directory literally named `-p`. For nested dirs use PowerShell `New-Item -ItemType Directory -Path "parent/child" -Force` or `mkdir parent && mkdir parent\child` in cmd.

| Operation | Windows | Linux/macOS |
|-----------|---------|-------------|
| Create dir | `mkdir folder` / `New-Item -ItemType Directory -Path folder` | `mkdir -p folder` |
| Read file | `type file.txt` / `Get-Content file.txt` | `cat file.txt` |
| List | `dir` / `Get-ChildItem` | `ls -la` |
| Delete file | `del file.txt` / `Remove-Item file.txt` | `rm file.txt` |
| Delete dir | `rmdir folder` / `Remove-Item -Recurse folder` | `rm -rf folder` |
| Recursive find | `dir /s pattern` / `Get-ChildItem -Recurse -Filter pattern` | `find . -name pattern` |

---

## Reference files

- `agents/grader.md` — grading expectations against outputs
- `agents/comparator.md` — blind A/B comparison
- `agents/analyzer.md` — analyzing benchmark results
- `references/description-optimization.md` — full description optimization process
- `references/schemas.md` — JSON schemas for evals.json, grading.json, etc.
