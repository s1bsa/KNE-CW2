"""
Structured pipeline runner — extract EUR-Lex CELLAR XML metadata into JSON.

The SPARQL CONSTRUCT step that materialises this output as TTL is run
separately by the unified pipeline/sparql/run_all_constructs.py (which is
called from unstructured_pipeline.py once both unstructured sub-pipelines
have produced their JSON inputs).
"""

from __future__ import annotations

try:
    from ._runner import run_python
except ImportError:
    from _runner import run_python


def main() -> None:
    run_python("pipeline/structured/extract_xml_metadata.py")


if __name__ == "__main__":
    main()
