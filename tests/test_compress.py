import pytest
from agenttee.compress import (
    strategy_template_dedup,
    strategy_semantic,
    strategy_agent,
    strategy_agent_hybrid,
    strategy_conservative,
    compress,
)


class TestTemplateDedup:
    def test_collapses_identical_lines(self):
        lines = ["INFO request handled"] * 20
        result = strategy_template_dedup(lines)
        assert len(result) < len(lines)

    def test_preserves_structurally_distinct_lines(self):
        lines = [
            "2024-01-15 INFO user logged in",
            "ERROR: connection timeout at 192.168.1.1:5432",
            "asset bundle.js 500 KiB [emitted]",
        ]
        result = strategy_template_dedup(lines)
        assert len(result) == len(lines)

    def test_empty_input(self):
        assert strategy_template_dedup([]) == []


class TestSemanticCompression:
    def test_webpack_progress_collapse(self):
        lines = [f"<s> [webpack.Progress] {i}% building" for i in range(0, 101)]
        result = strategy_semantic(lines)
        assert len(result) < 10

    def test_docker_layer_collapse(self):
        layers = [f"abc123def456: Pushing" for _ in range(20)]
        result = strategy_semantic(layers)
        assert len(result) < len(layers)

    def test_identical_run_collapse(self):
        lines = ["same warning message"] * 10
        result = strategy_semantic(lines)
        assert len(result) <= 2


class TestAgentStrategy:
    def test_asset_listing_collapse(self):
        lines = [f"asset bundle{i}.js 100 KiB [emitted]" for i in range(20)]
        result = strategy_agent(lines)
        assert len(result) <= 3

    def test_warning_truncation(self):
        lines = [
            "WARNING in ./src/components/Foo.js",
            "export 'Bar' (imported as 'Bar') was not found in './utils'",
            "(possible exports: Baz, Qux)",
        ]
        result = strategy_agent(lines)
        assert len(result) == 1
        assert "missing export" in result[0] or "WARN" in result[0]

    def test_structlog_grouping(self):
        lines = []
        for i in range(10):
            lines.append(f'time="2024-01-15T10:0{i}:00Z" level=warning msg="could not map pods" service=api')
        result = strategy_agent(lines)
        assert len(result) < len(lines)


class TestConservativeStrategy:
    def test_less_aggressive_than_agent(self):
        """Conservative should keep more lines than agent hybrid."""
        lines = [f"INFO request {i} handled in {i*10}ms" for i in range(50)]
        conservative = strategy_conservative(lines)
        aggressive = strategy_agent_hybrid(lines)
        assert len(conservative) >= len(aggressive)

    def test_still_collapses_progress(self):
        lines = [f"<s> [webpack.Progress] {i}% building" for i in range(100)]
        result = strategy_conservative(lines)
        assert len(result) < 10

    def test_keeps_short_identical_runs(self):
        """Runs of 3 or fewer identical lines should be kept as-is."""
        lines = ["same line"] * 3
        result = strategy_conservative(lines)
        assert len(result) == 3

    def test_collapses_long_identical_runs(self):
        lines = ["same line"] * 10
        result = strategy_conservative(lines)
        assert len(result) == 2


class TestAgentHybrid:
    def test_maximum_compression(self):
        lines = [f"INFO request {i}" for i in range(100)]
        result = strategy_agent_hybrid(lines)
        assert len(result) < len(lines)


class TestCompressFunction:
    def test_compact_mode(self):
        lines = ["hello"] * 20
        result = compress(lines, "compact")
        assert len(result) < len(lines)

    def test_conservative_mode(self):
        lines = ["hello"] * 20
        result = compress(lines, "conservative")
        assert len(result) < len(lines)

    def test_unknown_mode_falls_back(self):
        lines = ["hello"] * 20
        result = compress(lines, "nonexistent")
        assert len(result) < len(lines)
