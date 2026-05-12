"""
HTML pipeline runner — extract structured JSON from EUR-Lex HTML, run the
five-stage extraction pipeline, then serialise to TTL.

Stages:
  1. Parser            — HTML → eu_ai_act_articles.json
  2. Rule-based        — annex bullets, Article 5 practices, etc. → rule_extraction.json
  3. LLM               — obligations, powers, conditions → llm_extraction.json
  4. NER + regex       — deadlines, fines, cross-refs → ner_enrichment.json
  5. Serialiser        — merge all 3 JSON files into eu_ai_act_html.ttl
"""

from __future__ import annotations

try:
    from ._runner import run_python
except ImportError:
    from _runner import run_python


def main() -> None:
    run_python("pipeline/unstructured/html/eurlex_html_to_json.py")
    run_python("pipeline/unstructured/html/rule_based_extract.py")
    run_python("pipeline/unstructured/html/llm_extract.py")
    run_python("pipeline/unstructured/html/ner_enrich.py")
    run_python("pipeline/unstructured/html/serialise_llm_extraction.py")


if __name__ == "__main__":
    main()