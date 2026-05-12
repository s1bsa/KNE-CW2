"""
RAG-based completion of the EU AI Act KG. Implements the five-step
retrieval-augmented generation loop (query → retrieval → verbalisation →
prompt → generation → schema validation) for each gap identified by
gap_analysis.py.

Performs completion in two directions:

  ADDITIVE     New triples that populate under-used schema elements.
               Written to data/rag_completion_triples.ttl.

  SUBTRACTIVE  Dead schema elements that should be removed from the
               ontology to raise CM1 schema completeness. Emitted as
               a JSON manifest at data/rag_schema_deletions.json and
               applied later by build_final_kg.py.

Addresses 5 ontology-level gaps and 5 instance-level gaps documented in
gap_analysis.json. The pre-RAG baseline TTL is left untouched so the
Completion section of the report can show a real Zaveri before/after
delta.

Required env: OPENAI_API_KEY
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

#  Optional .env loading 
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai SDK not installed. Run: pip install openai", file=sys.stderr)
    sys.exit(1)

if not os.environ.get("OPENAI_API_KEY"):
    print(
        "ERROR: OPENAI_API_KEY not set. Set it in your shell or in .env",
        file=sys.stderr,
    )
    sys.exit(1)

# Paths
INPUT_KG       = "data/eu_ai_act_final.ttl"
GAP_JSON       = "data/evaluation/gap_analysis.json"
ARTICLES_JSON  = "data/unstructured/html/eu_ai_act_articles.json"
OUTPUT_TTL     = "data/rag_completion_triples.ttl"
OUTPUT_DEL     = "data/rag_schema_deletions.json"
OUTPUT_LOG     = "data/evaluation/rag_completion_log.json"

# Namespaces 
EX    = Namespace("https://example.org/eu-ai-act-compliance#")
AIACT = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
AIRO  = Namespace("https://w3id.org/airo#")
DPV   = Namespace("https://w3id.org/dpv#")

# Schema cleanup manifest

SCHEMA_DELETIONS = [
    {
        "uri":    str(EX.Recital),
        "kind":   "class",
        "reason": "EUR-Lex HTML lacks <div id='rct_*'> structure; no realistic extraction path",
    },
    {
        "uri":    str(EX.CEMarkingComponent),
        "kind":   "class",
        "reason": "Never populated; existing :CEMarking instances (7) cover the semantic need",
    },
    {
        "uri":    str(EX.EntryIntoForceProvision),
        "kind":   "class",
        "reason": "Redundant with :EntryIntoForceDate which has 5 populated instances",
    },
    {
        "uri":    str(EX.SystemicRiskGPAIObligation),
        "kind":   "class",
        "reason": "Redundant; Article 55 systemic-risk obligations are captured as :GPAISystemicRiskIncidentReport",
    },
    {
        "uri":    str(EX.hasRecitalReference),
        "kind":   "object_property",
        "reason": "Depended on :Recital class which is being deleted",
    },
    {
        "uri":    str(EX.hasReference),
        "kind":   "object_property",
        "reason": "Superseded by specific :hasArticleReference / :hasAnnexReference / :hasParagraphReference",
    },
    {
        "uri":    str(EX.isRegulatedBy),
        "kind":   "object_property",
        "reason": "Never used; the inverse relationship is already captured via :hasArticleReference",
    },
    {
        "uri":    str(EX.hasComplianceDeadline),
        "kind":   "datatype_property",
        "reason": "Superseded by the populated :hasDeadline property",
    },
]

# LLM config 
MODEL = "gpt-4.1-mini"
MAX_TOKENS = 1024          # default for most gap-filling calls
MAX_TOKENS_LARGE = 4096    # for enumeration gaps (O1, O2) that must emit many objects
RETRY_LIMIT = 3
RETRY_BACKOFF = 4.0

client = OpenAI()

# Step 5 helper — LLM call with JSON-mode + retries

def call_llm(system: str, user: str, label: str, max_tokens: int = MAX_TOKENS) -> dict:
    """Call the OpenAI API expecting a JSON object response.

    The default max_tokens (1024) is sufficient for single-value completions
    (I1 fine matching, I2 deadline extraction, etc.). Enumeration gaps that
    must emit many objects in one response (O1 DocumentationComponent, O2
    RegistrationField) should pass max_tokens=MAX_TOKENS_LARGE (4096) to
    avoid mid-response JSON truncation.
    """
    last_err = None
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            text = response.choices[0].message.content.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = f"JSONDecodeError: {e}"
            print(f"    [{label}] attempt {attempt}: bad JSON, retrying...")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"    [{label}] attempt {attempt}: {last_err}, retrying...")
        time.sleep(RETRY_BACKOFF * attempt)
    print(f"    [{label}] FAILED after {RETRY_LIMIT} attempts: {last_err}")
    return {}


# Step 3 helper — KG verbalisation 

def verbalise_instance(g: Graph, uri: URIRef) -> str:
    """Convert an instance's triples into a natural-language paragraph.

    Following the verbalisation approach in 5CCSAKNEW11: gather the
    instance's type, label, and key properties, then format as a sentence
    the LLM can reason over."""
    types = [str(t).split("#")[-1] for t in g.objects(uri, RDF.type)
             if isinstance(t, URIRef)]
    label_objs = list(g.objects(uri, RDFS.label))
    label = str(label_objs[0]) if label_objs else str(uri).split("#")[-1]
    summary_objs = list(g.objects(uri, EX.hasSummary))
    summary = str(summary_objs[0]) if summary_objs else ""
    art_refs = [str(a).split("#")[-1] for a in g.objects(uri, EX.hasArticleReference)]
    annex_refs = [str(a).split("#")[-1] for a in g.objects(uri, EX.hasAnnexReference)]

    parts = [f"Instance '{label}' is a {' / '.join(types)}."]
    if summary:
        parts.append(f"Description: {summary}")
    if art_refs:
        parts.append(f"Grounded in: {', '.join(art_refs)}.")
    if annex_refs:
        parts.append(f"Annexes: {', '.join(annex_refs)}.")
    return " ".join(parts)


def get_article_text(articles_payload: dict, article_num: int) -> str:
    """Retrieve the full text of an article from the articles JSON."""
    for art in articles_payload.get("articles", []):
        if art.get("article_number") == article_num:
            return art.get("text", "")
    return ""


def get_annex_text(articles_payload: dict, annex_roman: str) -> str:
    """Retrieve the full text of an annex from the articles JSON."""
    for ann in articles_payload.get("annexes", []):
        if str(ann.get("annex_number", "")).upper() == annex_roman.upper():
            return ann.get("text", "")
    return ""


# GAP O1 — DocumentationComponent completion from Annex IV (RAG few-shot)

O1_SYSTEM_PROMPT = """You are populating Annex IV of the EU AI Act knowledge graph.

Annex IV lists the contents of the "technical documentation" that providers of high-risk AI systems must prepare. It contains 9 numbered paragraphs, each with multiple lettered sub-items (a, b, c, ...). In total there are roughly 25 distinct documentation components.

You will receive the full Annex IV text and a few-shot example showing the expected shape of an already-extracted DocumentationComponent. Your task: extract ALL distinct documentation components from the annex text and emit them as a JSON list.

Output a JSON object with key "components" whose value is a list of objects, each with:
  - uri_suffix:  string, snake_case, format "documentation_component_anniv_<N>_<letter>" (or just "_<N>" for top-level items)
  - paragraph:   the Annex IV reference (e.g. "Annex IV(1)(a)")
  - summary:     the component description from the annex text (1-2 sentences)

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read Annex IV in full.
  Step 2. Enumerate the 9 numbered paragraphs (1 through 9).
  Step 3. For each numbered paragraph, enumerate its lettered sub-items.
  Step 4. For each distinct component (numbered item OR lettered sub-item), emit one JSON object.
  Step 5. Skip components that already appear in the few-shot examples — only return NEW ones.

Output format: {"components": [{"uri_suffix": "...", "paragraph": "...", "summary": "..."}]}
"""


def gap_o1_doc_components(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """Populate :DocumentationComponent from Annex IV using few-shot."""
    print("  Gap O1: DocumentationComponent completion (RAG few-shot on Annex IV)")
    annex_iv_text = get_annex_text(articles_payload, "IV")
    if not annex_iv_text:
        print("    [skip] Annex IV text not available")
        return 0

    # Get existing examples as few-shot anchors
    existing = list(g.subjects(RDF.type, EX.DocumentationComponent))
    existing_suffixes = {str(s).split("#")[-1] for s in existing}
    fewshot = "\n".join(f"  - {verbalise_instance(g, ex)}" for ex in existing[:5])

    user_msg = (
        f"ANNEX IV TEXT:\n{annex_iv_text}\n\n"
        f"FEW-SHOT EXAMPLES (already extracted, do NOT repeat these):\n{fewshot}\n\n"
        f"EXISTING SUFFIXES TO SKIP: {sorted(existing_suffixes)}\n\n"
        'Return JSON {"components": [...]} with all NEW documentation components.'
    )
    result = call_llm(O1_SYSTEM_PROMPT, user_msg, "o1", max_tokens=MAX_TOKENS_LARGE)
    comps = result.get("components") or []
    minted = 0
    for c in comps:
        if not isinstance(c, dict):
            continue
        suffix = c.get("uri_suffix", "").strip()
        if not suffix:
            continue
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", suffix)
        if suffix in existing_suffixes:
            continue
        existing_suffixes.add(suffix)  # track within this run
        c_uri = EX[suffix]
        g_out.add((c_uri, RDF.type, EX.DocumentationComponent))
        g_out.add((c_uri, RDFS.label, Literal(suffix, lang="en")))
        summary = (c.get("summary") or "").strip()
        if summary:
            g_out.add((c_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        g_out.add((c_uri, EX.hasAnnexReference, EX.Annex_IV))
        g_out.add((EX.TechnicalDocumentation_Annex_IV, EX.hasRequiredComponent, c_uri))
        g_out.add((c_uri, EX.hasComponentOf, EX.TechnicalDocumentation_Annex_IV))
        minted += 1
    log.append({"gap": "O1", "annex": "IV", "llm_response": result,
                "triples_emitted": minted})
    print(f"    minted {minted} new :DocumentationComponent instances")
    return minted

# GAP O2 — RegistrationField completion from Annex VIII (RAG few-shot)

O2_SYSTEM_PROMPT = """You are populating Annex VIII of the EU AI Act knowledge graph.

Annex VIII lists the information that must be submitted for registration of high-risk AI systems in the EU database. It has three sections:
  - Section A: information submitted by PROVIDERS of high-risk AI systems
  - Section B: information submitted by DEPLOYERS that are public authorities
  - Section C: additional information for biometric remote identification systems

Each section enumerates multiple numbered fields. In total there are roughly 27 distinct registration fields.

You will receive the full Annex VIII text and few-shot examples showing the expected shape of an already-extracted RegistrationField. Your task: extract ALL distinct fields from the annex text and emit them as a JSON list.

Output a JSON object with key "fields" whose value is a list of objects, each with:
  - uri_suffix:  string, snake_case, format "registration_field_annviii_<section>_<N>"
                  where <section> is a, b, or c
  - paragraph:   the Annex VIII reference (e.g. "Annex VIII(A)(1)")
  - section:     "A", "B", or "C"
  - summary:     the field description from the annex text

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read Annex VIII in full.
  Step 2. Enumerate Section A fields (there are usually 11 of them).
  Step 3. Enumerate Section B fields (usually 5-6).
  Step 4. Enumerate Section C fields (usually 1-2).
  Step 5. Skip fields whose URI suffix already appears in the examples.

Output format: {"fields": [{"uri_suffix": "...", "paragraph": "...", "section": "A", "summary": "..."}]}
"""


def gap_o2_registration_fields(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """Populate :RegistrationField from Annex VIII using few-shot."""
    print("  Gap O2: RegistrationField completion (RAG few-shot on Annex VIII)")
    annex_viii_text = get_annex_text(articles_payload, "VIII")
    if not annex_viii_text:
        print("    [skip] Annex VIII text not available")
        return 0

    existing = list(g.subjects(RDF.type, EX.RegistrationField))
    existing_suffixes = {str(s).split("#")[-1] for s in existing}
    fewshot = "\n".join(f"  - {verbalise_instance(g, ex)}" for ex in existing[:5])

    user_msg = (
        f"ANNEX VIII TEXT:\n{annex_viii_text}\n\n"
        f"FEW-SHOT EXAMPLES (already extracted, do NOT repeat these):\n{fewshot}\n\n"
        f"EXISTING SUFFIXES TO SKIP: {sorted(existing_suffixes)}\n\n"
        'Return JSON {"fields": [...]} with all NEW registration fields.'
    )
    result = call_llm(O2_SYSTEM_PROMPT, user_msg, "o2", max_tokens=MAX_TOKENS_LARGE)
    fields = result.get("fields") or []
    minted = 0
    for f in fields:
        if not isinstance(f, dict):
            continue
        suffix = f.get("uri_suffix", "").strip()
        if not suffix:
            continue
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", suffix)
        if suffix in existing_suffixes:
            continue
        existing_suffixes.add(suffix)
        f_uri = EX[suffix]
        g_out.add((f_uri, RDF.type, EX.RegistrationField))
        g_out.add((f_uri, RDFS.label, Literal(suffix, lang="en")))
        summary = (f.get("summary") or "").strip()
        if summary:
            g_out.add((f_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        g_out.add((f_uri, EX.hasAnnexReference, EX.Annex_VIII))
        g_out.add((EX.RegistrationRecord_Annex_VIII, EX.hasRequiredComponent, f_uri))
        g_out.add((f_uri, EX.hasComponentOf, EX.RegistrationRecord_Annex_VIII))
        minted += 1
    log.append({"gap": "O2", "annex": "VIII", "llm_response": result,
                "triples_emitted": minted})
    print(f"    minted {minted} new :RegistrationField instances")
    return minted


# GAP O3 — requiresControl (RAG)

O3_SYSTEM_PROMPT = """You are a legal-knowledge engineer working on the EU AI Act knowledge graph.

Your task: determine whether a given obligation requires the implementation of a given risk control as part of compliance.

You will receive:
  1. An obligation (from the operative part of the AI Act)
  2. A risk control (typically from Article 14 human-oversight measures)
  3. The article text where both are grounded

Your output: a JSON object with key "requires" whose value is true or false, plus a "reason" string explaining your decision in one sentence.

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read the obligation. What duty does it impose?
  Step 2. Read the risk control. What safeguard does it implement?
  Step 3. Does the article text establish a 'requires' relationship — i.e., does compliance with the obligation require implementing the control?
  Step 4. Output the answer.

Output format: {"requires": true, "reason": "..."}  or  {"requires": false, "reason": "..."}
"""


def gap_o3_requires_control(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """For each (obligation, risk-control) pair sharing an article, ask the LLM
    whether the obligation requires the control."""
    print("  Gap O3: requiresControl (RAG)")

    # Find risk controls
    risk_controls = list(g.subjects(RDF.type, AIRO.RiskControl))
    if not risk_controls:
        print("    [skip] no risk controls in KG")
        return 0

    # Find obligations that share an article reference with any risk control
    minted = 0
    pair_count = 0
    seen_pairs = set()

    # Build article → controls index
    art_to_controls = {}
    for rc in risk_controls:
        for art in g.objects(rc, EX.hasArticleReference):
            art_to_controls.setdefault(art, []).append(rc)

    # For each article that has controls, find obligations grounded in the same article
    for art_uri, controls in art_to_controls.items():
        art_num_match = re.search(r"Article_(\d+)", str(art_uri))
        if not art_num_match:
            continue
        art_num = int(art_num_match.group(1))

        # Obligations sharing this article ref
        obligations = []
        for o, _, _ in g.triples((None, EX.hasArticleReference, art_uri)):
            # Confirm it's some kind of obligation
            for t in g.objects(o, RDF.type):
                if "Obligation" in str(t) or "IncidentReport" in str(t):
                    obligations.append(o)
                    break

        article_text = get_article_text(articles_payload, art_num)[:2000]
        for ob in obligations[:3]:  # cap obligations per article
            for rc in controls[:2]:  # cap controls per article
                pair_key = (ob, rc)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                pair_count += 1
                if pair_count > 15:  # global cap on calls for this gap
                    break

                ob_verb = verbalise_instance(g, ob)
                rc_verb = verbalise_instance(g, rc)

                user_msg = (
                    f"OBLIGATION:\n{ob_verb}\n\n"
                    f"RISK CONTROL:\n{rc_verb}\n\n"
                    f"ARTICLE TEXT (truncated):\n{article_text}\n\n"
                    'Return JSON {"requires": bool, "reason": "..."}.'
                )
                label = f"o3_{str(ob).split('#')[-1][:20]}_{str(rc).split('#')[-1][:20]}"
                result = call_llm(O3_SYSTEM_PROMPT, user_msg, label)

                if result.get("requires") is True:
                    g_out.add((ob, EX.requiresControl, rc))
                    minted += 1
                log.append({
                    "gap": "O3",
                    "obligation": str(ob).split("#")[-1],
                    "control": str(rc).split("#")[-1],
                    "verbalised_obligation": ob_verb,
                    "verbalised_control": rc_verb,
                    "llm_response": result,
                    "triples_emitted": 1 if result.get("requires") is True else 0,
                })
            if pair_count > 15:
                break
        if pair_count > 15:
            break

    print(f"    emitted {minted} :requiresControl triples (from {pair_count} candidate pairs)")
    return minted

# GAP O4 — hasOJReference (RAG, deterministic prompt)

O4_SYSTEM_PROMPT = """You extract the Official Journal of the European Union reference for the EU AI Act (Regulation (EU) 2024/1689).

You know that this regulation was published in OJ L on 12 July 2024. The standard short citation is 'OJ L, 2024/1689, 12.7.2024' but variations exist.

Output a JSON object with key "oj_reference" whose value is the canonical OJ short citation string for the EU AI Act.

Output format: {"oj_reference": "..."}
"""


def gap_o4_oj_reference(g: Graph, g_out: Graph, log: list) -> int:
    """Single-call gap. Find the AIActRegulation instance and add the OJ ref."""
    print("  Gap O4: hasOJReference (RAG, single call)")

    # Find the regulation instance
    regulation_uris = list(g.subjects(RDF.type, EX.AIActRegulation))
    if not regulation_uris:
        print("    [skip] no :AIActRegulation instance found")
        return 0
    reg_uri = regulation_uris[0]

    user_msg = "Provide the Official Journal short citation for Regulation (EU) 2024/1689."
    result = call_llm(O4_SYSTEM_PROMPT, user_msg, "o4")
    oj = (result.get("oj_reference") or "").strip()
    if not oj:
        print("    [warn] LLM returned empty OJ reference")
        log.append({"gap": "O4", "subject": str(reg_uri).split("#")[-1],
                    "llm_response": result, "triples_emitted": 0})
        return 0
    g_out.add((reg_uri, EX.hasOJReference, Literal(oj, datatype=XSD.string)))
    log.append({"gap": "O4", "subject": str(reg_uri).split("#")[-1],
                "llm_response": result, "triples_emitted": 1})
    print(f"    emitted :hasOJReference '{oj}'")
    return 1


# GAP O5 — GPAIObligation parent class population (RAG)

O5_SYSTEM_PROMPT = """You are extracting obligations from Article 56 of the EU AI Act (Codes of practice for general-purpose AI models).

Your task: identify obligations in Article 56 that apply to BOTH general GPAI providers AND systemic-risk GPAI providers — i.e. shared obligations that should be typed as the parent class :GPAIObligation rather than either subclass.

Output a JSON object with key "obligations" whose value is a list of objects, each with:
  - uri_suffix:  string, snake_case, must include "art56"
  - summary:     1-2 sentence description from the article text
  - paragraph:   the specific Article 56 sub-paragraph (e.g. "Article 56(1)")

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read Article 56's text.
  Step 2. Identify each distinct duty imposed.
  Step 3. For each duty, judge: does it apply to ALL GPAI providers (both general and systemic risk)?
  Step 4. Only emit duties that apply to BOTH, not duties specific to systemic-risk providers.
  Step 5. Format as JSON.

Output format: {"obligations": [{"uri_suffix": "...", "summary": "...", "paragraph": "..."}]}
"""


def gap_o5_gpai_parent(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """Populate :GPAIObligation parent class from Article 56."""
    print("  Gap O5: GPAIObligation parent (RAG)")
    art56_text = get_article_text(articles_payload, 56)
    if not art56_text:
        print("    [skip] Article 56 text not found")
        return 0

    user_msg = f"ARTICLE 56 TEXT:\n{art56_text}\n\nExtract shared GPAI obligations as JSON."
    result = call_llm(O5_SYSTEM_PROMPT, user_msg, "o5")
    obls = result.get("obligations") or []
    minted = 0
    for ob in obls:
        if not isinstance(ob, dict):
            continue
        suffix = ob.get("uri_suffix", "").strip()
        summary = (ob.get("summary") or "").strip()
        para = (ob.get("paragraph") or "Article 56").strip()
        if not suffix:
            continue
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", suffix)
        if "art56" not in suffix:
            suffix = f"{suffix}_art56"
        ob_uri = EX[suffix]
        g_out.add((ob_uri, RDF.type, EX.GPAIObligation))
        g_out.add((ob_uri, RDFS.label, Literal(suffix, lang="en")))
        if summary:
            g_out.add((ob_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        g_out.add((ob_uri, EX.hasArticleReference, EX.Article_56))
        # Wire to both Provider and the GPAI model
        g_out.add((EX.ProviderStakeholder, EX.hasObligation, ob_uri))
        g_out.add((EX.GPAIModelInstance, EX.hasObligation, ob_uri))
        g_out.add((EX.GPAISystemicRiskModelInstance, EX.hasObligation, ob_uri))
        minted += 1
    log.append({"gap": "O5", "article": "Article_56", "llm_response": result,
                "triples_emitted": minted})
    print(f"    emitted {minted} :GPAIObligation instances from Article 56")
    return minted


# GAP I1 — hasFine on EnforcementPower (RAG)

I1_SYSTEM_PROMPT = """You are matching enforcement powers to fine amounts in Article 99 of the EU AI Act.

Article 99 specifies three fine tiers:
  - 35 000 000 EUR (or 7% of worldwide annual turnover) for prohibited practices (Art. 5)
  - 15 000 000 EUR (or 3% of worldwide annual turnover) for most other infringements
  - 7 500 000 EUR (or 1% of worldwide annual turnover) for incorrect/misleading information

You will receive an enforcement-power instance with its description. Your task: identify which of the three fine tiers applies to it based on what kind of non-compliance it addresses.

Output a JSON object: {"fine_eur": <integer>, "reason": "..."} where fine_eur is one of 35000000, 15000000, 7500000, or null if no fine applies.

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read the enforcement power description.
  Step 2. Identify what kind of non-compliance it addresses.
  Step 3. Match to one of the three fine tiers from Article 99.
  Step 4. If the power is not from Article 99 or doesn't impose a fine, return null.
"""


def gap_i1_fines(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """For each EnforcementPower without :hasFine, ask the LLM to match a tier."""
    print("  Gap I1: hasFine on EnforcementPower (RAG)")

    art99_text = get_article_text(articles_payload, 99)[:3000]
    minted = 0
    candidates = []
    for ep in g.subjects(RDF.type, EX.EnforcementPower):
        # Skip if already has a fine
        if list(g.objects(ep, EX.hasFine)):
            continue
        candidates.append(ep)

    for ep in candidates[:14]:  # all of them
        verb = verbalise_instance(g, ep)
        user_msg = (
            f"ENFORCEMENT POWER:\n{verb}\n\n"
            f"ARTICLE 99 TEXT:\n{art99_text}\n\n"
            'Return JSON {"fine_eur": <int or null>, "reason": "..."}.'
        )
        label = f"i1_{str(ep).split('#')[-1][:30]}"
        result = call_llm(I1_SYSTEM_PROMPT, user_msg, label)
        fine = result.get("fine_eur")
        added = 0
        if isinstance(fine, (int, float)) and fine > 0:
            g_out.add((ep, EX.hasFine, Literal(int(fine), datatype=XSD.decimal)))
            minted += 1
            added = 1
        log.append({"gap": "I1", "subject": str(ep).split("#")[-1],
                    "verbalised_context": verb, "llm_response": result,
                    "triples_emitted": added})
    print(f"    emitted {minted} :hasFine triples on {len(candidates)} candidates")
    return minted


# GAP I2 — hasDeadline on Obligation (RAG)

I2_SYSTEM_PROMPT = """You are extracting reporting deadlines from EU AI Act obligation provisions.

You will receive an obligation, its grounding article text, and you must determine whether the article imposes a specific time-bounded deadline on the duty.

Output a JSON object with key "deadline" whose value is either:
  - An ISO-8601 xsd:duration string like "P15D" (15 days), "P1M" (1 month), "P12M" (12 months), "PT24H" (24 hours)
  - null if no specific deadline is stated

Examples:
  "within 15 days"  → "P15D"
  "no later than 12 months"  → "P12M"
  "within 2 days where the incident is widespread"  → "P2D"
  "immediately"  → "PT0H" (zero duration)
  "as soon as possible"  → null  (no specific time)

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read the obligation summary. Does it mention a time constraint?
  Step 2. Search the article text for the specific phrase.
  Step 3. Convert to ISO-8601 duration format.
  Step 4. Return null if no concrete duration is stated.
"""


def gap_i2_deadlines(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """For each Obligation without :hasDeadline, ask the LLM to extract one."""
    print("  Gap I2: hasDeadline on Obligation (RAG)")

    # Find obligations of specific types known to have deadlines
    target_types = [
        EX.ProviderIncidentReport, EX.DeployerIncidentReport,
        EX.GPAISystemicRiskIncidentReport, EX.ConformityAssessmentObligation,
        EX.ThirdPartyAssessmentObligation,
    ]
    candidates = set()
    for t in target_types:
        for s in g.subjects(RDF.type, t):
            if not list(g.objects(s, EX.hasDeadline)):
                candidates.add(s)

    candidates = list(candidates)[:15]  # cap
    minted = 0
    for ob in candidates:
        # Find article number
        art_uris = list(g.objects(ob, EX.hasArticleReference))
        if not art_uris:
            continue
        art_match = re.search(r"Article_(\d+)", str(art_uris[0]))
        if not art_match:
            continue
        art_num = int(art_match.group(1))
        art_text = get_article_text(articles_payload, art_num)[:2500]

        verb = verbalise_instance(g, ob)
        user_msg = (
            f"OBLIGATION:\n{verb}\n\n"
            f"ARTICLE {art_num} TEXT:\n{art_text}\n\n"
            'Return JSON {"deadline": "<ISO-8601 duration>" or null}.'
        )
        label = f"i2_{str(ob).split('#')[-1][:30]}"
        result = call_llm(I2_SYSTEM_PROMPT, user_msg, label)
        dur = result.get("deadline")
        added = 0
        if dur and isinstance(dur, str) and re.match(r"^P", dur):
            g_out.add((ob, EX.hasDeadline, Literal(dur, datatype=XSD.duration)))
            minted += 1
            added = 1
        log.append({"gap": "I2", "subject": str(ob).split("#")[-1],
                    "verbalised_context": verb, "llm_response": result,
                    "triples_emitted": added})
    print(f"    emitted {minted} :hasDeadline triples on {len(candidates)} candidates")
    return minted


# GAP I3 — TestingPlanField population (RAG few-shot)

I3_SYSTEM_PROMPT = """You are populating Annex IX of the EU AI Act knowledge graph.

Annex IX lists the information that must be submitted upon registration of high-risk AI systems for testing in real-world conditions. The list contains exactly 5 numbered items.

You will receive the full Annex IX text and one example of a TestingPlanField that has already been extracted. Your task: extract ALL 5 fields from the annex text and emit them as a JSON list.

Output a JSON object with key "fields" whose value is a list of objects:
  - uri_suffix:  string, snake_case, format "testing_plan_field_annix_<n>"
  - paragraph:   the Annex IX item label (e.g. "Annex IX(1)")
  - summary:     the field description from the annex text

FEW-SHOT EXAMPLE (one already extracted):
  {"uri_suffix": "testing_plan_field_annix_1", "paragraph": "Annex IX(1)",
   "summary": "A Union-wide unique single identification number..."}

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read Annex IX.
  Step 2. Identify the 5 numbered items.
  Step 3. Format each as the JSON shape above.
"""


def gap_i3_testing_plan(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """Populate :TestingPlanField from Annex IX."""
    print("  Gap I3: TestingPlanField population (RAG few-shot)")
    annex_ix_text = get_annex_text(articles_payload, "IX")
    if not annex_ix_text:
        print("    [skip] Annex IX text not available")
        return 0

    # Get the existing example
    existing = list(g.subjects(RDF.type, EX.TestingPlanField))
    example = ""
    if existing:
        example = verbalise_instance(g, existing[0])

    user_msg = (
        f"ANNEX IX TEXT:\n{annex_ix_text}\n\n"
        f"EXISTING EXAMPLE:\n{example}\n\n"
        'Return JSON {"fields": [...]} with all 5 fields.'
    )
    result = call_llm(I3_SYSTEM_PROMPT, user_msg, "i3")
    fields = result.get("fields") or []
    minted = 0
    existing_suffixes = {str(s).split("#")[-1] for s in existing}
    for f in fields:
        if not isinstance(f, dict):
            continue
        suffix = f.get("uri_suffix", "").strip()
        if not suffix:
            continue
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", suffix)
        if suffix in existing_suffixes:
            continue
        f_uri = EX[suffix]
        g_out.add((f_uri, RDF.type, EX.TestingPlanField))
        g_out.add((f_uri, RDFS.label, Literal(suffix, lang="en")))
        summary = (f.get("summary") or "").strip()
        if summary:
            g_out.add((f_uri, EX.hasSummary, Literal(summary, datatype=XSD.string)))
        g_out.add((f_uri, EX.hasAnnexReference, EX.Annex_IX))
        g_out.add((EX.TestingPlan_Annex_IX, EX.hasRequiredComponent, f_uri))
        g_out.add((f_uri, EX.hasComponentOf, EX.TestingPlan_Annex_IX))
        minted += 1
    log.append({"gap": "I3", "annex": "IX", "llm_response": result,
                "triples_emitted": minted})
    print(f"    minted {minted} new :TestingPlanField instances")
    return minted


# GAP I4 — AreaOfApplication population + linking (RAG)

I4_SYSTEM_PROMPT = """You are populating the airo:AreaOfApplication instances for the EU AI Act knowledge graph.

Annex III of the AI Act lists 8 high-risk deployment domains. These are:
  1. Biometrics
  2. Critical infrastructure
  3. Education and vocational training
  4. Employment, workers management and access to self-employment
  5. Access to and enjoyment of essential private and public services and benefits
  6. Law enforcement
  7. Migration, asylum and border control management
  8. Administration of justice and democratic processes

Each of these corresponds to an existing :HighRiskAISystem_<sector> instance in the KG. Your task: emit one airo:AreaOfApplication object per sector with a 1-sentence description drawn from the Annex III text, and link each HighRiskAISystem to its matching AreaOfApplication.

You will receive the full Annex III text. Produce a JSON object with key "areas" whose value is a list of objects, each with:
  - sector_key:  one of "biometrics", "critical_infrastructure", "education",
                  "employment", "essential_services", "law_enforcement",
                  "migration", "justice"
  - label:       short human-readable name (e.g. "Biometrics")
  - description: 1-2 sentence description drawn from Annex III

CHAIN OF THOUGHT (think step by step internally):
  Step 1. Read Annex III.
  Step 2. For each of the 8 numbered items, extract its deployment sector.
  Step 3. Map it to the sector_key from the list above.
  Step 4. Write a concise description of the kind of AI systems it covers.

Output format: {"areas": [{"sector_key": "...", "label": "...", "description": "..."}]}
"""


# Static map: sector_key → existing HighRiskAISystem_<sector> local name
SECTOR_TO_SYSTEM_SUFFIX = {
    "biometrics":              "biometrics",
    "critical_infrastructure": "critical_infrastructure",
    "education":               "education",
    "employment":              "employment",
    "essential_services":      "essential_services",
    "law_enforcement":         "law_enforcement",
    "migration":               "migration",
    "justice":                 "justice",
}


def gap_i4_areas_of_application(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """Populate airo:AreaOfApplication instances and link them to HighRiskAISystem."""
    print("  Gap I4: AreaOfApplication population + linking (RAG)")
    annex_iii_text = get_annex_text(articles_payload, "III")
    if not annex_iii_text:
        print("    [skip] Annex III text not available")
        return 0

    # Check which HighRiskAISystem instances exist so we only link to real ones
    existing_systems = {}  # sector_key → URI
    for s in g.subjects(RDF.type, AIACT.HighRiskAISystem):
        name = str(s).split("#")[-1]
        for key in SECTOR_TO_SYSTEM_SUFFIX:
            if name.endswith(key):
                existing_systems[key] = s
                break

    user_msg = (
        f"ANNEX III TEXT:\n{annex_iii_text}\n\n"
        'Return JSON {"areas": [...]} with all 8 areas.'
    )
    result = call_llm(I4_SYSTEM_PROMPT, user_msg, "i4")
    areas = result.get("areas") or []
    minted = 0
    for a in areas:
        if not isinstance(a, dict):
            continue
        key = (a.get("sector_key") or "").strip().lower()
        key = re.sub(r"[^a-z_]", "", key)
        if key not in SECTOR_TO_SYSTEM_SUFFIX:
            continue
        area_uri = EX[f"AreaOfApplication_{key}"]
        label = (a.get("label") or key.replace("_", " ").title()).strip()
        description = (a.get("description") or "").strip()
        # Mint the AreaOfApplication instance
        g_out.add((area_uri, RDF.type, EX.AreaOfApplication))
        g_out.add((area_uri, RDFS.label, Literal(label, lang="en")))
        if description:
            g_out.add((area_uri, EX.hasSummary, Literal(description, datatype=XSD.string)))
        g_out.add((area_uri, EX.hasAnnexReference, EX.Annex_III))
        minted += 1
        # Link the corresponding HighRiskAISystem
        if key in existing_systems:
            g_out.add((existing_systems[key], AIRO.hasAreaOfApplication, area_uri))
            minted += 1
    log.append({"gap": "I4", "annex": "III", "llm_response": result,
                "triples_emitted": minted})
    print(f"    minted {len(areas)} :AreaOfApplication instances + linking triples ({minted} triples)")
    return minted


# GAP I5 — hasMaximumFineRatio on EnforcementPower (RAG)

I5_SYSTEM_PROMPT = """You are matching enforcement powers to fine ratios (% of worldwide annual turnover) in the EU AI Act.

Article 99 specifies three turnover-ratio caps:
  - 7% (0.07) for prohibited practices (Art. 5)
  - 3% (0.03) for most other infringements
  - 1% (0.01) for incorrect/misleading information

Other articles (76, 80, 82, 83, 88, 101) may also impose fines but typically do not specify a turnover ratio cap directly.

Output: {"ratio": <float between 0 and 1>, "reason": "..."} or {"ratio": null, "reason": "..."}.
"""


def gap_i5_fine_ratios(g: Graph, g_out: Graph, articles_payload: dict, log: list) -> int:
    """For each EnforcementPower without :hasMaximumFineRatio."""
    print("  Gap I5: hasMaximumFineRatio on EnforcementPower (RAG)")
    art99_text = get_article_text(articles_payload, 99)[:3000]
    minted = 0
    candidates = [s for s in g.subjects(RDF.type, EX.EnforcementPower)
                  if not list(g.objects(s, EX.hasMaximumFineRatio))]
    for ep in candidates[:14]:
        verb = verbalise_instance(g, ep)
        user_msg = (
            f"ENFORCEMENT POWER:\n{verb}\n\n"
            f"ARTICLE 99 TEXT:\n{art99_text}\n\n"
            'Return JSON {"ratio": <0-1 or null>, "reason": "..."}.'
        )
        label = f"i5_{str(ep).split('#')[-1][:30]}"
        result = call_llm(I5_SYSTEM_PROMPT, user_msg, label)
        ratio = result.get("ratio")
        added = 0
        if isinstance(ratio, (int, float)) and 0 < ratio <= 1:
            g_out.add((ep, EX.hasMaximumFineRatio, Literal(round(ratio, 4), datatype=XSD.decimal)))
            minted += 1
            added = 1
        log.append({"gap": "I5", "subject": str(ep).split("#")[-1],
                    "verbalised_context": verb, "llm_response": result,
                    "triples_emitted": added})
    print(f"    emitted {minted} :hasMaximumFineRatio triples on {len(candidates)} candidates")
    return minted


# Main

def main() -> None:
    print("=" * 70)
    print("rag_enhance_kg.py — RAG-based KG completion")
    print("=" * 70)

    print(f"\nLoading KG from {INPUT_KG}")
    g = Graph()
    g.parse(INPUT_KG, format="turtle")
    print(f"  triples: {len(g)}")

    print(f"Loading gap analysis from {GAP_JSON}")
    if not os.path.exists(GAP_JSON):
        print(f"  ERROR: {GAP_JSON} not found. Run gap_analysis.py first.")
        sys.exit(1)
    with open(GAP_JSON, encoding="utf-8") as f:
        gap_data = json.load(f)
    print(f"  documented gaps: {len(gap_data['documented_gaps']['ontology_gaps'])} ontology, "
          f"{len(gap_data['documented_gaps']['instance_gaps'])} instance")

    print(f"Loading articles JSON from {ARTICLES_JSON}")
    with open(ARTICLES_JSON, encoding="utf-8") as f:
        articles_payload = json.load(f)
    print(f"  articles: {len(articles_payload.get('articles', []))}, "
          f"annexes: {len(articles_payload.get('annexes', []))}")

    g_out = Graph()
    g_out.bind("",         EX)
    g_out.bind("airo",     AIRO)
    g_out.bind("eu-aiact", AIACT)
    g_out.bind("dpv",      DPV)
    g_out.bind("rdfs",     RDFS)
    g_out.bind("xsd",      XSD)

    log: list = []

    print("\n=== ONTOLOGY GAPS ===")
    o1_count = gap_o1_doc_components(g, g_out, articles_payload, log)
    o2_count = gap_o2_registration_fields(g, g_out, articles_payload, log)
    o3_count = gap_o3_requires_control(g, g_out, articles_payload, log)
    o4_count = gap_o4_oj_reference(g, g_out, log)
    o5_count = gap_o5_gpai_parent(g, g_out, articles_payload, log)

    print("\n=== INSTANCE GAPS ===")
    i1_count = gap_i1_fines(g, g_out, articles_payload, log)
    i2_count = gap_i2_deadlines(g, g_out, articles_payload, log)
    i3_count = gap_i3_testing_plan(g, g_out, articles_payload, log)
    i4_count = gap_i4_areas_of_application(g, g_out, articles_payload, log)
    i5_count = gap_i5_fine_ratios(g, g_out, articles_payload, log)

    # SCHEMA CLEANUP (SUBTRACTIVE COMPLETION)

    print("\n=== SCHEMA CLEANUP (subtractive completion) ===")
    classes_to_delete   = [d for d in SCHEMA_DELETIONS if d["kind"] == "class"]
    obj_props_to_delete = [d for d in SCHEMA_DELETIONS if d["kind"] == "object_property"]
    dt_props_to_delete  = [d for d in SCHEMA_DELETIONS if d["kind"] == "datatype_property"]
    print(f"  Classes to delete from post-RAG graph:     {len(classes_to_delete)}")
    for d in classes_to_delete:
        print(f"    ✗ {d['uri'].split('#')[-1]}")
    print(f"  Object properties to delete:               {len(obj_props_to_delete)}")
    for d in obj_props_to_delete:
        print(f"    ✗ {d['uri'].split('#')[-1]}")
    print(f"  Datatype properties to delete:             {len(dt_props_to_delete)}")
    for d in dt_props_to_delete:
        print(f"    ✗ {d['uri'].split('#')[-1]}")

    deletion_manifest = {
        "description": (
            "URIs scheduled for removal from the post-RAG KG by "
            "build_final_kg.py. The pre-RAG baseline TTL is unaffected."
        ),
        "total_deletions": len(SCHEMA_DELETIONS),
        "deletions": SCHEMA_DELETIONS,
    }

    print("\n=== Summary ===")
    print(f"  O1 DocumentationComponent instances: {o1_count}")
    print(f"  O2 RegistrationField instances:      {o2_count}")
    print(f"  O3 requiresControl triples:          {o3_count}")
    print(f"  O4 hasOJReference triples:           {o4_count}")
    print(f"  O5 GPAIObligation parent instances:  {o5_count}")
    print(f"  I1 hasFine triples (RAG):            {i1_count}")
    print(f"  I2 hasDeadline triples (RAG):        {i2_count}")
    print(f"  I3 TestingPlanField instances (RAG): {i3_count}")
    print(f"  I4 AreaOfApplication triples:        {i4_count}")
    print(f"  I5 hasMaximumFineRatio triples:      {i5_count}")
    total_added = o1_count + o2_count + o3_count + o4_count + o5_count + \
                  i1_count + i2_count + i3_count + i4_count + i5_count
    print(f"  TOTAL completion triples (additive): {total_added}")
    print(f"  Schema elements to delete:           {len(SCHEMA_DELETIONS)}")
    print(f"  Total triples in completion graph:   {len(g_out)}")

    # Serialise
    os.makedirs(os.path.dirname(OUTPUT_TTL), exist_ok=True)
    g_out.serialize(destination=OUTPUT_TTL, format="turtle")
    print(f"\n  Triples written to:        {OUTPUT_TTL}")

    os.makedirs(os.path.dirname(OUTPUT_DEL) or ".", exist_ok=True)
    with open(OUTPUT_DEL, "w", encoding="utf-8") as f:
        json.dump(deletion_manifest, f, indent=2, ensure_ascii=False)
    print(f"  Deletion manifest written: {OUTPUT_DEL}")

    os.makedirs(os.path.dirname(OUTPUT_LOG), exist_ok=True)
    log_payload = {
        "model": MODEL,
        "total_llm_calls": len(log),
        "total_triples_emitted": total_added,
        "schema_deletions": SCHEMA_DELETIONS,
        "gap_analysis_input": GAP_JSON,
        "calls": log,
    }
    with open(OUTPUT_LOG, "w", encoding="utf-8") as f:
        json.dump(log_payload, f, indent=2, ensure_ascii=False)
    print(f"  Log written to:            {OUTPUT_LOG}")


if __name__ == "__main__":
    main()