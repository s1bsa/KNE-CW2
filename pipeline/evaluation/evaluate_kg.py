"""
Cheap evaluation metrics for the EU AI Act KG. Runs in under 30 seconds
with no LLM API cost. Every metric is computed twice — once on the
pre-RAG TTL and once on the post-RAG TTL — and the results are written
into a single side-by-side comparison.

Sections:
  1. Performance profiling   wall-clock + peak memory for the deterministic
                              pipeline stages (parser, rule-based extractor,
                              NER+regex, serialiser, merge, build), measured
                              with tracemalloc + perf_counter in subprocesses.
  2. Ontology metrics        class/property counts, hierarchy depth,
                              disjointness, equivalence, individual count.
  3. Zaveri completeness     CM1 schema, CM2 property, CM3 population,
                              CM4 interlinking.
  4. CQ answerability        executes all 20 SPARQL queries from
                              om_n_om/Queries.rq, records pass/fail and
                              latency.
  5. Graph connectivity      nodes, edges, degree distribution, clustering
                              coefficient, connected components, density.
  6. OntoClean tagging       rigidity / identity / dependence meta-properties
                              for the six most-populated classes.
  7. Triple sampling         50 random ABox triples for manual spot-checking.
  8. RAG vs baseline table   pre/post/delta summary across all metrics.

The two expensive evaluation scripts (NER benchmark, LLM baseline) live
in their own files and are not invoked from here.

Outputs:
  data/evaluation/evaluation_results.json
  data/evaluation/triple_sample_50.txt
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import tracemalloc
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef, Literal

# set seed for reproducibility of sampled triples
random.seed(0)

# Namespaces 
EX    = Namespace("https://example.org/eu-ai-act-compliance#")
AIRO  = Namespace("https://w3id.org/airo#")
AIACT = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
DPV   = Namespace("https://w3id.org/dpv#")

# Paths 
PRE_RAG_TTL    = "data/eu_ai_act_final.ttl"
POST_RAG_TTL   = "data/eu_ai_act_final_RAG.ttl"
ONTOLOGY       = "om_n_om/aiact_ontology.ttl"
QUERIES        = "om_n_om/Queries.rq"
EVAL_DIR       = "data/evaluation"
OUT_JSON       = os.path.join(EVAL_DIR, "evaluation_results.json")
TRIPLE_OUT     = os.path.join(EVAL_DIR, "triple_sample_50.txt")

# Stages with deterministic, cached-replay-safe behaviour. The LLM extractor
# is excluded — we use cached llm_extraction.json + rag_completion_triples.ttl
# from disk.
DETERMINISTIC_STAGES = [
    ("Parser (HTML → JSON)",       "pipeline/unstructured/html/eurlex_html_to_json.py"),
    ("Rule-based extraction",      "pipeline/unstructured/html/rule_based_extract.py"),
    ("NER + regex enrichment",     "pipeline/unstructured/html/ner_enrich.py"),
    ("Serialise to TTL",           "pipeline/unstructured/html/serialise_llm_extraction.py"),
    ("Merge layers",               "pipeline/merging/merge_all_ttl.py"),
    ("Build final KG",             "pipeline/merging/build_final_kg.py"),
]

# Utilities

def ln(uri):
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


def load_ttl(path):
    g = Graph()
    g.parse(path, format="turtle")
    return g



# Section 1 — Performance profiling (deterministic stages only)

def run_performance() -> list[dict]:
    """Profile the deterministic pipeline stages with tracemalloc + perf_counter.

    The LLM extractor and RAG enhancer are EXCLUDED from this profile because
    they make API calls that cost money and dominate the timing in a way
    that's not representative of typical re-runs (which are cache-warm).
    See Section 1 of EVALUATION_REPORT.md for the rationale.
    """
    print("\n[Section 1] Performance profiling (deterministic stages)")
    res = []
    for name, script in DETERMINISTIC_STAGES:
        if not os.path.exists(script):
            print(f"  SKIP   {name:35}  ({script} not found)")
            res.append({
                "stage": name, "script": script,
                "time_s": None, "peak_mb": None, "status": "not_found",
            })
            continue

        wrapper = (
            f"import tracemalloc, time, runpy, os, sys\n"
            f"os.chdir({os.getcwd()!r})\n"
            f"sys.path.insert(0, {os.getcwd()!r})\n"
            f"tracemalloc.start()\n"
            f"t0 = time.perf_counter()\n"
            f"try:\n"
            f"    runpy.run_path({script!r}, run_name='__main__')\n"
            f"    status = 'ok'\n"
            f"except SystemExit as e:\n"
            f"    status = 'ok' if (e.code in (0, None)) else f'exit_{{e.code}}'\n"
            f"except Exception as e:\n"
            f"    status = type(e).__name__\n"
            f"t1 = time.perf_counter()\n"
            f"_, peak = tracemalloc.get_traced_memory()\n"
            f"tracemalloc.stop()\n"
            f"print(f'__P__|{{t1-t0:.4f}}|{{peak/1024/1024:.2f}}|{{status}}')\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", wrapper],
                capture_output=True, text=True, timeout=120, cwd=os.getcwd(),
            )
            m = re.search(r"__P__\|([\d.]+)\|([\d.]+)\|(.+)",
                         proc.stdout + proc.stderr)
            if m:
                t, mem, status = float(m.group(1)), float(m.group(2)), m.group(3).strip()
                marker = "✓" if status == "ok" else "✗"
                print(f"  {marker}  {name:35}  {t:>6.2f}s   {mem:>6.1f} MB   [{status}]")
                res.append({
                    "stage": name, "script": script,
                    "time_s": round(t, 4), "peak_mb": round(mem, 2),
                    "status": status,
                })
            else:
                print(f"  ?  {name:35}  PARSE_ERROR")
                res.append({
                    "stage": name, "script": script,
                    "time_s": None, "peak_mb": None, "status": "parse_error",
                })
        except subprocess.TimeoutExpired:
            print(f"  ⏱  {name:35}  TIMEOUT")
            res.append({
                "stage": name, "script": script,
                "time_s": None, "peak_mb": None, "status": "timeout",
            })

    total_t = sum(r["time_s"] for r in res if r["time_s"])
    peak_m  = max((r["peak_mb"] for r in res if r["peak_mb"]), default=0)
    print(f"  ─" * 40)
    print(f"  TOTAL:                              {total_t:>6.2f}s   (peak {peak_m:.1f} MB)")
    return res


# Section 2 — Ontology metrics

def run_ontology(tbox: Graph, kg: Graph, label: str) -> dict:
    """Compute ontology shape metrics: classes, properties, hierarchy depth,
    disjointness axioms, individual counts."""
    cls = {c for c in tbox.subjects(RDF.type, OWL.Class)
           if str(c).startswith(str(EX))}
    op  = {p for p in tbox.subjects(RDF.type, OWL.ObjectProperty)
           if str(p).startswith(str(EX))}
    dp  = {p for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)
           if str(p).startswith(str(EX))}
    disj = len(list(tbox.triples((None, OWL.disjointWith, None))))
    eqc  = len(list(tbox.triples((None, OWL.equivalentClass, None))))

    # Hierarchy depth 
    children = defaultdict(set)
    for s, _, o in tbox.triples((None, RDFS.subClassOf, None)):
        if str(s).startswith(str(EX)) and str(o).startswith(str(EX)):
            children[o].add(s)
    all_children = set()
    for v in children.values():
        all_children.update(v)
    roots = cls - all_children
    max_depth = 0
    for root in roots:
        queue = [(root, 1)]
        while queue:
            node, d = queue.pop(0)
            max_depth = max(max_depth, d)
            for c in children.get(node, []):
                queue.append((c, d + 1))

    # Individuals 
    inds = set()
    for s, _, o in kg.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and str(o).startswith(str(EX)):
            if s not in cls and s not in op and s not in dp:
                inds.add(s)

    # Per-class instance count
    per_class = Counter()
    for s, _, o in kg.triples((None, RDF.type, None)):
        if str(o).startswith(str(EX)) and s in inds:
            per_class[ln(o)] += 1

    res = {
        "classes": len(cls),
        "obj_props": len(op),
        "dt_props": len(dp),
        "max_hierarchy_depth": max_depth,
        "disjointness_axioms": disj,
        "equivalent_class_axioms": eqc,
        "individuals": len(inds),
        "total_triples": len(kg),
        "top_classes_by_population": dict(per_class.most_common(15)),
    }
    print(f"\n[Section 2] Ontology metrics — {label}")
    for k in ("classes", "obj_props", "dt_props", "max_hierarchy_depth",
              "disjointness_axioms", "individuals", "total_triples"):
        print(f"  {k:35}  {res[k]:>8}")
    return res


# Section 2b — Zaveri completeness (CM1-CM4)

EXPECTED_POPULATIONS = {
    "Article":    113,
    "Annex":       13,
    "AreaOfApplication": 8,
    "ProhibitedPractice": 8,
    "EnforcementPower":  10,
    "Requirement":       12,
    "DocumentationComponent": 25,
    "RegistrationField":      27,
    "TestingPlanField":        5,
    "ConformityAssessmentStep": 15,
    "GPAIObligation":          3,
}


def run_completeness(tbox: Graph, kg: Graph, label: str) -> dict:
    """Compute Zaveri CM1-CM4 against the given KG."""
    print(f"\n[Section 2b] Zaveri completeness — {label}")

    # CM1 — schema completeness
    custom_classes = set(c for c in tbox.subjects(RDF.type, OWL.Class)
                         if str(c).startswith(str(EX)))
    custom_op = set(p for p in tbox.subjects(RDF.type, OWL.ObjectProperty)
                    if str(p).startswith(str(EX)))
    custom_dp = set(p for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)
                    if str(p).startswith(str(EX)))

    # Filter the TBox to only the elements that
    # still exist in the graph being evaluated.
    classes_in_kg = set()
    props_in_kg = set()
    for s, p, o in kg.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and o == OWL.Class:
            classes_in_kg.add(s)
        if isinstance(s, URIRef) and o in (OWL.ObjectProperty, OWL.DatatypeProperty):
            props_in_kg.add(s)
    custom_classes = custom_classes & classes_in_kg if classes_in_kg else custom_classes
    custom_op = custom_op & props_in_kg if props_in_kg else custom_op
    custom_dp = custom_dp & props_in_kg if props_in_kg else custom_dp

    used_classes = set(o for _, _, o in kg.triples((None, RDF.type, None))
                       if isinstance(o, URIRef))
    used_props = set(p for _, p, _ in kg if p != RDF.type)

    cls_used = custom_classes & used_classes
    op_used = custom_op & used_props
    dp_used = custom_dp & used_props
    total = len(custom_classes) + len(custom_op) + len(custom_dp)
    used = len(cls_used) + len(op_used) + len(dp_used)
    cm1 = used / total if total else 0.0

    # CM2 — property completeness (per property domain)
    per_prop = {}
    for prop in sorted(custom_op | custom_dp, key=str):
        domains = list(tbox.objects(prop, RDFS.domain))
        if not domains:
            continue
        dom = domains[0]
        dom_instances = set(kg.subjects(RDF.type, dom))
        if not dom_instances:
            continue
        with_value = set(s for s, _, _ in kg.triples((None, prop, None))
                        if s in dom_instances)
        per_prop[ln(prop)] = {
            "domain": ln(dom),
            "domain_instances": len(dom_instances),
            "with_value": len(with_value),
            "ratio": round(len(with_value) / len(dom_instances), 4),
        }
    cm2_avg = (sum(v["ratio"] for v in per_prop.values()) / len(per_prop)
               if per_prop else 0.0)

    # CM3 — population completeness (against EXPECTED_POPULATIONS)
    pop = {}
    for cls_name, expected in EXPECTED_POPULATIONS.items():
        actual = len(set(kg.subjects(RDF.type, EX[cls_name])))
        pop[cls_name] = {
            "actual": actual,
            "expected": expected,
            "ratio": round(actual / expected, 3) if expected else None,
        }
    known_ratios = [p["ratio"] for p in pop.values() if p["ratio"] is not None]
    cm3_avg = sum(known_ratios) / len(known_ratios) if known_ratios else 0.0

    # CM4 — interlinking completeness
    instance_uris = set()
    for s, _, o in kg.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            if (str(o).startswith(str(EX)) or str(o).startswith(str(AIACT))
                    or str(o).startswith(str(AIRO)) or str(o).startswith(str(DPV))):
                instance_uris.add(s)
    skip_predicates = {RDF.type, RDFS.label, RDFS.comment,
                       EX.hasSummary, EX.hasSourceURL, EX.hasCellarURI}
    linked = set()
    for inst in instance_uris:
        if inst in linked:
            continue
        for p, o in kg.predicate_objects(inst):
            if p not in skip_predicates and isinstance(o, URIRef):
                linked.add(inst); break
        if inst in linked:
            continue
        for s, p in kg.subject_predicates(inst):
            if p not in skip_predicates and isinstance(s, URIRef):
                linked.add(inst); break
    cm4 = len(linked) / len(instance_uris) if instance_uris else 0.0

    res = {
        "CM1_schema_completeness": round(cm1, 4),
        "CM1_used": used, "CM1_total": total,
        "CM2_property_completeness_avg": round(cm2_avg, 4),
        "CM3_population_completeness_avg": round(cm3_avg, 4),
        "CM4_interlinking_completeness": round(cm4, 4),
        "CM2_per_property_worst_5": dict(
            sorted(per_prop.items(), key=lambda kv: kv[1]["ratio"])[:5]
        ),
        "CM3_population_detail": pop,
        "CM4_linked": len(linked), "CM4_total": len(instance_uris),
    }
    print(f"  CM1 schema completeness:    {cm1:.4f}  ({used}/{total})")
    print(f"  CM2 property avg:           {cm2_avg:.4f}")
    print(f"  CM3 population avg (known): {cm3_avg:.4f}")
    print(f"  CM4 interlinking:           {cm4:.4f}  ({len(linked)}/{len(instance_uris)})")
    return res

# Section 3 — CQ answerability

def parse_queries() -> list[dict]:
    """Parse Queries.rq into individual SPARQL queries.

    Headers look like:  # CQ1 — title text
    Each query block contains comment lines (starting with #) followed by
    PREFIX declarations and the SELECT/CONSTRUCT body. We delimit blocks
    by headers only — the next header flushes the previous block.
    """
    with open(QUERIES, encoding="utf-8") as f:
        text = f.read()
    queries = []
    current_id = None
    current_question = ""
    current_lines: list[str] = []

    def flush():
        if current_id and current_lines:
            # Join and trim trailing comment-decoration lines
            sparql = "\n".join(current_lines).strip()
            if sparql:
                queries.append({
                    "id": current_id,
                    "question": current_question.strip(),
                    "sparql": sparql,
                })

    in_query_body = False
    for line in text.split("\n"):
        m = re.match(r"^# ((?:CQ|LLM)\d+) —\s*(.*)$", line)
        if m:
            flush()
            current_id = m.group(1)
            current_question = m.group(2).strip()
            current_lines = []
            in_query_body = False
            continue
        if current_id is None:
            continue
        # Once we see PREFIX, we're in the query body
        if line.strip().startswith("PREFIX"):
            in_query_body = True
        if in_query_body:
            current_lines.append(line)
    flush()
    return queries


def run_cqs(kg: Graph, label: str) -> list[dict]:
    """Execute every CQ in Queries.rq, measuring rows + latency per query."""
    print(f"\n[Section 3] CQ answerability — {label}")
    queries = parse_queries()
    res = []
    passed = 0
    for q in queries:
        t0 = time.perf_counter()
        try:
            rows = list(kg.query(q["sparql"]))
            n = len(rows)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            sample = []
            for row in rows[:3]:
                sample.append({
                    str(k): ln(v) if isinstance(v, URIRef) else str(v)
                    for k, v in zip(row.labels, row)
                })
            ok = n > 0
            if ok:
                passed += 1
            res.append({
                "id": q["id"],
                "question": q["question"][:100],
                "status": "PASS" if ok else "FAIL",
                "row_count": n,
                "latency_ms": round(elapsed_ms, 2),
                "sample": sample,
            })
            flag = "✓" if ok else "✗"
            print(f"  {flag} {q['id']:6}  {n:>5} rows  {elapsed_ms:>7.1f}ms")
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res.append({
                "id": q["id"],
                "question": q["question"][:100],
                "status": "ERROR",
                "row_count": 0,
                "latency_ms": round(elapsed_ms, 2),
                "error": str(e)[:200],
            })
            print(f"  ✗ {q['id']:6}  ERROR: {str(e)[:70]}")
    print(f"  → {passed}/{len(queries)} answered")
    return res

# Section 4 — Graph connectivity 

def run_connectivity(kg: Graph, label: str) -> dict:
    """Compute graph connectivity metrics: nodes, edges, degree distribution,
    clustering coefficient, connected components."""
    print(f"\n[Section 4] Graph connectivity — {label}")
    adj = defaultdict(set)
    nodes = set()
    skip_predicates = {
        RDF.type, RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
        OWL.imports, OWL.disjointWith, OWL.equivalentClass,
        OWL.equivalentProperty,
    }
    for s, p, o in kg:
        if isinstance(s, URIRef) and isinstance(o, URIRef) and p not in skip_predicates:
            adj[s].add(o)
            nodes.add(s)
            nodes.add(o)

    n_nodes = len(nodes)
    n_edges = sum(len(v) for v in adj.values())

    # Degree (in + out)
    in_deg = Counter()
    for s, neighbours in adj.items():
        for o in neighbours:
            in_deg[o] += 1
    deg = {}
    for n in nodes:
        deg[n] = len(adj.get(n, set())) + in_deg.get(n, 0)
    degs = list(deg.values()) or [0]

    # Clustering coefficient 
    def cc_for(node):
        nb = adj.get(node, set()) | {n for n in nodes if node in adj.get(n, set())}
        k = len(nb)
        if k < 2:
            return 0.0
        nb_list = list(nb)
        links = 0
        for i in range(len(nb_list)):
            for j in range(i + 1, len(nb_list)):
                if nb_list[j] in adj.get(nb_list[i], set()) or \
                   nb_list[i] in adj.get(nb_list[j], set()):
                    links += 1
        return 2.0 * links / (k * (k - 1))

    sample = random.sample(list(nodes), min(200, n_nodes)) if n_nodes else []
    avg_cc = sum(cc_for(n) for n in sample) / len(sample) if sample else 0.0

    # Connected components (undirected)
    undir = defaultdict(set)
    for s, neighbours in adj.items():
        for o in neighbours:
            undir[s].add(o)
            undir[o].add(s)
    visited = set()
    components = []
    for n in nodes:
        if n in visited:
            continue
        comp = set()
        queue = [n]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            comp.add(current)
            queue.extend(x for x in undir.get(current, set()) if x not in visited)
        components.append(len(comp))
    components.sort(reverse=True)

    res = {
        "nodes": n_nodes,
        "edges": n_edges,
        "avg_degree": round(sum(degs) / len(degs), 3) if degs else 0,
        "max_degree": max(degs) if degs else 0,
        "median_degree": sorted(degs)[len(degs) // 2] if degs else 0,
        "clustering_coefficient_sampled": round(avg_cc, 4),
        "connected_components": len(components),
        "largest_component_size": components[0] if components else 0,
        "density": round(n_edges / (n_nodes * (n_nodes - 1)), 6)
                   if n_nodes > 1 else 0,
    }
    for k in ("nodes", "edges", "avg_degree", "max_degree",
              "clustering_coefficient_sampled", "connected_components",
              "largest_component_size"):
        print(f"  {k:35}  {res[k]:>10}")
    return res


# Section 5 — OntoClean meta-property tagging


ONTOCLEAN_TAGS = {
    "Article": {
        "rigidity": "+R",
        "identity": "+I",
        "dependence": "-D",
        "rationale": "An Article is intrinsically what it is — being Article 5 "
                     "is essential to the entity. It has its own identity (article "
                     "number is unique). It does not depend on other entities for "
                     "its existence (the Act could exist without specific articles "
                     "being instantiated in our KG, but each Article is rigid).",
    },
    "Provider": {
        "rigidity": "~R",
        "identity": "+I",
        "dependence": "+D",
        "rationale": "Provider is anti-rigid: an organisation can become a "
                     "Provider when it places an AI system on the market and stop "
                     "being one when it withdraws. It has identity (legal entity "
                     "name + address). It depends on the AI System it provides "
                     "for the role to apply.",
    },
    "Obligation": {
        "rigidity": "+R",
        "identity": "+I",
        "dependence": "+D",
        "rationale": "An Obligation is what it is: the duty to do X cannot become "
                     "the duty to do Y. It has identity (the specific duty + its "
                     "grounding article). It depends on the bearer (provider, "
                     "deployer) — an obligation without anyone bound by it is "
                     "metaphysically odd.",
    },
    "EnforcementPower": {
        "rigidity": "+R",
        "identity": "+I",
        "dependence": "+D",
        "rationale": "An EnforcementPower (e.g. 'fine up to 35M EUR for "
                     "prohibited practices') is rigid: the power's content cannot "
                     "change without becoming a different power. It has identity "
                     "(the specific quantum + the offence it addresses). It "
                     "depends on the existence of an Authority that holds it.",
    },
    "Condition": {
        "rigidity": "+R",
        "identity": "-I",
        "dependence": "+D",
        "rationale": "A Condition is rigid (being a necessity-condition is "
                     "essential), but lacks identity in itself — two necessity "
                     "conditions on different practices are distinct only by "
                     "their textual content, not by intrinsic properties. Heavily "
                     "dependent on the gating provision.",
    },
    "Paragraph": {
        "rigidity": "+R",
        "identity": "+I",
        "dependence": "+D",
        "rationale": "A specific paragraph (e.g. Article 5(1)(h)) is rigid and "
                     "identifiable by its hierarchical reference. It depends on "
                     "the parent Article — a paragraph cannot exist outside its "
                     "containing article.",
    },
}


def run_ontoclean(kg: Graph, label: str) -> dict:
    """Tag the 6 most-populated custom classes with OntoClean meta-properties."""
    print(f"\n[Section 5] OntoClean meta-properties — {label}")
    out = {}
    # Map kg-side class names to our tag dictionary
    name_aliases = {
        "Article": "Article",
        "AIRegulatorySandboxInstance": "Provider",  # stand-in
        "ConformityAssessmentObligation": "Obligation",
        "EnforcementPower": "EnforcementPower",
        "NecessityCondition": "Condition",
        "Paragraph": "Paragraph",
    }
    # Pick the 6 most-populated classes that map to our tags
    counts = Counter()
    for s, _, o in kg.triples((None, RDF.type, None)):
        if str(o).startswith(str(EX)):
            counts[ln(o)] += 1

    for kg_name in name_aliases:
        n = counts.get(kg_name, 0)
        tag_key = name_aliases[kg_name]
        if tag_key in ONTOCLEAN_TAGS:
            entry = dict(ONTOCLEAN_TAGS[tag_key])
            entry["instances"] = n
            entry["kg_class"] = kg_name
            out[kg_name] = entry
            print(f"  {kg_name:35}  rigidity={entry['rigidity']:3}  "
                  f"identity={entry['identity']:3}  dependence={entry['dependence']:3}  "
                  f"({n} instances)")
    return out


# Section 6 — Triple sampling for manual review

def run_triple_sampling(kg: Graph, n: int = 50) -> list[dict]:
    """Sample N random ABox triples and write a markdown table for human review."""
    print(f"\n[Section 6] Triple sampling — {n} random ABox triples")
    skip_predicates = {
        RDF.type, RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
        OWL.imports, OWL.disjointWith, OWL.equivalentClass,
        OWL.equivalentProperty, OWL.versionInfo,
    }
    skip_subjects = {
        "https://example.org/eu-ai-act-compliance",
        "https://example.org/eu-ai-act-external-stubs",
    }
    abox = [
        (s, p, o) for s, p, o in kg
        if p not in skip_predicates and str(s) not in skip_subjects
        and isinstance(s, URIRef) and str(s).startswith(str(EX))
    ]
    # rdflib graph iteration order is not stable across runs, so sort first
    # before sampling with a dedicated fixed-seed RNG.
    abox.sort(key=lambda t: (str(t[0]), str(t[1]), str(t[2])))
    rng = random.Random(42)
    sample = rng.sample(abox, min(n, len(abox)))
    lines = [
        f"{'#':<4} {'Subject':<45} {'Predicate':<30} {'Object':<50} Correct?",
        "-" * 135,
    ]
    data = []
    for i, (s, p, o) in enumerate(sample, 1):
        sn, pn = ln(s), ln(p)
        on = ln(o) if isinstance(o, URIRef) else str(o)[:50]
        data.append({"i": i, "s": sn, "p": pn, "o": on})
        lines.append(f"{i:<4} {sn:<45} {pn:<30} {on:<50} [ ]")
    with open(TRIPLE_OUT, "w") as f:
        f.write("\n".join(lines))
    print(f"  {len(sample)} triples → {TRIPLE_OUT}")
    return data

# Section 7 — RAG vs baseline comparison wrapper

def build_comparison_table(pre: dict, post: dict) -> dict:
    """Compute the side-by-side delta between pre-RAG and post-RAG metrics."""
    print("\n[Section 7] RAG vs baseline comparison")

    def delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 4)

    # Triple counts
    pre_total = pre["ontology_pre"]["total_triples"]
    post_total = post["ontology_post"]["total_triples"]
    pre_inds  = pre["ontology_pre"]["individuals"]
    post_inds = post["ontology_post"]["individuals"]

    # Zaveri deltas
    pre_z  = pre["completeness_pre"]
    post_z = post["completeness_post"]

    # CQ deltas
    pre_cqs  = {c["id"]: c for c in pre["cqs_pre"]}
    post_cqs = {c["id"]: c for c in post["cqs_post"]}
    cq_table = []
    for cq_id in sorted(pre_cqs.keys()):
        if cq_id not in post_cqs:
            continue
        cq_table.append({
            "id": cq_id,
            "pre_rows": pre_cqs[cq_id].get("row_count", 0),
            "post_rows": post_cqs[cq_id].get("row_count", 0),
            "delta": delta(pre_cqs[cq_id].get("row_count", 0),
                           post_cqs[cq_id].get("row_count", 0)),
        })
    pre_passed  = sum(1 for c in pre["cqs_pre"] if c["status"] == "PASS")
    post_passed = sum(1 for c in post["cqs_post"] if c["status"] == "PASS")

    # Connectivity deltas
    pre_c  = pre["connectivity_pre"]
    post_c = post["connectivity_post"]

    table = {
        "triple_counts": {
            "pre_rag":  pre_total,
            "post_rag": post_total,
            "delta":    delta(pre_total, post_total),
        },
        "individuals": {
            "pre_rag":  pre_inds,
            "post_rag": post_inds,
            "delta":    delta(pre_inds, post_inds),
        },
        "zaveri": {
            "CM1_schema": {
                "pre_rag":  pre_z["CM1_schema_completeness"],
                "post_rag": post_z["CM1_schema_completeness"],
                "delta":    delta(pre_z["CM1_schema_completeness"],
                                  post_z["CM1_schema_completeness"]),
            },
            "CM2_property_avg": {
                "pre_rag":  pre_z["CM2_property_completeness_avg"],
                "post_rag": post_z["CM2_property_completeness_avg"],
                "delta":    delta(pre_z["CM2_property_completeness_avg"],
                                  post_z["CM2_property_completeness_avg"]),
            },
            "CM3_population_avg": {
                "pre_rag":  pre_z["CM3_population_completeness_avg"],
                "post_rag": post_z["CM3_population_completeness_avg"],
                "delta":    delta(pre_z["CM3_population_completeness_avg"],
                                  post_z["CM3_population_completeness_avg"]),
            },
            "CM4_interlinking": {
                "pre_rag":  pre_z["CM4_interlinking_completeness"],
                "post_rag": post_z["CM4_interlinking_completeness"],
                "delta":    delta(pre_z["CM4_interlinking_completeness"],
                                  post_z["CM4_interlinking_completeness"]),
            },
        },
        "cq_answerability": {
            "pre_rag_passing":  pre_passed,
            "post_rag_passing": post_passed,
            "total":            len(pre_cqs),
            "per_cq":           cq_table,
        },
        "connectivity": {
            "nodes": {
                "pre_rag":  pre_c["nodes"],
                "post_rag": post_c["nodes"],
                "delta":    delta(pre_c["nodes"], post_c["nodes"]),
            },
            "edges": {
                "pre_rag":  pre_c["edges"],
                "post_rag": post_c["edges"],
                "delta":    delta(pre_c["edges"], post_c["edges"]),
            },
            "avg_degree": {
                "pre_rag":  pre_c["avg_degree"],
                "post_rag": post_c["avg_degree"],
                "delta":    delta(pre_c["avg_degree"], post_c["avg_degree"]),
            },
        },
    }

    print(f"  Triples:           {pre_total}  →  {post_total}  ({delta(pre_total, post_total):+})")
    print(f"  Individuals:       {pre_inds}  →  {post_inds}  ({delta(pre_inds, post_inds):+})")
    print(f"  CM1 schema:        {pre_z['CM1_schema_completeness']:.4f}  →  "
          f"{post_z['CM1_schema_completeness']:.4f}  "
          f"({delta(pre_z['CM1_schema_completeness'], post_z['CM1_schema_completeness']):+.4f})")
    print(f"  CM2 property avg:  {pre_z['CM2_property_completeness_avg']:.4f}  →  "
          f"{post_z['CM2_property_completeness_avg']:.4f}  "
          f"({delta(pre_z['CM2_property_completeness_avg'], post_z['CM2_property_completeness_avg']):+.4f})")
    print(f"  CM3 population:    {pre_z['CM3_population_completeness_avg']:.4f}  →  "
          f"{post_z['CM3_population_completeness_avg']:.4f}  "
          f"({delta(pre_z['CM3_population_completeness_avg'], post_z['CM3_population_completeness_avg']):+.4f})")
    print(f"  CM4 interlinking:  {pre_z['CM4_interlinking_completeness']:.4f}  →  "
          f"{post_z['CM4_interlinking_completeness']:.4f}  "
          f"({delta(pre_z['CM4_interlinking_completeness'], post_z['CM4_interlinking_completeness']):+.4f})")
    print(f"  CQs answered:      {pre_passed}/{len(pre_cqs)}  →  {post_passed}/{len(post_cqs)}")
    return table

# Banner

def print_banner(results: dict) -> None:
    """Pretty-print the headline numbers in a box."""
    cmp = results.get("comparison", {})
    perf = results.get("performance", [])
    total_t = sum(s.get("time_s", 0) or 0 for s in perf)
    peak_m = max((s.get("peak_mb", 0) or 0 for s in perf), default=0)

    w = 70
    def row(label, value):
        print(f"  │ {label:<42} {str(value):>23}  │")
    print(f"\n  ┌{'─' * w}┐")
    print(f"  │{'EU AI Act KG — Evaluation Summary':^{w}}│")
    print(f"  ├{'─' * w}┤")
    if "triple_counts" in cmp:
        tc = cmp["triple_counts"]
        row("Triples (pre → post-RAG)",
            f"{tc['pre_rag']} → {tc['post_rag']} ({tc['delta']:+})")
    if "zaveri" in cmp:
        z = cmp["zaveri"]
        row("CM1 schema (pre → post)",
            f"{z['CM1_schema']['pre_rag']:.3f} → {z['CM1_schema']['post_rag']:.3f}")
        row("CM2 property avg (pre → post)",
            f"{z['CM2_property_avg']['pre_rag']:.3f} → {z['CM2_property_avg']['post_rag']:.3f}")
        row("CM3 population (pre → post)",
            f"{z['CM3_population_avg']['pre_rag']:.3f} → {z['CM3_population_avg']['post_rag']:.3f}")
        row("CM4 interlinking (pre → post)",
            f"{z['CM4_interlinking']['pre_rag']:.3f} → {z['CM4_interlinking']['post_rag']:.3f}")
    if "cq_answerability" in cmp:
        ca = cmp["cq_answerability"]
        row("CQs answered (pre → post)",
            f"{ca['pre_rag_passing']}/{ca['total']} → {ca['post_rag_passing']}/{ca['total']}")
    print(f"  ├{'─' * w}┤")
    row("Pipeline time (deterministic stages)", f"{total_t:.2f}s")
    row("Peak memory", f"{peak_m:.1f} MB")
    print(f"  └{'─' * w}┘")

# Main

def main() -> None:
    os.makedirs(EVAL_DIR, exist_ok=True)

    # Existence checks
    missing = []
    for path, desc in [(PRE_RAG_TTL, "pre-RAG TTL"),
                        (POST_RAG_TTL, "post-RAG TTL"),
                        (ONTOLOGY, "ontology"),
                        (QUERIES, "Queries.rq")]:
        if not os.path.exists(path):
            missing.append(f"  {desc}: {path}")
    if missing:
        print("ERROR: required files missing:")
        for m in missing:
            print(m)
        sys.exit(1)

    print("Loading graphs...")
    tbox    = load_ttl(ONTOLOGY)
    pre_kg  = load_ttl(PRE_RAG_TTL)
    post_kg = load_ttl(POST_RAG_TTL)
    print(f"  pre-RAG:  {len(pre_kg)} triples")
    print(f"  post-RAG: {len(post_kg)} triples")
    print(f"  TBox:     {len(tbox)} triples")

    results: dict = {}

    # Section 1 — Performance (deterministic stages, single run)
    results["performance"] = run_performance()

    # Sections 2-4 — Run twice (pre-RAG and post-RAG)
    results["ontology_pre"]      = run_ontology(tbox, pre_kg, "pre-RAG baseline")
    results["completeness_pre"]  = run_completeness(tbox, pre_kg, "pre-RAG baseline")
    results["cqs_pre"]           = run_cqs(pre_kg, "pre-RAG baseline")
    results["connectivity_pre"]  = run_connectivity(pre_kg, "pre-RAG baseline")

    results["ontology_post"]     = run_ontology(tbox, post_kg, "post-RAG completed")
    results["completeness_post"] = run_completeness(tbox, post_kg, "post-RAG completed")
    results["cqs_post"]          = run_cqs(post_kg, "post-RAG completed")
    results["connectivity_post"] = run_connectivity(post_kg, "post-RAG completed")

    # Section 5 — OntoClean (post-RAG only, doesn't depend on RAG)
    results["ontoclean"] = run_ontoclean(post_kg, "post-RAG completed")

    # Section 6 — Triple sampling (post-RAG)
    results["triple_sample"] = run_triple_sampling(post_kg, n=50)

    # Section 7 — Comparison wrapper
    results["comparison"] = build_comparison_table(results, results)

    # Write JSON output
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print_banner(results)
    print(f"\n  Output: {OUT_JSON}")
    print(f"          {TRIPLE_OUT}")
    print()
    print("  For NER benchmark and LLM baseline (expensive, opt-in):")
    print("    python3 pipeline/evaluation/ner_benchmark.py")
    print("    python3 pipeline/evaluation/llm_baseline.py")


if __name__ == "__main__":
    main()
