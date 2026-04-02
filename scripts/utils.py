"""Shared utilities for skill-creator scripts."""

import shutil
import subprocess
from pathlib import Path


EVAL_AGENT_NAME = "description-improvement"


def get_skills_dir() -> Path:
    """Return the OpenClaw user skills directory."""
    return Path.home() / ".openclaw" / "skills"


def ensure_eval_agent(timeout: int = 60) -> str:
    """Create the eval agent if it doesn't exist, return agent name.

    Centralises agent setup so callers don't duplicate creation logic.
    """
    agent_dir = Path.home() / ".openclaw" / "agents" / EVAL_AGENT_NAME
    agent_workspace = Path.home() / ".openclaw" / f"workspace-{EVAL_AGENT_NAME}"
    source_workspace = Path.home() / ".openclaw" / "workspace"

    if not agent_dir.exists():
        subprocess.run(
            [
                "openclaw", "agents", "add", EVAL_AGENT_NAME,
                "--workspace", str(agent_workspace),
                "--non-interactive",
            ],
            timeout=timeout,
            capture_output=True,
            check=True,
        )

        for md_file in source_workspace.glob("*.md"):
            if md_file.name == "BOOTSTRAP.md":
                continue
            shutil.copy2(md_file, agent_workspace / md_file.name)

    return EVAL_AGENT_NAME



def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content)."""
    content = (skill_path / "SKILL.md").read_text()
    lines = content.split("\n")

    if lines[0].strip() != "---":
        raise ValueError("SKILL.md missing frontmatter (no opening ---)")

    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("SKILL.md missing frontmatter (no closing ---)")

    name = ""
    description = ""
    frontmatter_lines = lines[1:end_idx]
    i = 0
    while i < len(frontmatter_lines):
        line = frontmatter_lines[i]
        if line.startswith("name:"):
            name = line[len("name:"):].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            value = line[len("description:"):].strip()
            # Handle YAML multiline indicators (>, |, >-, |-)
            if value in (">", "|", ">-", "|-"):
                continuation_lines: list[str] = []
                i += 1
                while i < len(frontmatter_lines) and (frontmatter_lines[i].startswith("  ") or frontmatter_lines[i].startswith("\t")):
                    continuation_lines.append(frontmatter_lines[i].strip())
                    i += 1
                description = " ".join(continuation_lines)
                continue
            else:
                description = value.strip('"').strip("'")
        i += 1

    return name, description, content
