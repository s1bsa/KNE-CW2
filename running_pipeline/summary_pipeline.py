"""
Summary pipeline runner — scrape plain-language summaries from
artificialintelligenceact.eu (articles + annexes) and produce enrichment
TTL that attaches :hasSummary text to existing Article/Annex URIs.

The summaries pipeline no longer creates its own instances; it enriches
the canonical URIs created by the HTML pipeline.
"""

from __future__ import annotations

try:
    from ._runner import run_python
except ImportError:
    from _runner import run_python


def main() -> None:
    run_python("pipeline/unstructured/summaries/scrape_ai_act_summaries.py")
    run_python("pipeline/unstructured/summaries/enrich_summaries_to_ttl.py")


if __name__ == "__main__":
    main()
