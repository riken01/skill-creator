## Description Optimization

The description field in SKILL.md frontmatter is the primary mechanism that determines whether the agent invokes a skill. After creating or improving a skill, offer to optimize the description for better triggering accuracy.

### Step 1: Generate trigger eval queries

Create 20 eval queries — a mix of should-trigger and should-not-trigger. Save as JSON:

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

The queries must be realistic and something an OpenClaw user would actually type. Not abstract requests, but requests that are concrete and specific and have a good amount of detail. For instance, file paths, personal context about the user's job or situation, column names and values, company names, URLs. A little bit of backstory. Some might be in lowercase or contain abbreviations or typos or casual speech. Use a mix of different lengths, and focus on edge cases rather than making them clear-cut (the user will get a chance to sign off on them).

Bad: `"Format this data"`, `"Extract text from PDF"`, `"Create a chart"`

Good: `"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

For the **should-trigger** queries (8-10), think about coverage. You want different phrasings of the same intent — some formal, some casual. Include cases where the user doesn't explicitly name the skill or file type but clearly needs it. Throw in some uncommon use cases and cases where this skill competes with another but should win.

For the **should-not-trigger** queries (8-10), the most valuable ones are the near-misses — queries that share keywords or concepts with the skill but actually need something different. Think adjacent domains, ambiguous phrasing where a naive keyword match would trigger but shouldn't, and cases where the query touches on something the skill does but in a context where another tool is more appropriate.

The key thing to avoid: don't make should-not-trigger queries obviously irrelevant. "Write a fibonacci function" as a negative test for a PDF skill is too easy — it doesn't test anything. The negative cases should be genuinely tricky.

### Step 2: Review with user

Present the eval set to the user conversationally for review:

1. Show the eval queries in a clear format, grouped by category:

   **Should trigger (8-10 queries):**
   1. `"ok so my boss just sent me this xlsx file..."` ✅
   2. `"another query..."` ✅
   ...

   **Should NOT trigger (8-10 queries):**
   1. `"some near-miss query..."` ❌
   2. `"another query..."` ❌
   ...

2. Ask the user to review:
   - Are any should-trigger queries wrong? (should actually be negative)
   - Are any should-not-trigger queries wrong? (should actually be positive)
   - Any queries to add, remove, or rephrase?
   - Does the overall coverage look good?

3. Apply the user's edits and confirm the final eval set. If the user suggests changes, show the updated list and confirm again.

4. Once confirmed, save the final eval set as a JSON file (e.g., `<workspace>/trigger_eval.json`) in the same format as Step 1 — this file is required by `run_loop.py --eval-set` in the next step.

This step matters — bad eval queries lead to bad descriptions.

### Step 3: Run the optimization loop

Tell the user: "This will take some time — I'll run the optimization loop in the background and check on it periodically."

Save the eval set to the workspace, then run in the background:

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --max-iterations 5 \
  --verbose
```

The `--model` parameter is optional — openclaw uses its configured model automatically.

While it runs, periodically tail the output to give the user updates on which iteration it's on and what the scores look like.

This handles the full optimization loop automatically. It splits the eval set into 60% train and 40% held-out test, evaluates the current description (running each query 3 times to get a reliable trigger rate), then calls the agent to propose improvements based on what failed. It re-evaluates each new description on both train and test, iterating up to 5 times. When it's done, it prints JSON to stdout with `best_description` — selected by test score rather than train score to avoid overfitting. Read the JSON output and present the results to the user in conversation.

### Step 4: Apply the result

Take `best_description` from the JSON output and update the skill's SKILL.md frontmatter. Show the user before/after and report the scores.