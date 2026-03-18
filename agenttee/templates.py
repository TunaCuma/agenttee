"""
Template engine: clusters tokenized lines by signature, scores templates,
and provides the building blocks for compression strategies.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .tokenizer import TokenType, TokenizedLine, tokenize_line


@dataclass
class TemplateCluster:
    signature: str
    lines: list[TokenizedLine] = field(default_factory=list)
    first_seen_idx: int = 0
    framework_score: float = 0.0
    representative: str = ""

    @property
    def count(self) -> int:
        return len(self.lines)

    def compute_score(self, total_lines: int):
        """Higher score = more likely framework/noise, lower = more likely signal."""
        score = 0.0

        has_ts = any(t.type == TokenType.TIMESTAMP for t in self.lines[0].tokens)
        has_level = any(t.type == TokenType.LEVEL for t in self.lines[0].tokens)
        has_ns = any(t.type == TokenType.NAMESPACE for t in self.lines[0].tokens)
        has_progress = any(t.type == TokenType.PROGRESS for t in self.lines[0].tokens)

        if has_ts:
            score += 2.0
        if has_level:
            score += 3.0
        if has_ns:
            score += 2.0
        if has_progress:
            score += 2.0

        frequency_ratio = self.count / total_lines
        if frequency_ratio > 0.01:
            score += 2.0
        if frequency_ratio > 0.05:
            score += 3.0
        if frequency_ratio > 0.1:
            score += 5.0

        self.framework_score = score


@dataclass
class TemplateIndex:
    clusters: dict[str, TemplateCluster] = field(default_factory=dict)
    line_order: list[tuple[str, int]] = field(default_factory=list)  # (signature, index_in_cluster)
    total_lines: int = 0

    def ingest(self, lines: list[str]):
        self.total_lines = len(lines)
        for i, raw_line in enumerate(lines):
            tl = tokenize_line(raw_line)
            sig = tl.signature

            if sig not in self.clusters:
                self.clusters[sig] = TemplateCluster(
                    signature=sig,
                    first_seen_idx=i,
                    representative=tl.clean,
                )

            cluster = self.clusters[sig]
            self.line_order.append((sig, len(cluster.lines)))
            cluster.lines.append(tl)

        for cluster in self.clusters.values():
            cluster.compute_score(self.total_lines)

    def top_templates(self, n: int = 20) -> list[TemplateCluster]:
        return sorted(
            self.clusters.values(),
            key=lambda c: c.count,
            reverse=True,
        )[:n]

    def unique_templates(self) -> int:
        return len(self.clusters)

    def stats(self) -> dict:
        clusters = sorted(self.clusters.values(), key=lambda c: c.count, reverse=True)
        top10_count = sum(c.count for c in clusters[:10])
        return {
            "total_lines": self.total_lines,
            "unique_templates": self.unique_templates(),
            "top10_cover_pct": round(top10_count / self.total_lines * 100, 1) if self.total_lines else 0,
            "top10": [(c.signature, c.count, c.representative[:80]) for c in clusters[:10]],
        }
