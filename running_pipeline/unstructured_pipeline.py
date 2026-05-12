"""
Unstructured pipeline runner — runs HTML and summary sub-pipelines, then
materialises the HTML extraction JSON as TTL via SPARQL CONSTRUCT.

The summaries enrichment TTL is produced directly by Python (no SPARQL),
and is merged later by pipeline/merging/merge_all_ttl.py.
"""

from __future__ import annotations

try:
    from ._runner import run_python
except ImportError:
    from _runner import run_python


def main() -> None:
    run_python("running_pipeline/html_pipeline.py")
    run_python("running_pipeline/summary_pipeline.py")
    # Materialise HTML JSON → TTL via SPARQL Anything (also runs structured queries)
    run_python("pipeline/sparql/run_all_constructs.py")


if __name__ == "__main__":
    main()
