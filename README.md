# EU AI Act Compliance Knowledge Graph (KNE-CW2)

> Automated construction of an OWL 2 knowledge graph covering Regulation (EU) 2024/1689 — the EU AI Act — grounded in external ontologies (AIRO, DPV, DPV-AIAct) and evaluated against 20 competency questions.

This repository contains the full data pipeline, ontology, SPARQL queries, and evaluation scripts for building a semantically rich knowledge graph of the EU AI Act from three complementary sources: EUR-Lex CELLAR XML metadata, the full HTML legal text, and plain-language summaries from artificialintelligenceact.eu.

---

## Table of contents

1. [What this project does](#1-what-this-project-does)
2. [Reproduction guide](#7-reproduction-guide)
3. [RAG-based knowledge graph completion](#8-rag-based-knowledge-graph-completion)
4. [Evaluation](#9-evaluation)

---

## 1. What this project does

The EU AI Act is a long, densely cross-referenced legal document. Regulators, providers, deployers and researchers all need structured access to its obligations, powers, conditions, prohibited practices, deadlines and definitions. A knowledge graph exposes that structure as queryable RDF.

This project automates the end-to-end construction of such a knowledge graph. It starts from raw sources (XML metadata, HTML text, scraped summaries) and produces a single Turtle file (`data/eu_ai_act_final.ttl`) that combines:

- A **TBox** — the ontology: classes, object properties, datatype properties, and hierarchies describing the domain
- An **ABox** — the instances: specific obligations, powers, conditions, prohibited practices, articles, deadlines, cited legislation, etc., all typed against the TBox

The KG is evaluated against 20 competency questions (CQs) — 10 designed by the team and 10 derived from an LLM-assisted elicitation exercise — that exercise the full range of domain concepts.

---

## 2. Reproduction guide

### 2.1 Prerequisites

**Python 3.11+** with a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Java** (any recent version) — needed for SPARQL Anything to run the structured layer CONSTRUCT.

**OpenAI API key** — set in a `.env` file at the repo root (not committed):

```bash
echo 'OPENAI_API_KEY=sk-proj-...your-key-here...' > .env
```

Or export it in your shell session:

```bash
export OPENAI_API_KEY=sk-proj-...your-key-here...
```

**SPARQL Anything jar** — should already be at `tools/sparql-anything-v1.1.0.jar`. If missing, download from https://github.com/SPARQL-Anything/sparql.anything/releases.

#### Spacy requirements
Install the model required by spaCy (after installing all requirements - including spaCy):
```bash
python3 -m spacy download en_core_web_sm
```

### 2.2 Input data

These files should already be in the repo:

- `data/structured/eu_ai_act_32024R1689.xml` — EUR-Lex CELLAR XML metadata
- `data/unstructured/html/eu_ai_act_content.html` — the saved EUR-Lex HTML text

The summaries are scraped fresh on every run from artificialintelligenceact.eu.

### 2.3 Full reproduction from scratch
**One command, end-to-end, from a clean checkout:**

```bash
# 1. Set up the environment (one-off)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m spacy download en_core_web_sm
echo 'OPENAI_API_KEY=sk-proj-...your-key-here...' > .env

# 2. Run everything: ontology build + baseline extraction + RAG completion + evaluation
python3 -m running_pipeline.whole_pipeline_with_ontology --phase3-and-4
```

That single command rebuilds the ontology, runs all 6 baseline pipeline stages, runs the Phase 3 RAG completion, and runs the Phase 4 cheap evaluation metrics. Total wall-clock: **~5-6 minutes**, total OpenAI cost: **~$0.20-0.25**.

> **Note on the entry point**: `whole_pipeline_with_ontology.py` is the recommended marker entry point — it rebuilds `om_n_om/aiact_ontology.ttl` from `om_n_om/build_ontology.py` before anything else, guaranteeing the TBox in `data/eu_ai_act_final*.ttl` matches the source. `whole_pipeline.py` is the same orchestrator without the ontology rebuild step (used during development to iterate on the ABox without touching the TBox). Both accept the same flags.

#### What gets produced

| File | Description | Approx size |
|---|---|---|
| `om_n_om/aiact_ontology.ttl` | TBox (rebuilt from `build_ontology.py`) | 545 triples |
| `data/eu_ai_act_final.ttl` | **Pre-RAG** baseline KG (TBox + ABox) | ~9189 triples |
| `data/eu_ai_act_final_RAG.ttl` | **Post-RAG** completed KG (TBox + ABox + completion) | ~9519 triples |
| `data/evaluation/evaluation_results.json` | Side-by-side metrics for both KGs | — |

#### CLI flags

The orchestrator (`whole_pipeline.py` / `whole_pipeline_with_ontology.py`) is driven by argparse flags, not environment variables:

| Flag | What it does | Time added | Cost added |
|---|---|---|---|
| (none) | Ontology + baseline extraction + merge + pre-RAG build | ~2-3 min | ~$0.05-0.10 (LLM extractor) |
| `--phase3-and-4` | + gap analysis + RAG completion + post-RAG build + cheap evaluation metrics | +2-3 min | +~$0.15 (RAG calls) |
| `--phase3-and-4-only` | Skip ontology + baseline; run only Phase 3 + Phase 4 | — | +~$0.15 |
| `--api-key KEY` | Override `OPENAI_API_KEY` for this run | — | — |

Phase 3 and Phase 4 are bundled into a single flag — they're always run together (or not at all). Running RAG completion without the evaluation that measures its impact, or running the evaluation without the post-RAG TTL it's supposed to compare, are both incoherent options, so the orchestrator no longer exposes them separately.

#### Common invocations

```bash
# Recommended for marker reproduction — full end-to-end run
python3 -m running_pipeline.whole_pipeline_with_ontology --phase3-and-4

# Baseline only (no RAG, no eval) — fastest sanity check
python3 -m running_pipeline.whole_pipeline_with_ontology

# Re-run RAG + evaluation only, skipping the expensive extraction stages
# (useful when iterating on RAG prompts or evaluation scripts; requires
#  a previous baseline run to have produced data/eu_ai_act_final.ttl)
python3 -m running_pipeline.whole_pipeline_with_ontology --phase3-and-4-only

# Pass the API key inline instead of using .env
python3 -m running_pipeline.whole_pipeline_with_ontology --phase3-and-4 --api-key sk-proj-...
```

#### Optional clean slate

The pipeline is idempotent — re-runs overwrite previous outputs — so deletion is not required. If you want a guaranteed-clean rebuild:

```bash
rm -f data/structured/eu_ai_act_metadata.json data/structured/eu_ai_act_metadata.ttl
rm -f data/unstructured/html/rule_extraction.json data/unstructured/html/llm_extraction.json
rm -f data/unstructured/html/ner_enrichment.json data/unstructured/html/eu_ai_act_html.ttl
rm -f data/unstructured/summaries/ai_act_summaries.json data/unstructured/summaries/summary_enrichment.ttl
rm -f data/eu_ai_act_knowledge_graph.ttl
rm -f data/rag_completion_triples.ttl data/rag_schema_deletions.json
rm -f data/eu_ai_act_final.ttl data/eu_ai_act_final_RAG.ttl
```

#### After the run — the two opt-in evaluation scripts

The orchestrator deliberately does **not** run `ner_benchmark.py` or `llm_baseline.py` because they have specific prerequisites (gold-standard file, additional API budget). To reproduce the full evaluation report numbers, run them manually after the orchestrator finishes:

```bash
# NER benchmark (~15s, free, needs spaCy en_core_web_sm)
python3 pipeline/evaluation/ner_benchmark.py

# LLM baseline (~30s, ~$0.01, needs OPENAI_API_KEY)
python3 pipeline/evaluation/llm_baseline.py
```

Both write to `data/evaluation/` alongside `evaluation_results.json`. See Section 4 for what they measure.

### 2.4 Running stages individually

If you want to iterate on a single step without re-running the whole thing:

```bash
# Just re-extract metadata from XML
python3 pipeline/structured/extract_xml_metadata.py

# Just re-parse the HTML (no LLM call)
python3 pipeline/unstructured/html/eurlex_html_to_json.py

# Just re-run the rule-based extractor (Layer 1, no LLM)
python3 pipeline/unstructured/html/rule_based_extract.py

# Just re-run the LLM extractor (Layer 2, expensive, ~$0.05-0.10)
python3 pipeline/unstructured/html/llm_extract.py

# Just re-run the spaCy + regex enrichment (Layer 3, no LLM)
python3 pipeline/unstructured/html/ner_enrich.py

# Just re-serialise all three layers to TTL (cheap, no LLM)
python3 pipeline/unstructured/html/serialise_llm_extraction.py

# Just re-scrape summaries
python3 pipeline/unstructured/summaries/scrape_ai_act_summaries.py

# Just re-run the structured SPARQL CONSTRUCT
python3 pipeline/sparql/run_all_constructs.py

# Just re-merge all the TTL layers
python3 pipeline/merging/merge_all_ttl.py

# Just rebuild both final KGs (pre-RAG + post-RAG if completion triples exist)
python3 pipeline/merging/build_final_kg.py

# Just re-run the gap analysis (Phase 3, free)
python3 pipeline/evaluation/gap_analysis.py

# Just re-run the RAG completion (Phase 3, ~$0.15)
python3 pipeline/evaluation/rag_enhance_kg.py

# Just run the cheap evaluation (Phase 4, free, <30s)
python3 pipeline/evaluation/evaluate_kg.py

# Just run the NER benchmark (Phase 4, free, ~15s)
python3 pipeline/evaluation/ner_benchmark.py

# Just run the LLM baseline comparison (Phase 4, ~$0.01, ~30s)
python3 pipeline/evaluation/llm_baseline.py
```

### 2.5 Running just the evaluation on existing TTLs

If both `data/eu_ai_act_final.ttl` and `data/eu_ai_act_final_RAG.ttl` already exist:

```bash
# Cheap metrics only — runs on both TTLs, produces side-by-side comparison
python3 pipeline/evaluation/evaluate_kg.py

# Add the NER benchmark (free, uses spaCy)
python3 pipeline/evaluation/ner_benchmark.py

# Add the LLM baseline comparison (costs ~$0.01)
python3 pipeline/evaluation/llm_baseline.py
```

All three scripts write to `data/evaluation/` and can be run independently.

### 2.6 Rebuilding the ontology from the builder

```bash
python3 om_n_om/build_ontology.py
python3 om_n_om/build_graph.py   # optional — regenerates aiact_ontology.png
```

This overwrites `om_n_om/aiact_ontology.ttl`.

---

## 3. RAG-based knowledge graph completion

RAG-based completion (**R**etrieval-**A**ugmented **G**eneration applied to KG completion) is the process of identifying under-populated ontology elements in the ABox, then asking an LLM to fill those gaps using relevant passages from the source text as retrieval context. The coursework specification requires identifying at least 5 ontology-level gaps and 5 instance-level gaps and using RAG to resolve them.

This project implements a **gap-driven, two-direction** completion approach:

### 3.1 Gap identification

`pipeline/evaluation/gap_analysis.py` computes the four Zaveri et al. (2015) completeness metrics (CM1 schema, CM2 property, CM3 population, CM4 interlinking) on the pre-RAG KG and identifies concrete gaps based on the scores:

- **Ontology-level gaps** — classes declared in the TBox that have zero or near-zero instances in the ABox, or object/datatype properties that are never applied. These indicate schema elements that need either population (if the class represents something real in the Act) or removal (if the class was a modelling mistake).
- **Instance-level gaps** — properties that are severely under-applied on their domain classes (e.g. `:hasFine` populated on 0/14 `:EnforcementPower` instances). These indicate that the extraction layer missed specific values that the text does contain.

The gap analysis script writes `data/evaluation/gap_analysis.json` listing 5 documented ontology gaps (O1–O5) and 5 documented instance gaps (I1–I5), each with a brief justification drawn from the Zaveri metrics.

### 3.2 RAG completion

`pipeline/evaluation/rag_enhance_kg.py` v5.2.0 addresses each gap with a dedicated RAG call. The architecture for each gap is:

1. **Retrieve** — SPARQL-query the pre-RAG KG to fetch any existing instances of the relevant class, plus the article or annex text where the relevant content is documented. For example, the O1 gap (DocumentationComponent under-population) retrieves the full text of Annex IV.
2. **Verbalise** — convert the retrieved context into a natural-language prompt section.
3. **Prompt** — ask `gpt-4.1-mini` for a constrained JSON output listing new instances / triples to add. Temperature 0.0 for determinism. Max output tokens sized per gap (O1/O2 need large outputs; I1/I2 need small ones).
4. **Validate** — the script validates the LLM output against the TBox: types must be declared classes, predicates must exist, domains and ranges must match.
5. **Emit** — valid triples are written to `data/rag_completion_triples.ttl` (~384 triples total across all gaps).

### 3.3 Two-direction completion

In addition to the **additive** completion described above, the script also performs **subtractive cleanup**. The gap analysis identifies 8 dead schema elements — classes and properties that ended up unused after extraction completed, either because the concept was redundant with an external ontology term or because the extraction target turned out to be wrong. These are:

**Classes**: `:Recital` (we never populated recitals), `:CEMarkingComponent`, `:EntryIntoForceProvision`, `:SystemicRiskGPAIObligation` (superseded by the parent `:GPAIObligation`)

**Object properties**: `:hasRecitalReference`, `:hasReference`, `:isRegulatedBy`

**Datatype property**: `:hasComplianceDeadline`

The RAG script emits a deletion manifest `data/rag_schema_deletions.json` that `build_final_kg.py` applies **only to the post-RAG TTL**. The pre-RAG TTL keeps the dead elements so the comparison shows both the schema-cleanup benefit and the additive-completion benefit.

### 3.4 Measured impact

Running the full completion produces the following changes, measured by re-running `gap_analysis.py` on both the pre-RAG and post-RAG TTLs:

| Metric | Pre-RAG | Post-RAG | Delta |
|---|---|---|---|
| Total triples | 9189 | 9519 | **+330** |
| Individuals (ABox) | 1571 | 1623 | +52 |
| **CM1 schema completeness** | **0.800** (68/85) | **0.922** (71/77) | **+0.122** |
| **CM2 property average** | **0.660** | **0.825** | **+0.165** |
| **CM3 population average** | **0.637** | **1.025** | **+0.388** |
| **CM4 interlinking** | 0.996 | 0.996 | ~0 |
| **CQs answered** | 20/20 | 20/20 | 0 regressions |

The CM1 denominator drops from 85 to 77 because of the 8-element cleanup; the numerator rises because RAG populated previously-unused properties. CM3 exceeds 1.0 because a handful of classes ended up with more instances than our conservative expected-population estimates.

The most visible single effect is on **LLM7** ("which enforcement powers can impose fines ≥ 3% of turnover"): its result count goes from 4 rows pre-RAG to 14 rows post-RAG because the I5 gap (under-applied `:hasMaximumFineRatio`) was filled with 10 new percentage values extracted from Article 99. Every other CQ either stays the same or improves by 1-2 rows.

### 3.5 Prompts and logs

The exact prompts used for each of the 10 gaps are documented in `docs/COMPLETION_PROMPTS.md` (one section per gap, with the full system + user prompts). The call log — including which gap ran, how many triples each call emitted, and any validation failures — is written to `data/evaluation/rag_completion_log.json`.

---

## 4. Evaluation

The evaluation answers the coursework specification requirement to measure *"performance (time, memory) as well as quality (competency question answerability, comparison against LLM baseline)"* using quantitative metrics grounded in the course materials. The methodology follows the five-step framework from **5CCSAKNEW07 slide 34** ("Benchmarking and evaluating NLP-built KGs"): define goals → curate gold standard → compare → apply metrics → task-based evaluation.

The evaluation is split across **three scripts** with different cost profiles:

### 4.1 `evaluate_kg.py` — cheap metrics on both TTLs (<30 s, free)

Runs every metric twice — once on the pre-RAG baseline and once on the post-RAG completed KG — and produces a side-by-side comparison table. No LLM calls. Writes `data/evaluation/evaluation_results.json`.

Sections covered:

1. **Performance profiling** — per-stage wall-clock time and peak memory measured with `tracemalloc` + `time.perf_counter()` in isolated subprocesses. Only the **deterministic** stages are profiled (parser, rule extractor, NER+regex, serialiser, merge, build) — the LLM-dependent stages are excluded because their cost is API-bound and not representative of typical cache-warm re-runs. Typical total: ~18 seconds, ~190 MB peak, dominated by spaCy model loading in the NER enrichment stage.

2. **Ontology metrics** — class count, object property count, datatype property count, max hierarchy depth, disjointness axiom count, equivalent class count, individual count. Run against both TTLs.

3. **Zaveri completeness metrics** — CM1 through CM4 as defined in Section 8.1. Run against both TTLs. Headline result: CM1 0.800 → 0.922, CM2 0.660 → 0.825, CM3 0.637 → 1.025, CM4 unchanged at 0.996.

4. **CQ answerability** — executes all 20 SPARQL queries from `om_n_om/Queries.rq` against both TTLs. Records pass/fail, row count, and per-query latency. Headline result: **20/20 answered on both TTLs, zero regressions**.

5. **Graph connectivity** — nodes, edges, average/max/median degree, clustering coefficient (sampled over 200 nodes), connected components, largest component size, density. 5CCSAKNEW07 slide 34 explicitly calls out these metrics for NLP-built KG evaluation. Typical result: ~1685 nodes, ~2905 edges, avg degree 3.45, clustering 0.30, 32 components with 86% of nodes in the largest.

6. **OntoClean meta-property tagging** — the 6 most-populated classes are tagged with Guarino & Welty's rigidity / identity / dependence meta-properties. Not a full OntoClean pass (that would require tagging all 50 classes) but enough to demonstrate methodological awareness and validate that subclasses don't relax their superclasses' rigidity.

7. **Triple sampling** — 50 random ABox triples written to `data/evaluation/triple_sample_50.txt` for manual spot-checking. Seed 42 for reproducibility.

8. **RAG vs baseline comparison table** — assembles every metric's pre/post/delta into a single summary at the end of the run.

### 4.2 `ner_benchmark.py` — NER quality vs gold standard (opt-in, ~15 s, free)

Evaluates the spaCy and regex extraction layers against a **30-sentence hand-annotated gold standard** drawn from Articles 3, 5, 6, 10, 14, 26, 43, 46, 50, 56, 73, 99, 113 and Annexes III, IV. The gold standard has 77 entity annotations across 6 entity types relevant to the AI Act KG: `AI_SYSTEM`, `STAKEHOLDER`, `REGULATION_REF`, `LEGISLATION`, `DEADLINE`, `MONEY`. It is persisted to `data/evaluation/ner_gold_standard.json` for reproducibility.

The benchmark scores three extractors against the same gold standard:

- **spaCy `en_core_web_sm` alone** — generic NER. Catches MONEY, DATE, LAW entities with reasonable precision but cannot see the three domain-specific entity types (AI_SYSTEM, STAKEHOLDER, REGULATION_REF). Overall recall is bounded by 11/77 ≈ 0.143 by construction. Measured overall F1 ≈ 0.15.

- **Regex pipeline alone** — reproduces the patterns from `ner_enrich.py`. Near-perfect precision and recall on the four entity types it targets (REGULATION_REF F1 = 0.96, LEGISLATION F1 = 1.00, DEADLINE F1 = 1.00, MONEY F1 = 1.00), zero on AI_SYSTEM and STAKEHOLDER. Overall F1 ≈ 0.46.

- **Combined (spaCy + regex)** — what the live pipeline uses. De-duplicates predictions by (normalised text, type) before scoring so a single gold entity matched by both extractors doesn't get counted as a false positive against itself.

**The story**: the regex layer is surgically accurate on the legal-citation and numeric entity types spaCy cannot see; spaCy adds partial coverage of the generic types; neither layer can handle the AI_SYSTEM and STAKEHOLDER semantic types, which is exactly why the pipeline has a third LLM extraction layer. This three-layer architecture is the quantitative justification for the pipeline design.

Writes `data/evaluation/ner_benchmark.json`.

### 4.3 `llm_baseline.py` — LLM-vs-KG comparison (opt-in, ~$0.01, ~30 s)

Answers the coursework requirement: *"how does the quality of its answers compare to e.g. simple prompts against an LLM"*. Implements the **LLMKE four-condition framework** from Zhang et al. 2023 (the canonical reference on 5CCSAKNEW10 slide 35), adapted for the before/after RAG story.

For 10 hand-picked CQs (CQ1, CQ3, CQ8, CQ9, CQ10, LLM1, LLM2, LLM6, LLM7, LLM10 — all with short verifiable answers, avoiding the 360-row cartesian queries), the script runs **four conditions**:

1. **KG-SPARQL only** — the deterministic answer from the KG itself (free, no LLM call)
2. **LLM-only** (no context) — `gpt-4.1-mini` answering from parametric knowledge
3. **LLM + pre-RAG KG context** — same model, but with the pre-RAG SPARQL result injected as context
4. **LLM + post-RAG KG context** — same model, with the post-RAG SPARQL result injected as context

Total: 30 LLM calls per run (~$0.01 at current `gpt-4.1-mini` pricing).

Each answer is scored on two dimensions:
- **Entity recall** — fraction of expected keywords (drawn from the KG ground truth) that the LLM mentions in its answer
- **Hallucination count** — number of Article or Annex references in the answer that are out-of-range (e.g. "Article 200" when the Act has only 113 articles)

Measured aggregate results:

| Condition | Recall | Hallucinations |
|---|---|---|
| LLM-only (no context) | 0.476 | **0** |
| LLM + pre-RAG KG context | 0.586 (+0.110) | **0** |
| LLM + post-RAG KG context | 0.615 (+0.139) | **0** |

The two strongest findings:

- **Zero hallucinations across all 30 calls**. The LLM never invented a non-existent Article or Annex number, with or without KG context. This is the cleanest possible argument that KG grounding works.
- **+11 percentage points from KG context**. Providing the pre-RAG KG's SPARQL answer as LLM context improves recall from 0.48 to 0.59 — a substantial and direction-consistent improvement. Providing the post-RAG context gives an additional +3 points, with the biggest single contribution from CQ9 (biometric conditions, +12 points) and LLM7 (enforcement powers, where the pre/post row count went from 4 to 14 and the context-delivered answers followed).

Writes `data/evaluation/llm_baseline.json` and a markdown summary at `data/evaluation/llm_baseline_report.md`.

### 4.4 Full evaluation report

The evaluation report — which is what actually goes into the submission — lives at `docs/EVALUATION_REPORT.md`. It has 10 sections covering every dimension listed above plus a RAG-vs-baseline comparison (Section 7) and a limitations discussion (Section 10). Numbers are populated from the three JSON outputs listed above.

---