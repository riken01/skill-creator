#!/usr/bin/env python3
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes the agent to trigger (read the skill)
for a set of queries. Outputs results as JSON.

Adapted for OpenClaw: uses `openclaw agent` instead of `claude -p`.

Strategy: Creates a temporary skill in ~/.openclaw/workspace/skills/, sends the raw
user query via `openclaw agent`, then inspects the session log for a `read`
toolCall targeting the temporary skill's SKILL.md path — the same mechanism
OpenClaw uses natively to trigger skills.
"""

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from scripts.utils import parse_skill_md


EVAL_AGENT_NAME = "description-improvement"


def get_skills_dir() -> Path:
    """Return the OpenClaw user skills directory."""
    return Path.home() / ".openclaw" / "workspace" / "skills"


def _find_latest_session_log(agent_name: str) -> Path | None:
    """Find the latest session log for an agent."""
    sessions_dir = Path.home() / ".openclaw" / "agents" / agent_name / "sessions"
    if not sessions_dir.exists():
        return None
    logs = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return logs[0] if logs else None


def _check_new_lines_for_skill_read(
    log_path: Path, start_line: int, skill_path_fragment: str
) -> bool:
    """Check lines added after start_line for a `read` toolCall targeting a skill.

    OpenClaw logs tool calls as message blocks with type="toolCall":
        {"type": "toolCall", "name": "read", "arguments": {"path": "..."}}
    """
    if not log_path or not log_path.exists():
        return False

    try:
        with open(log_path) as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue

                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "toolCall":
                        continue
                    if block.get("name") != "read":
                        continue
                    arguments = block.get("arguments", {})
                    file_path = arguments.get("path", "")
                    if skill_path_fragment in file_path:
                        return True
    except OSError:
        return False

    return False


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    skills_dir: str,
    agent_name: str,
    model: str | None = None,
) -> bool:
    """Run a single query and return whether the skill was triggered.

    Creates a temporary skill, sends the query via CLI with /new prefix
    (to start a fresh context), then inspects the latest session log for
    a `read` toolCall targeting the temporary skill's SKILL.md.
    """
    unique_id = uuid.uuid4().hex[:8]
    temp_skill_name = f"_eval-{skill_name}-{unique_id}"
    temp_skill_dir = Path(skills_dir) / temp_skill_name
    temp_skill_file = temp_skill_dir / "SKILL.md"

    try:
        temp_skill_dir.mkdir(parents=True, exist_ok=True)
        # Use YAML block scalar to avoid breaking on quotes in description
        indented_desc = "\n  ".join(skill_description.split("\n"))
        skill_content = (
            f"---\n"
            f"name: {temp_skill_name}\n"
            f"description: |\n"
            f"  {indented_desc}\n"
            f"---\n\n"
            f"# {temp_skill_name}\n\n"
            f"This skill handles: {skill_description}\n"
        )
        temp_skill_file.write_text(skill_content)

        # Send query via CLI in a fresh session (/new)
        subprocess.run(
            [
                "openclaw", "agent",
                "--agent", agent_name,
                "--message", f"/new {query}",
            ],
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Check the latest session log for skill trigger
        session_log = _find_latest_session_log(agent_name)
        if not session_log:
            return False

        if _check_new_lines_for_skill_read(session_log, 0, temp_skill_name):
            return True
        if _check_new_lines_for_skill_read(session_log, 0, f"/{skill_name}/"):
            return True

        return False

    except Exception:
        return False
    finally:
        if temp_skill_dir.exists():
            shutil.rmtree(temp_skill_dir, ignore_errors=True)


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    timeout: int,
    skills_dir: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict:
    """Run the full eval set sequentially and return results.

    Creates a single temporary agent with an isolated workspace for the
    entire eval run.  Each query uses /new to start a fresh context.
    """
    agent_name = EVAL_AGENT_NAME
    agent_workspace = Path.home() / ".openclaw" / f"workspace-{agent_name}"
    source_workspace = Path.home() / ".openclaw" / "workspace"
    agent_dir = Path.home() / ".openclaw" / "agents" / agent_name

    # Create the eval agent if it doesn't already exist
    if not agent_dir.exists():
        subprocess.run(
            [
                "openclaw", "agents", "add", agent_name,
                "--workspace", str(agent_workspace),
                "--non-interactive",
            ],
            timeout=timeout,
            capture_output=True,
            check=True,
        )

        # Copy .md files from source workspace to the new workspace
        for md_file in source_workspace.glob("*.md"):
            if md_file.name == "BOOTSTRAP.md":
                continue
            shutil.copy2(md_file, agent_workspace / md_file.name)

    results = []

    query_triggers: dict[str, list[bool]] = {}
    query_items: dict[str, dict] = {}
    for item in eval_set:
        query = item["query"]
        query_items[query] = item
        if query not in query_triggers:
            query_triggers[query] = []
        for _ in range(runs_per_query):
            try:
                triggered = run_single_query(
                    query,
                    skill_name,
                    description,
                    timeout,
                    str(skills_dir),
                    agent_name,
                    model,
                )
                query_triggers[query].append(triggered)
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run trigger evaluation for a skill description")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout per query in seconds")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--model", default=None, help="Model (unused — openclaw uses its configured model)")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, content = parse_skill_md(skill_path)
    description = args.description or original_description
    skills_dir = get_skills_dir()

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        timeout=args.timeout,
        skills_dir=skills_dir,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
