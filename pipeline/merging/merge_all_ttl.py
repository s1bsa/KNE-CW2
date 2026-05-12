"""
Merges the three pipeline ABox TTL outputs into a single unified knowledge
graph file. Loads each input into one rdflib Graph (deduplication is
automatic) and re-binds canonical prefixes before serialising.

Inputs:
  - data/structured/eu_ai_act_metadata.ttl       (structured)
  - data/unstructured/html/eu_ai_act_html.ttl    (HTML)
  - data/unstructured/summaries/summary_enrichment.ttl (summaries)

Output: data/eu_ai_act_knowledge_graph.ttl
"""

import os

from rdflib import Graph, Namespace, OWL, RDFS, XSD

# Paths 
STRUCTURED_TTL  = "data/structured/eu_ai_act_metadata.ttl"
HTML_TTL        = "data/unstructured/html/eu_ai_act_html.ttl"
SUMMARIES_TTL   = "data/unstructured/summaries/summary_enrichment.ttl"
OUTPUT_TTL      = "data/eu_ai_act_knowledge_graph.ttl"

EX       = Namespace("https://example.org/eu-ai-act-compliance#")
AIRO     = Namespace("https://w3id.org/airo#")
AIACT    = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
DPV      = Namespace("https://w3id.org/dpv#")
DCT      = Namespace("http://purl.org/dc/terms/")


def load_if_exists(graph: Graph, path: str, label: str) -> int:
    if not os.path.exists(path):
        print(f"  SKIP  {label} ({path} not found)")
        return 0
    sub = Graph()
    sub.parse(path, format="turtle")
    for triple in sub:
        graph.add(triple)
    print(f"  OK    {label}: {len(sub)} triples")
    return len(sub)


def main() -> None:
    merged = Graph()
    merged.bind("",         EX)
    merged.bind("airo",     AIRO)
    merged.bind("eu-aiact", AIACT)
    merged.bind("dpv",      DPV)
    merged.bind("dct",      DCT)
    merged.bind("owl",      OWL)
    merged.bind("rdfs",     RDFS)
    merged.bind("xsd",      XSD)

    print("Merging pipeline TTL outputs...")
    structured = load_if_exists(merged, STRUCTURED_TTL,  "Structured (XML)")
    html       = load_if_exists(merged, HTML_TTL,        "HTML (LLM extraction)")
    summaries  = load_if_exists(merged, SUMMARIES_TTL,   "Summaries enrichment")

    os.makedirs(os.path.dirname(OUTPUT_TTL), exist_ok=True)
    merged.serialize(destination=OUTPUT_TTL, format="turtle")

    print()
    print(f"Total merged triples: {len(merged)} (deduplicated)")
    print(f"  Structured:    {structured}")
    print(f"  HTML:          {html}")
    print(f"  Summaries:     {summaries}")
    print(f"Output: {OUTPUT_TTL}")


if __name__ == "__main__":
    main()
