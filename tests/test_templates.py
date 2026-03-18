import pytest
from agenttee.templates import TemplateIndex


class TestTemplateIndex:
    def test_groups_similar_lines(self):
        lines = [
            "2024-01-15 INFO user alice logged in",
            "2024-01-15 INFO user bob logged in",
            "2024-01-15 ERROR database connection failed",
        ]
        idx = TemplateIndex()
        idx.ingest(lines)
        stats = idx.stats()
        # Two login lines should share a template, error should be separate
        assert stats["unique_templates"] >= 2

    def test_stats_counts(self):
        lines = ["hello world"] * 10 + ["goodbye"] * 5
        idx = TemplateIndex()
        idx.ingest(lines)
        stats = idx.stats()
        assert stats["total_lines"] == 15

    def test_framework_score(self):
        """Lines with timestamps + log levels should score higher."""
        idx = TemplateIndex()
        idx.ingest([
            "2024-01-15T10:00:00Z INFO [app.server] starting...",
            "some random output",
        ])
        framework_sigs = [
            (sig, c) for sig, c in idx.clusters.items()
            if c.framework_score > 0
        ]
        assert len(framework_sigs) >= 1

    def test_empty_input(self):
        idx = TemplateIndex()
        idx.ingest([])
        stats = idx.stats()
        assert stats["total_lines"] == 0


class TestTopTemplates:
    def test_returns_most_frequent(self):
        # Structurally different lines so they get different signatures
        lines = (
            ["2024-01-15 INFO request ok"] * 50
            + ["ERROR timeout at 192.168.1.1"] * 10
            + ["asset bundle.js 500 KiB"] * 1
        )
        idx = TemplateIndex()
        idx.ingest(lines)
        top = idx.top_templates(n=2)
        assert len(top) == 2
        assert top[0].count >= top[1].count
