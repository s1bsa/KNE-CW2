"""
Converts the scraped article and annex summaries into enrichment TTL.

Attaches each summary as a :hasSummary literal on the canonical
:Article_N / :Annex_X URI created by the HTML pipeline. Also attaches
:hasSourceURL where available. Does NOT mint new entities — this is a
pure enrichment pass on URIs that already exist.

Input:  data/unstructured/summaries/ai_act_summaries.json
Output: data/unstructured/summaries/summary_enrichment.ttl
"""

import json
import os

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

INPUT_JSON = "data/unstructured/summaries/ai_act_summaries.json"
OUTPUT_TTL = "data/unstructured/summaries/summary_enrichment.ttl"

EX = Namespace("https://example.org/eu-ai-act-compliance#")


def main() -> None:
    with open(INPUT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    g = Graph()
    g.bind("", EX)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)

    article_count = 0
    for entry in data.get("articles", []):
        num = entry.get("article_number")
        summary = (entry.get("summary") or "").strip()
        if num is None or not summary:
            continue
        article_uri = EX[f"Article_{num}"]
        # Type assertion is idempotent — the HTML pipeline also asserts this.
        g.add((article_uri, RDF.type, EX.Article))
        g.add((article_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        source_url = entry.get("source_url")
        if source_url:
            g.add((article_uri, EX.hasSourceURL, Literal(source_url, datatype=XSD.string)))
        article_count += 1

    annex_count = 0
    for entry in data.get("annexes", []):
        roman = entry.get("annex_number")
        summary = (entry.get("summary") or "").strip()
        if not roman or not summary:
            continue
        annex_uri = EX[f"Annex_{roman}"]
        g.add((annex_uri, RDF.type, EX.Annex))
        g.add((annex_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        source_url = entry.get("source_url")
        if source_url:
            g.add((annex_uri, EX.hasSourceURL, Literal(source_url, datatype=XSD.string)))
        annex_count += 1

    os.makedirs(os.path.dirname(OUTPUT_TTL), exist_ok=True)
    g.serialize(destination=OUTPUT_TTL, format="turtle")

    print("Summary enrichment complete")
    print(f"  Articles enriched: {article_count}")
    print(f"  Annexes enriched:  {annex_count}")
    print(f"  Total triples:     {len(g)}")
    print(f"  Output: {OUTPUT_TTL}")


if __name__ == "__main__":
    main()
