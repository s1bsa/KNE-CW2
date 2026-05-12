"""
Pre-RAG gap audit for the EU AI Act knowledge graph. Computes the four
Zaveri completeness metrics (CM1 schema, CM2 property, CM3 population,
CM4 interlinking) and produces a structured report identifying the
ontology and instance gaps that the RAG completion stage should target.

Deterministic and read-only — does not modify the KG. Output is consumed
by rag_enhance_kg.py to drive the completion calls.

Output: data/evaluation/gap_analysis.json
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

EX    = Namespace("https://example.org/eu-ai-act-compliance#")
AIRO  = Namespace("https://w3id.org/airo#")
AIACT = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
DPV   = Namespace("https://w3id.org/dpv#")

INPUT_KG    = "data/eu_ai_act_final.ttl"
ONTOLOGY    = "om_n_om/aiact_ontology.ttl"
OUTPUT_PATH = "data/evaluation/gap_analysis.json"

# Helpers

def local_name(uri):
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


# CM1 — Schema completeness

def cm1_schema(g: Graph, tbox: Graph) -> dict:
    """Proportion of declared classes + properties that are actually used."""
    declared_classes = set()
    for s in tbox.subjects(RDF.type, OWL.Class):
        if str(s).startswith(str(EX)):
            declared_classes.add(s)

    declared_obj_props = set()
    for s in tbox.subjects(RDF.type, OWL.ObjectProperty):
        if str(s).startswith(str(EX)):
            declared_obj_props.add(s)

    declared_dt_props = set()
    for s in tbox.subjects(RDF.type, OWL.DatatypeProperty):
        if str(s).startswith(str(EX)):
            declared_dt_props.add(s)

    used_classes = set()
    for s, p, o in g.triples((None, RDF.type, None)):
        if isinstance(o, URIRef):
            used_classes.add(o)

    used_props = set()
    for s, p, o in g:
        if p != RDF.type:
            used_props.add(p)

    classes_used = declared_classes & used_classes
    obj_used = declared_obj_props & used_props
    dt_used = declared_dt_props & used_props

    total = len(declared_classes) + len(declared_obj_props) + len(declared_dt_props)
    used = len(classes_used) + len(obj_used) + len(dt_used)
    cm1 = used / total if total else 0.0

    return {
        "ratio": round(cm1, 4),
        "used": used,
        "total": total,
        "unused_classes": sorted(local_name(c) for c in declared_classes - used_classes),
        "unused_obj_properties": sorted(local_name(p) for p in declared_obj_props - used_props),
        "unused_dt_properties": sorted(local_name(p) for p in declared_dt_props - used_props),
    }


# CM2 — Property completeness

def cm2_property(g: Graph, tbox: Graph) -> dict:
    """For each property with a domain, what fraction of domain instances
    actually have a value for that property?"""
    per_property = {}
    properties = set()
    for pt in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for p in tbox.subjects(RDF.type, pt):
            if str(p).startswith(str(EX)):
                properties.add(p)

    for prop in properties:
        domains = list(tbox.objects(prop, RDFS.domain))
        if not domains:
            continue
        domain = domains[0]
        # Resolve subclass closure for the domain
        domain_instances = set(g.subjects(RDF.type, domain))
        if not domain_instances:
            continue
        with_value = set(s for s, _, _ in g.triples((None, prop, None))
                        if s in domain_instances)
        ratio = len(with_value) / len(domain_instances)
        per_property[local_name(prop)] = {
            "domain": local_name(domain),
            "domain_instances": len(domain_instances),
            "with_value": len(with_value),
            "ratio": round(ratio, 4),
        }

    if per_property:
        avg = sum(d["ratio"] for d in per_property.values()) / len(per_property)
    else:
        avg = 0.0

    return {
        "average": round(avg, 4),
        "per_property": dict(sorted(per_property.items(), key=lambda kv: kv[1]["ratio"])),
    }

# CM3 — Population completeness

EXPECTED_POPULATIONS = {
    "Article":    113,   # known: AI Act has exactly 113 articles
    "Annex":       13,   # known: AI Act has exactly 13 annexes
    "Recital":    180,   # known: AI Act has 180 recitals
    "AreaOfApplication": 8,   # Annex III lists exactly 8 sectors
    "ProhibitedPractice": 8,  # Article 5(1) lists 8 practices
    "EnforcementPower":  10,  # ~10 distinct enforcement powers in Articles 99-101
    "Requirement":       12,  # Article 31 lists 12 requirements for notified bodies
    "DocumentationComponent": 25,  # Annex IV
    "RegistrationField":      27,  # Annex VIII Sections A-C
    "TestingPlanField":        5,  # Annex IX
    "ConformityAssessmentStep": 15,  # Annex VI + VII combined
}


def cm3_population(g: Graph, tbox: Graph) -> dict:
    """For each custom class, count actual instances and compare to expected
    population where known."""
    actuals = {}
    for cls in tbox.subjects(RDF.type, OWL.Class):
        if not str(cls).startswith(str(EX)):
            continue
        n = len(set(g.subjects(RDF.type, cls)))
        actuals[local_name(cls)] = n

    populations = {}
    for cls_name, actual in sorted(actuals.items()):
        expected = EXPECTED_POPULATIONS.get(cls_name)
        ratio = (actual / expected) if expected else None
        populations[cls_name] = {
            "actual": actual,
            "expected": expected,
            "ratio": round(ratio, 3) if ratio is not None else None,
        }

    # Average CM3 for classes with known expected counts
    known = [p["ratio"] for p in populations.values() if p["ratio"] is not None]
    avg = sum(known) / len(known) if known else 0.0

    return {
        "average_known": round(avg, 4),
        "per_class": populations,
    }

# CM4 — Interlinking completeness

def cm4_interlinking(g: Graph) -> dict:
    """Proportion of instances that participate in at least one
    object-property edge (in either direction)."""
    instance_uris = set()
    for s, _, o in g.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            if str(o).startswith(str(EX)) or str(o).startswith(str(AIACT)) or \
               str(o).startswith(str(AIRO)) or str(o).startswith(str(DPV)):
                instance_uris.add(s)

    if not instance_uris:
        return {"ratio": 0.0, "linked": 0, "total": 0}

    skip_predicates = {RDF.type, RDFS.label, RDFS.comment,
                       EX.hasSummary, EX.hasSourceURL, EX.hasCellarURI}

    linked = set()
    for inst in instance_uris:
        if inst in linked:
            continue
        # Outgoing
        for p, o in g.predicate_objects(inst):
            if p in skip_predicates:
                continue
            if isinstance(o, URIRef):
                linked.add(inst)
                break
        if inst in linked:
            continue
        # Incoming
        for s, p in g.subject_predicates(inst):
            if p in skip_predicates:
                continue
            if isinstance(s, URIRef):
                linked.add(inst)
                break

    return {
        "ratio": round(len(linked) / len(instance_uris), 4),
        "linked": len(linked),
        "total": len(instance_uris),
    }


# Documented gap list (5 ontology + 5 instance) — drives the RAG completion

ONTOLOGY_GAPS = [
    {
        "id": "O1",
        "kind": "class",
        "uri": "Recital",
        "metric": "CM1+CM3",
        "issue": (
            "The :Recital class is declared in the TBox but has zero instances. "
            "The EU AI Act has 180 recitals in its preamble; none are represented. "
            "Recitals provide the legal rationale for operative provisions and are "
            "frequently cited in case law and compliance guidance."
        ),
        "completion_strategy": (
            "Deterministic rule-based extraction from EUR-Lex HTML <div id='rct_*'> "
            "elements. Mints :Recital_N instances with :hasSummary text and "
            ":hasSourceURL. No RAG required for the structural extraction; RAG is "
            "used downstream (gap O2) to wire recitals to the obligations they "
            "justify."
        ),
    },
    {
        "id": "O2",
        "kind": "object_property",
        "uri": "hasRecitalReference",
        "metric": "CM1+CM4",
        "issue": (
            "The :hasRecitalReference property is declared but used 0 times. "
            "Operative provisions in the AI Act articles are typically grounded "
            "in one or more recitals (e.g. Article 5(1)(h) is grounded in "
            "Recitals 32-37), but the KG has no representation of this grounding."
        ),
        "completion_strategy": (
            "RAG. After O1 is resolved, query the KG for obligations and prohibited "
            "practices, retrieve the recital corpus as context, and ask the LLM to "
            "identify which recitals justify each provision. Output: triples of "
            "form (?obligation :hasRecitalReference :Recital_N)."
        ),
    },
    {
        "id": "O3",
        "kind": "object_property",
        "uri": "requiresControl",
        "metric": "CM1+CM2",
        "issue": (
            "The :requiresControl property (sub-property of airo:hasRiskControl) "
            "is declared but used 0 times. Article 9(2) explicitly requires the "
            "risk management system to comprise specific controls, and Article 14 "
            "requires human oversight controls — both are extracted as :RiskControl "
            "instances in the KG, but no obligation is linked to them."
        ),
        "completion_strategy": (
            "RAG. Query the KG for (obligation, risk-control) pairs that share an "
            "article reference, verbalise both, and ask the LLM 'does this "
            "obligation require this control?' with chain-of-thought reasoning. "
            "Emit (?obligation :requiresControl ?control) triples."
        ),
    },
    {
        "id": "O4",
        "kind": "datatype_property",
        "uri": "hasOJReference",
        "metric": "CM1+CM2",
        "issue": (
            "The :hasOJReference property is declared with domain :AIActRegulation "
            "but used 0 times. The Official Journal reference for the EU AI Act "
            "(OJ L, 2024/1689) is publicly known and is part of the metadata "
            "header in the EUR-Lex HTML, but no triple captures it."
        ),
        "completion_strategy": (
            "RAG with deterministic fallback. Retrieve the regulation metadata "
            "header from the structured pipeline output; ask the LLM to extract "
            "the OJ reference string. Single triple: (:EUAIAct2024 :hasOJReference "
            "'OJ L, 12.7.2024')."
        ),
    },
    {
        "id": "O5",
        "kind": "class",
        "uri": "GPAIObligation",
        "metric": "CM1+CM3",
        "issue": (
            "The :GPAIObligation parent class has 0 direct instances. Its two "
            "subclasses :GeneralGPAIObligation (10 instances) and "
            ":SystemicRiskGPAIObligation (1 instance) cover specific cases, but "
            "the parent class — meant for obligations that apply across both "
            "sub-categories (e.g. Article 56 codes-of-practice obligations) — "
            "is empty."
        ),
        "completion_strategy": (
            "RAG. Retrieve Article 56 (Codes of Practice) text, ask the LLM to "
            "identify obligations that apply to both general GPAI providers AND "
            "systemic-risk GPAI providers, and emit them typed as :GPAIObligation "
            "directly (not the subclasses)."
        ),
    },
]

INSTANCE_GAPS = [
    {
        "id": "I1",
        "kind": "property_completeness",
        "predicate": "hasFine",
        "subject_class": "EnforcementPower",
        "metric": "CM2",
        "issue": (
            "0 of 14 :EnforcementPower instances have a :hasFine value. "
            "Article 99 specifies three fine tiers (35 000 000 EUR, 15 000 000 "
            "EUR, 7 500 000 EUR) and the NER pass extracted them — but it "
            "attached them to :Article_99 itself, not to the specific "
            "enforcement-power instances they apply to. CM2 = 0%."
        ),
        "completion_strategy": (
            "RAG. For each :EnforcementPower with :hasArticleReference :Article_99, "
            "verbalise its summary, retrieve the Article 99 text as context, and "
            "ask the LLM to match the correct fine tier to the power based on "
            "what kind of non-compliance the power addresses. Emit "
            "(?power :hasFine ?amount) triples."
        ),
    },
    {
        "id": "I2",
        "kind": "property_completeness",
        "predicate": "hasDeadline",
        "subject_class": "Obligation (any subclass)",
        "metric": "CM2",
        "issue": (
            "Only 4 obligations have a :hasDeadline value, despite ~12 "
            ":ProviderIncidentReport instances and several :ConformityAssessment* "
            "obligations all having explicit deadlines in the article text "
            "(Article 73: 15 days / 10 days / 2 days; Article 43: 15 working "
            "days; Article 46: 12 months). CM2 < 2%."
        ),
        "completion_strategy": (
            "RAG. For each obligation that lacks :hasDeadline but whose summary "
            "contains time language ('within', 'no later than', 'by', "
            "'immediately'), retrieve the source article text and ask the LLM "
            "to extract the canonical xsd:duration value. Emit "
            "(?obligation :hasDeadline ?duration)."
        ),
    },
    {
        "id": "I3",
        "kind": "population_completeness",
        "predicate": "rdf:type",
        "subject_class": "TestingPlanField",
        "metric": "CM3",
        "issue": (
            "Only 1 :TestingPlanField instance exists. Annex IX of the AI Act "
            "lists 5 fields required for the real-world testing plan. The "
            "rule-based extractor fell back to a synthetic regex pass for Annex "
            "IX content_items and missed 4 of the 5. CM3 = 1/5 = 20%."
        ),
        "completion_strategy": (
            "RAG. Retrieve Annex IX text in full, verbalise the existing single "
            "TestingPlanField as a few-shot example, ask the LLM to enumerate "
            "the remaining 4 fields and emit them as new :TestingPlanField "
            "instances linked to :TestingPlan_Annex_IX via :hasRequiredComponent."
        ),
    },
    {
        "id": "I4",
        "kind": "property_completeness",
        "predicate": "hasReportingTarget",
        "subject_class": "ProviderIncidentReport",
        "metric": "CM2",
        "issue": (
            "Of 12 :ProviderIncidentReport instances, only 12 have "
            ":hasReportingTarget set (the serialiser default wires this for "
            "every instance). HOWEVER, all 12 are wired to "
            ":MarketSurveillanceAuthority by default — Article 73 actually "
            "specifies different recipients in different sub-paragraphs (the "
            "MSA of the Member State where the incident occurred; for serious "
            "infringements, the relevant data protection authority too). The "
            "default is too coarse."
        ),
        "completion_strategy": (
            "RAG. Retrieve the specific Article 73 sub-paragraph that grounds "
            "each instance, ask the LLM to refine the reporting target where "
            "the article specifies a more specific authority. Emit additional "
            "(?instance :hasReportingTarget ?specific_authority) triples."
        ),
    },
    {
        "id": "I5",
        "kind": "property_completeness",
        "predicate": "hasMaximumFineRatio",
        "subject_class": "EnforcementPower",
        "metric": "CM2",
        "issue": (
            "Only 3 of 14 :EnforcementPower instances have :hasMaximumFineRatio "
            "set (CM2 = 21%). Article 99 specifies turnover ratios for all "
            "three fine tiers (7%, 3%, 1%), but only the named-entity regex "
            "pass caught them. The other 11 enforcement powers — from Articles "
            "76, 80, 82, 83, 88, 101 — don't have ratios attached even when the "
            "source article specifies them."
        ),
        "completion_strategy": (
            "RAG. Same approach as I1, but for the ratio property instead of "
            "the absolute fine. For each :EnforcementPower without "
            ":hasMaximumFineRatio, verbalise its summary, retrieve the source "
            "article, ask the LLM to identify the applicable turnover-ratio "
            "ceiling. Emit (?power :hasMaximumFineRatio ?ratio)."
        ),
    },
]

# Main

def main() -> None:
    print(f"Loading KG from {INPUT_KG}")
    g = Graph()
    g.parse(INPUT_KG, format="turtle")
    print(f"  triples: {len(g)}")

    print(f"Loading TBox from {ONTOLOGY}")
    tbox = Graph()
    tbox.parse(ONTOLOGY, format="turtle")
    print(f"  triples: {len(tbox)}")

    print("\n=== Running Zaveri completeness metrics ===")
    cm1 = cm1_schema(g, tbox)
    cm2 = cm2_property(g, tbox)
    cm3 = cm3_population(g, tbox)
    cm4 = cm4_interlinking(g)

    print(f"  CM1 schema completeness:    {cm1['ratio']:.4f}  ({cm1['used']}/{cm1['total']})")
    print(f"  CM2 property avg:           {cm2['average']:.4f}")
    print(f"  CM3 population avg (known): {cm3['average_known']:.4f}")
    print(f"  CM4 interlinking:           {cm4['ratio']:.4f}  ({cm4['linked']}/{cm4['total']})")

    print(f"\n  CM1 unused classes ({len(cm1['unused_classes'])}):")
    for c in cm1['unused_classes']:
        print(f"    ✗ {c}")
    print(f"  CM1 unused obj props ({len(cm1['unused_obj_properties'])}):")
    for p in cm1['unused_obj_properties']:
        print(f"    ✗ {p}")
    print(f"  CM1 unused dt props ({len(cm1['unused_dt_properties'])}):")
    for p in cm1['unused_dt_properties']:
        print(f"    ✗ {p}")

    print(f"\n  CM2 worst 5 properties:")
    for name, info in list(cm2["per_property"].items())[:5]:
        print(f"    {info['ratio']*100:5.1f}%  {name:30}  ({info['with_value']}/{info['domain_instances']} {info['domain']})")

    print(f"\n  CM3 under-populated classes (ratio < 0.5):")
    for name, info in cm3["per_class"].items():
        if info["ratio"] is not None and info["ratio"] < 0.5:
            exp = info["expected"]
            print(f"    {info['actual']:>3}/{exp:<3}  ({info['ratio']*100:5.1f}%)  {name}")

    output = {
        "input_kg":  INPUT_KG,
        "ontology":  ONTOLOGY,
        "metrics": {
            "CM1_schema_completeness":      cm1,
            "CM2_property_completeness":    cm2,
            "CM3_population_completeness":  cm3,
            "CM4_interlinking_completeness": cm4,
        },
        "documented_gaps": {
            "ontology_gaps": ONTOLOGY_GAPS,
            "instance_gaps": INSTANCE_GAPS,
        },
    }

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
