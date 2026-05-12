"""
Unified runner for all SPARQL Anything CONSTRUCT queries across pipeline
layers. Walks pipeline/sparql/<layer>/, runs every .sparql file via the
SPARQL Anything jar, concatenates the per-query outputs, and writes a
single merged TTL per layer with deduplicated prefixes prepended.

Currently runs the structured layer only — the HTML layer bypasses SPARQL
Anything (direct rdflib serialisation in serialise_llm_extraction.py) and
the summaries layer is direct enrichment (enrich_summaries_to_ttl.py).

Output: data/structured/eu_ai_act_metadata.ttl
"""

import glob
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JAR = os.path.join(REPO_ROOT, "tools", "sparql-anything-v1.1.0.jar")

LAYERS = [
    {
        "name": "Structured",
        "sparql_dir": os.path.join(REPO_ROOT, "pipeline", "sparql", "structured"),
        "temp_dir":   os.path.join(REPO_ROOT, "data", "structured", "_sparql_temp"),
        "output":     os.path.join(REPO_ROOT, "data", "structured", "eu_ai_act_metadata.ttl"),
    },
]

PREFIXES = """\
@prefix :        <https://example.org/eu-ai-act-compliance#> .
@prefix airo:    <https://w3id.org/airo#> .
@prefix dct:     <http://purl.org/dc/terms/> .
@prefix dpv:     <https://w3id.org/dpv#> .
@prefix eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
"""


def run_layer(layer: dict) -> bool:
    name = layer["name"]
    sparql_dir = layer["sparql_dir"]
    temp_dir = layer["temp_dir"]
    final_output = layer["output"]

    queries = sorted(glob.glob(os.path.join(sparql_dir, "*.sparql")))
    if not queries:
        print(f"  [{name}] No .sparql files found in {sparql_dir}")
        return False

    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(os.path.dirname(final_output), exist_ok=True)

    print(f"\n--- {name} layer ({len(queries)} queries) ---")
    temp_files = []
    for query in queries:
        qname = os.path.splitext(os.path.basename(query))[0]
        out_path = os.path.join(temp_dir, f"{qname}.ttl")
        print(f"  RUN  {qname}", end=" ", flush=True)

        result = subprocess.run(
            ["java", "-jar", JAR, "--query", query, "--output", out_path],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            print(f"FAIL")
            print(f"       {result.stderr.strip()[:300]}")
            continue

        with open(out_path) as f:
            lines = sum(1 for _ in f)
        print(f"OK ({lines} lines)")
        temp_files.append(out_path)

    if not temp_files:
        print(f"  [{name}] No output produced")
        return False

    # Merge into a single layer file
    print(f"  MERGE → {os.path.relpath(final_output, REPO_ROOT)}")
    with open(final_output, "w") as out:
        out.write(PREFIXES + "\n")
        for ttl in temp_files:
            qname = os.path.splitext(os.path.basename(ttl))[0]
            out.write(f"\n# --- {qname} ---\n")
            with open(ttl) as f:
                for line in f:
                    if line.startswith("@prefix") or not line.strip():
                        continue
                    if line.lstrip().upper().startswith("PREFIX "):
                        continue
                    out.write(line)

    # Cleanup temp
    for ttl in temp_files:
        os.remove(ttl)
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass

    with open(final_output) as f:
        total = sum(1 for _ in f)
    print(f"  DONE  {total} total lines in {os.path.relpath(final_output, REPO_ROOT)}")
    return True


def main() -> None:
    if not os.path.exists(JAR):
        print(f"ERROR: SPARQL Anything jar not found at {JAR}", file=sys.stderr)
        print("Download from: https://github.com/SPARQL-Anything/sparql.anything/releases", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("Running SPARQL CONSTRUCTs across all layers")
    print("=" * 60)

    failures = 0
    for layer in LAYERS:
        ok = run_layer(layer)
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} layer(s) failed.", file=sys.stderr)
        sys.exit(1)
    print("\nAll layers complete.")


if __name__ == "__main__":
    main()
