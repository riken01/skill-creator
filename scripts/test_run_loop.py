#!/usr/bin/env python3
"""Command-line tests for run_loop.py.

Usage:
    # Run all unit tests (no server needed):
    python -m pytest scripts/test_run_loop.py -v

    # Run a quick integration smoke test against a live OpenClaw WebSocket server:
    python -m pytest scripts/test_run_loop.py -v -k integration --run-integration
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_loop import run_loop, split_eval_set
from scripts.run_eval import run_single_query, _send_ws_query
from scripts.improve_description import _call_openclaw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_EVAL_SET = [
    {"query": "帮我看看 Steam 有什么好玩的游戏", "should_trigger": True},
    {"query": "Steam 最近有什么打折的", "should_trigger": True},
    {"query": "推荐一些模拟经营类游戏", "should_trigger": True},
    {"query": "Steam 愿望单有更新吗", "should_trigger": True},
    {"query": "帮我写一个 Python 脚本", "should_trigger": False},
    {"query": "今天天气怎么样", "should_trigger": False},
    {"query": "帮我翻译这段话", "should_trigger": False},
    {"query": "这个 bug 怎么修", "should_trigger": False},
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
    """Create a temporary skills directory (for temp skill creation)."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def eval_set_file(tmp_path):
    """Write the sample eval set to a temp JSON file."""
    f = tmp_path / "eval_set.json"
    f.write_text(json.dumps(SAMPLE_EVAL_SET))
    return f


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="Run integration tests that require a live OpenClaw WebSocket server",
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
        train_pos = [e for e in train if e["should_trigger"]]
        train_neg = [e for e in train if not e["should_trigger"]]
        test_pos = [e for e in test if e["should_trigger"]]
        test_neg = [e for e in test if not e["should_trigger"]]
        assert len(train_pos) > 0
        assert len(train_neg) > 0
        assert len(test_pos) > 0
        assert len(test_neg) > 0

    def test_deterministic(self):
        """Same seed produces the same split."""
        train1, test1 = split_eval_set(SAMPLE_EVAL_SET, holdout=0.4, seed=123)
        train2, test2 = split_eval_set(SAMPLE_EVAL_SET, holdout=0.4, seed=123)
        assert train1 == train2
        assert test1 == test2

    def test_zero_holdout(self):
        """holdout=0 should still hold out at least 1 per group (min is 1)."""
        train, test = split_eval_set(SAMPLE_EVAL_SET, holdout=0.0, seed=42)
        # With holdout=0, max(1, int(n*0))=1, so 1 per group goes to test
        assert len(test) == 2  # 1 trigger + 1 no-trigger


class TestRunLoopMocked:
    """Tests for run_loop with mocked eval and improve functions."""

    def _make_eval_result(self, eval_set, description, all_pass=False, pass_rate=0.5):
        """Build a fake eval result dict."""
        results = []
        for item in eval_set:
            if all_pass:
                did_pass = True
                triggers = 3 if item["should_trigger"] else 0
            else:
                import random
                triggered = random.random() < pass_rate
                did_pass = (triggered == item["should_trigger"])
                triggers = 3 if triggered else 0
            results.append({
                "query": item["query"],
                "should_trigger": item["should_trigger"],
                "trigger_rate": triggers / 3,
                "triggers": triggers,
                "runs": 3,
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

    def test_all_pass_first_iteration(self, tmp_skill, tmp_skills_dir):
        """If everything passes on iteration 1, the loop should exit immediately."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model):
            return self._make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=3,
                trigger_threshold=0.5,
                holdout=0.0,
                verbose=False,
            )

        assert result["iterations_run"] == 1
        assert "all_passed" in result["exit_reason"]

    def test_max_iterations_reached(self, tmp_skill, tmp_skills_dir):
        """Loop should stop after max_iterations if never all-pass."""
        call_count = 0

        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model):
            nonlocal call_count
            call_count += 1
            return self._make_eval_result(eval_set, description, all_pass=False, pass_rate=0.6)

        def mock_improve(skill_name, skill_content, current_description,
                         eval_results, history, model=None, test_results=None,
                         log_dir=None, iteration=None):
            return f"improved description v{len(history) + 1}"

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.improve_description", side_effect=mock_improve), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override="initial description",
                timeout=10,
                max_iterations=3,
                runs_per_query=3,
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
                          runs_per_query, trigger_threshold, model):
            return self._make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=3,
                trigger_threshold=0.5,
                holdout=0.4,
                verbose=False,
            )

        assert result["train_size"] > 0
        assert result["test_size"] > 0
        assert result["train_size"] + result["test_size"] == len(SAMPLE_EVAL_SET)

    def test_best_description_selected(self, tmp_skill, tmp_skills_dir):
        """The best description should be from the highest-scoring iteration."""
        iteration_counter = [0]

        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model):
            iteration_counter[0] += 1
            # Iteration 2 scores perfectly
            all_pass = (iteration_counter[0] == 2)
            return self._make_eval_result(eval_set, description, all_pass=all_pass, pass_rate=0.3)

        def mock_improve(skill_name, skill_content, current_description,
                         eval_results, history, model=None, test_results=None,
                         log_dir=None, iteration=None):
            return f"improved-v{len(history) + 1}"

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.improve_description", side_effect=mock_improve), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override="initial",
                timeout=10,
                max_iterations=3,
                runs_per_query=3,
                trigger_threshold=0.5,
                holdout=0.0,
                verbose=False,
            )

        # Iteration 2 had all_pass, so best should be the description from iter 2
        assert result["best_description"] == "improved-v1"

    def test_history_structure(self, tmp_skill, tmp_skills_dir):
        """Each history entry should have the expected fields."""
        def mock_run_eval(eval_set, skill_name, description, timeout, skills_dir,
                          runs_per_query, trigger_threshold, model):
            return self._make_eval_result(eval_set, description, all_pass=True)

        with patch("scripts.run_loop.run_eval", side_effect=mock_run_eval), \
             patch("scripts.run_loop.get_skills_dir", return_value=tmp_skills_dir):
            result = run_loop(
                eval_set=SAMPLE_EVAL_SET,
                skill_path=tmp_skill,
                description_override=None,
                timeout=10,
                max_iterations=5,
                runs_per_query=3,
                trigger_threshold=0.5,
                holdout=0.4,
                verbose=False,
            )

        h = result["history"][0]
        assert "iteration" in h
        assert "description" in h
        assert "train_passed" in h
        assert "train_total" in h
        assert "train_results" in h


# ---------------------------------------------------------------------------
# Integration test — requires a live OpenClaw WebSocket server
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegration:
    """Smoke tests that hit the real WebSocket server.

    Run with: pytest scripts/test_run_loop.py -v -k integration --run-integration
    """

    def test_ws_connection(self):
        """Verify WebSocket connection and basic round-trip."""
        session_key = "_test-ws-ping"
        result = _send_ws_query(session_key, "回复OK", timeout=30)
        assert result is True, "WebSocket connection or query failed"

    def test_call_openclaw_returns_text(self):
        """Verify _call_openclaw returns non-empty text via WebSocket."""
        text = _call_openclaw("请回复一个字：好", timeout=30)
        assert len(text) > 0, "Got empty response from OpenClaw"

    def test_run_single_query(self, tmp_path):
        """Verify run_single_query creates temp skill, sends query, and cleans up."""
        skills_dir = Path.home() / ".openclaw" / "workspace" / "skills"
        triggered = run_single_query(
            query="这是一个测试查询",
            skill_name="test-integration",
            skill_description="Integration test skill — trigger for any test query.",
            timeout=30,
            skills_dir=str(skills_dir),
        )
        # We don't assert triggered True/False — just that it didn't crash
        assert isinstance(triggered, bool)

    def test_run_loop_one_iteration(self, tmp_path):
        """Run the full loop for 1 iteration to verify end-to-end plumbing."""
        skill_dir = tmp_path / "integration-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: integration-skill\n"
            "description: Trigger for Steam game recommendations.\n"
            "---\n\n"
            "# integration-skill\n\n"
            "Recommend Steam games.\n"
        )
        eval_set = [
            {"query": "Steam 有什么好游戏", "should_trigger": True},
            {"query": "帮我写代码", "should_trigger": False},
        ]

        result = run_loop(
            eval_set=eval_set,
            skill_path=skill_dir,
            description_override=None,
            timeout=30,
            max_iterations=1,
            runs_per_query=1,
            trigger_threshold=0.5,
            holdout=0.0,
            verbose=True,
        )

        assert result["iterations_run"] == 1
        assert "history" in result
        assert len(result["history"]) == 1
