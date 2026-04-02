#!/usr/bin/env python3
"""Tests for run_loop.py and run_eval.py.

Usage:
    # Unit tests only (no server needed):
    cd ~/.openclaw/skills/skill-creator && python -m pytest scripts/test_run_loop.py -v

    # Include integration smoke test (needs live openclaw):
    cd ~/.openclaw/skills/skill-creator && python -m pytest scripts/test_run_loop.py -v -k integration --run-integration
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_loop import run_loop, split_eval_set


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_EVAL_SET = [
    {"query": "我在看《三体》，记录一下", "should_trigger": True},
    {"query": "把《百年孤独》加入书单", "should_trigger": True},
    {"query": "《人类简史》读完了", "should_trigger": True},
    {"query": "我有哪些想读的书", "should_trigger": True},
    {"query": "读书无用论你怎么看", "should_trigger": False},
    {"query": "说明书在哪里", "should_trigger": False},
    {"query": "书架怎么整理", "should_trigger": False},
    {"query": "教科书太难了", "should_trigger": False},
]


@pytest.fixture
def tmp_skill(tmp_path):
    """Create a temporary skill directory with a SKILL.md."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill for unit testing.\n"
        "---\n\n"
        "# test-skill\n\n"
        "This is a test skill used for automated tests.\n"
    )
    return skill_dir


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Create a temporary skills directory."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="Run integration tests that require a live openclaw agent",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip = pytest.mark.skip(reason="needs --run-integration flag")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Unit tests — no server needed
# ---------------------------------------------------------------------------

class TestSplitEvalSet:
    """Tests for the train/test split logic."""

    def test_basic_split(self):
        train, test = split_eval_set(SAMPLE_EVAL_SET, holdout=0.5, seed=42)
        assert len(train) + len(test) == len(SAMPLE_EVAL_SET)
        assert len(test) > 0
        assert len(train) > 0

    def test_stratified(self):
        """Both train and test should contain positive and negative examples."""
        train, test = split_eval_set(SAMPLE_EVAL_SET, holdout=0.5, seed=42)
        assert any(e["should_trigger"] for e in train)
        assert any(not e["should_trigger"] for e in train)
        assert any(e["should_trigger"] for e in test)
        assert any(not e["should_trigger"] for e in test)

    def test_deterministic(self):
        """Same seed produces the same split."""
        train1, test1 = split_eval_set(SAMPLE_EVAL_SET, holdout=0.4, seed=123)
        train2, test2 = split_eval_set(SAMPLE_EVAL_SET, holdout=0.4, seed=123)
        assert train1 == train2
        assert test1 == test2

    def test_zero_holdout(self):
        """holdout=0 still holds out at least 1 per group (min is 1)."""
        train, test = split_eval_set(SAMPLE_EVAL_SET, holdout=0.0, seed=42)
        assert len(test) == 2  # 1 trigger + 1 no-trigger


# ---------------------------------------------------------------------------
# Helper to build fake eval results
# ---------------------------------------------------------------------------

def _make_eval_result(eval_set, description, all_pass=False, pass_rate=0.5):
    """Build a fake eval result dict."""
    import random
    results = []
    for item in eval_set:
        if all_pass:
            did_pass = True
            triggers = 1 if item["should_trigger"] else 0
        else:
            triggered = random.random() < pass_rate
            did_pass = (triggered == item["should_trigger"])
            triggers = 1 if triggered else 0
        results.append({
            "query": item["query"],
            "should_trigger": item["should_trigger"],
            "trigger_rate": float(triggers),
            "triggers": triggers,
            "runs": 1,
            "pass": did_pass,
        })
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    return {
        "skill_name": "test-skill",
        "description": description,
        "results": results,
        "summary": {"total": total, "passed": passed, "failed": total - passed},
    }


class TestRunLoopMocked:
    """Tests for run_loop with mocked eval and improve functions."""

    def test_all_pass_first_iteration(self, tmp_skill, tmp_skills_dir):
        """If everything passes on iteration 1, the loop exits immediately."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model, agent_name=None):
            return _make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir), \
             patch("scripts.run_loop.ensure_eval_agent", return_value="mock-agent"):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=1,
                trigger_threshold=0.5,
                holdout=0.0,
                verbose=False,
            )

        assert result["iterations_run"] == 1
        assert "all_passed" in result["exit_reason"]

    def test_max_iterations_reached(self, tmp_skill, tmp_skills_dir):
        """Loop should stop after max_iterations if never all-pass."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model, agent_name=None):
            return _make_eval_result(eval_set, description, all_pass=False, pass_rate=0.6)

        def mock_improve(skill_name, skill_content, current_description,
                         eval_results, history, model=None, test_results=None,
                         log_dir=None, iteration=None, agent_name=None):
            return f"improved description v{len(history) + 1}"

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.improve_description", side_effect=mock_improve), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir), \
             patch("scripts.run_loop.ensure_eval_agent", return_value="mock-agent"):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override="initial description",
                timeout=10,
                max_iterations=3,
                runs_per_query=1,
                trigger_threshold=0.5,
                holdout=0.0,
                verbose=False,
            )

        assert result["iterations_run"] == 3
        assert "max_iterations" in result["exit_reason"]
        assert len(result["history"]) == 3

    def test_holdout_split(self, tmp_skill, tmp_skills_dir):
        """With holdout > 0, result should include train/test sizes."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model, agent_name=None):
            return _make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir), \
             patch("scripts.run_loop.ensure_eval_agent", return_value="mock-agent"):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=1,
                trigger_threshold=0.5,
                holdout=0.4,
                verbose=False,
            )

        assert result["train_size"] > 0
        assert result["test_size"] > 0
        assert result["train_size"] + result["test_size"] == len(SAMPLE_EVAL_SET)

    def test_history_structure(self, tmp_skill, tmp_skills_dir):
        """Each history entry should have the expected fields."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model, agent_name=None):
            return _make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir), \
             patch("scripts.run_loop.ensure_eval_agent", return_value="mock-agent"):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=1,
                trigger_threshold=0.5,
                holdout=0.4,
                verbose=False,
            )

        h = result["history"][0]
        for key in ("iteration", "description", "train_passed", "train_total", "train_results"):
            assert key in h, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Integration test — requires live openclaw
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegration:
    """Smoke test that runs 1 iteration against the real openclaw agent.

    Run with: pytest scripts/test_run_loop.py -v -k integration --run-integration
    """

    def test_run_loop_one_iteration(self, tmp_path):
        """Run the full loop for 1 iteration to verify end-to-end plumbing."""
        skill_dir = tmp_path / "integration-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: integration-skill\n"
            "description: Trigger for book tracking and reading list management.\n"
            "---\n\n"
            "# integration-skill\n\n"
            "Track books and reading progress.\n"
        )
        # Minimal eval set: 1 positive + 1 negative
        eval_set = [
            {"query": "把三体加入书单", "should_trigger": True},
            {"query": "帮我写代码", "should_trigger": False},
        ]

        result = run_loop(
            eval_set=eval_set,
            skill_path=skill_dir,
            description_override=None,
            timeout=60,
            max_iterations=1,
            runs_per_query=1,
            trigger_threshold=0.5,
            holdout=0.0,
            verbose=True,
        )

        assert result["iterations_run"] == 1
        assert "history" in result
        assert len(result["history"]) == 1
        print(f"\nIntegration result: {json.dumps(result['history'][0], indent=2, ensure_ascii=False)}")
