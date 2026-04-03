## Description Optimization — Complete Protocol

The description field in SKILL.md frontmatter is the primary mechanism that determines whether the agent invokes a skill. This document contains the full protocol for optimizing it. Follow every step in order.

---

### Step 1: Generate 12 trigger eval queries

Create 12 eval queries — 6 should-trigger and 6 should-not-trigger. Save as JSON:

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

The queries must be realistic and something an OpenClaw user would actually type. Not abstract requests, but requests that are concrete and specific and have a good amount of detail. For instance, file paths, personal context about the user's job or situation, column names and values, company names, URLs. A little bit of backstory. Some might be in lowercase or contain abbreviations or typos or casual speech. Use a mix of different lengths, and focus on edge cases rather than making them clear-cut (the user will get a chance to sign off on them).

Bad: `"Format this data"`, `"Extract text from PDF"`, `"Create a chart"`

Good: `"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

For the **should-trigger** queries (6), think about coverage. You want different phrasings of the same intent — some formal, some casual. Include cases where the user doesn't explicitly name the skill or file type but clearly needs it. Throw in some uncommon use cases and cases where this skill competes with another but should win.

For the **should-not-trigger** queries (6), the most valuable ones are the near-misses — queries that share keywords or concepts with the skill but actually need something different. Think adjacent domains, ambiguous phrasing where a naive keyword match would trigger but shouldn't, and cases where the query touches on something the skill does but in a context where another tool is more appropriate.

The key thing to avoid: don't make should-not-trigger queries obviously irrelevant. "Write a fibonacci function" as a negative test for a PDF skill is too easy — it doesn't test anything. The negative cases should be genuinely tricky.

---

### Step 2: Review with user

Present the eval set to the user conversationally for review:

1. Show the eval queries in a clear format, grouped by category:

   **Should trigger (6 queries):**
   1. `"ok so my boss just sent me this xlsx file..."` ✅
   2. `"another query..."` ✅
   ...

   **Should NOT trigger (6 queries):**
   1. `"some near-miss query..."` ❌
   2. `"another query..."` ❌
   ...

2. Ask the user to review:
   - Are any should-trigger queries wrong? (should actually be negative)
   - Are any should-not-trigger queries wrong? (should actually be positive)
   - Any queries to add, remove, or rephrase?
   - Does the overall coverage look good?

3. Apply the user's edits and confirm the final eval set. If the user suggests changes, show the updated list and confirm again.

4. Once confirmed, save the final eval set as a JSON file (e.g., `<workspace>/trigger_eval.json`).

This step matters — bad eval queries lead to bad descriptions.

---

### Step 3: Run the optimization loop (agent-driven)

You drive the loop directly. For each iteration, test every query by spawning a subagent, checking if it reads the temp skill, and cancelling early when triggered.

#### Setup

1. **Split eval set:** 60% train, 40% test (stratified by should_trigger). Use a fixed seed for reproducibility.
2. **Create results workspace:** `<workspace>/description-optimization/`
3. **Set** `current_description` = skill's current description from frontmatter.

#### For each iteration (1 to 5):

**A. Evaluate all queries**

For each query in `train_set + test_set`:

1. **Create temp skill:** Write a temporary `SKILL.md` at `~/.openclaw/workspace/skills/_eval-<skill-name>-<random-8-hex>/SKILL.md` with:
   ```yaml
   ---
   name: _eval-<skill-name>-<hex>
   description: |
     <current_description>
   ---
   # _eval-<skill-name>-<hex>
   This skill handles: <current_description>
   ```

2. **Spawn subagent** with the raw query as the task. Note the `runId` returned by `sessions_spawn`.

3. **Monitor for trigger:** While the subagent is running, check its session log for a `read` toolCall targeting the temp skill. See "How to find the session log" and "How to detect trigger" below.
   - **If triggered** (read detected): Cancel the subagent immediately. Record `triggered: true`.
   - **If subagent completes** without triggering: Record `triggered: false`.

4. **Cleanup:** Delete the temp skill directory.

5. **Record result:** `{query, should_trigger, triggered, pass}` where `pass = (should_trigger == triggered)`.

**B. Compute scores**

Split results back into train/test by matching queries. Compute for each set:
- passed / total
- precision = TP / (TP + FP)
- recall = TP / (TP + FN)
- accuracy = (TP + TN) / total

**C. Check exit conditions**

- All train queries pass → exit with "all_passed"
- Max iterations (5) reached → exit with "max_iterations"
- Otherwise → continue to D

**D. Improve description**

Analyze **train failures only** (do NOT look at test results — this prevents overfitting). Consider:
- Which should-trigger queries failed to trigger? Why might the description miss them?
- Which should-not-trigger queries falsely triggered? What's too broad?

Write a new description (100–200 words, hard limit 1024 chars). Rules:
- Generalize from failures — don't list specific queries.
- Try structurally different phrasings each iteration.
- Use imperative form ("Use this skill for...").
- Focus on user intent, not implementation details.

Update `current_description` and continue the loop.

**E. Log iteration**

Append to `<workspace>/description-optimization/history.json`:
```json
{
  "iteration": N,
  "description": "...",
  "train_passed": X, "train_total": Y,
  "test_passed": X, "test_total": Y
}
```

**After loop:** Select the best iteration by **test score** (or train if no test set).

---

### How to find the subagent's session log

1. After spawning, note the `runId`.
2. Read `~/.openclaw/subagents/runs.json` → find the run entry → get `startedAt` timestamp.
3. In `~/.openclaw/agents/main/sessions/`, find the `.jsonl` file created at the closest timestamp that contains "Subagent Context" in its first few lines.

### How to detect trigger

Scan the session log for a `read` toolCall in the `message.content` array of any assistant message:

```json
{"type": "toolCall", "name": "read", "arguments": {"path": ".../_eval-<name>-<hex>/SKILL.md"}}
```

Match on: the `path` (or `file`) argument contains the temp skill name fragment (e.g., `_eval-book-tracker-a1b2c3d4`).

---

### Step 4: Present and apply

Show original vs. best description, train/test scores, iteration count, key observations. If user approves, update the skill's SKILL.md frontmatter with `best_description`.
