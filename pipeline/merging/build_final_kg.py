"""
Builds the two final knowledge graph TTLs in a single run.

  1. data/eu_ai_act_final.ttl
       Pre-RAG baseline: TBox + merged ABox only. The honest before-state
       used as the comparison anchor for the RAG completion analysis.

  2. data/eu_ai_act_final_RAG.ttl
       Post-RAG completed KG: TBox + ABox + RAG additive triples
       (rag_completion_triples.ttl) − RAG schema deletions
       (rag_schema_deletions.json). The deliverable used for post-completion
       CQ evaluation.

Both TTLs go through the same literal-typing sanitisation passes
(hasCellarURI / hasSourceURL → xsd:string, hasDeadline → xsd:duration)
so the before/after comparison is apples-to-apples. If the RAG inputs
don't exist yet, the post-RAG TTL is written as an identical copy of
the pre-RAG TTL.
"""

import json
import os

from rdflib import Graph, Literal, Namespace, OWL, RDFS, URIRef, XSD

EX = Namespace("https://example.org/eu-ai-act-compliance#")

ONTOLOGY_TTL   = "om_n_om/aiact_ontology.ttl"
KG_TTL         = "data/eu_ai_act_knowledge_graph.ttl"
RAG_TTL        = "data/rag_completion_triples.ttl"
RAG_DEL_JSON   = "data/rag_schema_deletions.json"
OUTPUT_TTL     = "data/eu_ai_act_final.ttl"
OUTPUT_TTL_RAG = "data/eu_ai_act_final_RAG.ttl"


def sanitise(g: Graph) -> dict:
    """Apply literal-typing fix passes. Returns counts of fixes applied."""
    counts = {"cellar": 0, "source_url": 0, "duration": 0}

    # hasCellarURI: bare IRI → xsd:string literal
    for s, p, o in list(g.triples((None, EX.hasCellarURI, None))):
        if isinstance(o, URIRef):
            g.remove((s, p, o))
            g.add((s, p, Literal(str(o), datatype=XSD.string)))
            counts["cellar"] += 1

    # hasSourceURL: bare IRI → xsd:string literal
    for s, p, o in list(g.triples((None, EX.hasSourceURL, None))):
        if isinstance(o, URIRef):
            g.remove((s, p, o))
            g.add((s, p, Literal(str(o), datatype=XSD.string)))
            counts["source_url"] += 1

    # hasDeadline: plain string → xsd:duration
    for s, p, o in list(g.triples((None, EX.hasDeadline, None))):
        if isinstance(o, Literal) and o.datatype != XSD.duration:
            val = str(o).strip()
            if val.startswith("P"):
                g.remove((s, p, o))
                g.add((s, p, Literal(val, datatype=XSD.duration)))
                counts["duration"] += 1

    return counts


def apply_schema_deletions(g: Graph, manifest_path: str) -> int:
    """Load the deletion manifest and strip listed URIs from the graph.

    For each URI in the manifest, removes every triple where that URI
    appears as either subject OR object. This deletes both the schema
    declarations (e.g. `:Recital a owl:Class`) and any incoming references
    (e.g. a rdfs:subClassOf axiom pointing at :Recital).

    Returns the number of triples removed. If the manifest file does not
    exist, returns 0 without error.
    """
    if not os.path.exists(manifest_path):
        return 0

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    deletions = manifest.get("deletions", [])
    if not deletions:
        return 0

    removed = 0
    by_kind = {"class": 0, "object_property": 0, "datatype_property": 0}
    for entry in deletions:
        uri = URIRef(entry["uri"])
        kind = entry.get("kind", "unknown")
        # Remove as subject
        for t in list(g.triples((uri, None, None))):
            g.remove(t)
            removed += 1
            if kind in by_kind:
                by_kind[kind] += 1
        # Remove as object
        for t in list(g.triples((None, None, uri))):
            g.remove(t)
            removed += 1

    print(f"  Schema deletions applied: {removed} triples removed")
    print(f"    classes:          {by_kind['class']}")
    print(f"    object props:     {by_kind['object_property']}")
    print(f"    datatype props:   {by_kind['datatype_property']}")
    return removed


def bind_prefixes(g: Graph) -> None:
    g.bind("",         EX)
    g.bind("airo",     Namespace("https://w3id.org/airo#"))
    g.bind("eu-aiact", Namespace("https://w3id.org/dpv/legal/eu/aiact#"))
    g.bind("dpv",      Namespace("https://w3id.org/dpv#"))
    g.bind("dct",      Namespace("http://purl.org/dc/terms/"))
    g.bind("owl",      OWL)
    g.bind("rdfs",     RDFS)
    g.bind("xsd",      XSD)


def load_base_graph() -> tuple[Graph, int, int]:
    """Load TBox + ABox into a single graph. Returns (graph, tbox_count, abox_count)."""
    merged = Graph()

    ontology = Graph()
    ontology.parse(ONTOLOGY_TTL, format="turtle")
    for triple in ontology:
        merged.add(triple)
    tbox_count = len(ontology)
    print(f"  TBox (ontology):  {tbox_count} triples")

    abox_count = 0
    if os.path.exists(KG_TTL):
        abox = Graph()
        abox.parse(KG_TTL, format="turtle")
        for triple in abox:
            merged.add(triple)
        abox_count = len(abox)
        print(f"  ABox (instances): {abox_count} triples")
    else:
        print(f"  ABox: SKIPPED (not found at {KG_TTL})")

    return merged, tbox_count, abox_count


def main() -> None:
    print("=" * 70)
    print("build_final_kg.py — two-output build with schema cleanup")
    print("=" * 70)

    # Build the pre-RAG graph (TBox + ABox, NO RAG additions or deletions)
    print("\n[1/2] Building pre-RAG baseline → eu_ai_act_final.ttl")
    pre_rag, tbox_count, abox_count = load_base_graph()
    sanitise_counts = sanitise(pre_rag)
    for k, v in sanitise_counts.items():
        if v:
            print(f"  sanitise {k}: {v} fixes")
    bind_prefixes(pre_rag)

    os.makedirs(os.path.dirname(OUTPUT_TTL), exist_ok=True)
    pre_rag.serialize(destination=OUTPUT_TTL, format="turtle")
    print(f"\n  Pre-RAG KG written: {OUTPUT_TTL}")
    print(f"    TBox:           {tbox_count} triples")
    print(f"    ABox:           {abox_count} triples")
    print(f"    Merged total:   {len(pre_rag)} triples (deduplicated)")

    # Build the post-RAG graph (TBox + ABox + additive RAG − deletions)

    print("\n[2/2] Building post-RAG completed KG → eu_ai_act_final_RAG.ttl")
    post_rag, _, _ = load_base_graph()

    # Additive completion
    rag_count = 0
    if os.path.exists(RAG_TTL):
        rag = Graph()
        rag.parse(RAG_TTL, format="turtle")
        for triple in rag:
            post_rag.add(triple)
        rag_count = len(rag)
        print(f"  RAG completion (additive): {rag_count} triples")
    else:
        print(f"  RAG completion (additive): SKIPPED ({RAG_TTL} not found)")
        print(f"  → Run pipeline/evaluation/rag_enhance_kg.py to produce RAG triples.")

    # Subtractive completion (schema cleanup)
    deletions_count = 0
    if os.path.exists(RAG_DEL_JSON):
        deletions_count = apply_schema_deletions(post_rag, RAG_DEL_JSON)
    else:
        print(f"  Schema deletions: SKIPPED ({RAG_DEL_JSON} not found)")

    post_sanitise = sanitise(post_rag)
    for k, v in post_sanitise.items():
        if v:
            print(f"  sanitise {k}: {v} fixes")
    bind_prefixes(post_rag)

    post_rag.serialize(destination=OUTPUT_TTL_RAG, format="turtle")
    print(f"\n  Post-RAG KG written: {OUTPUT_TTL_RAG}")
    print(f"    TBox:                     {tbox_count} triples")
    print(f"    ABox:                     {abox_count} triples")
    print(f"    RAG additive completion:  +{rag_count} triples")
    print(f"    RAG schema deletions:     -{deletions_count} triples")
    print(f"    Merged total:             {len(post_rag)} triples (deduplicated)")

    # Delta summary
    delta = len(post_rag) - len(pre_rag)
    sign = "+" if delta >= 0 else ""
    print(f"\n=== Build complete ===")
    print(f"  Pre-RAG:  {OUTPUT_TTL}         ({len(pre_rag)} triples)")
    print(f"  Post-RAG: {OUTPUT_TTL_RAG}     ({len(post_rag)} triples)")
    print(f"  Delta:    {sign}{delta} triples net (additive − subtractive)")


if __name__ == "__main__":
    main()