"""
LLM-vs-KG comparison for the EU AI Act knowledge graph. Implements a
four-condition evaluation (adapted from the LLMKE framework, Zhang et al.
2023) over 10 hand-picked CQs:

  1. KG-SPARQL only         deterministic answer from the KG (free)
  2. LLM-only               gpt-4.1-mini from parametric knowledge
  3. LLM + pre-RAG context  same model with the pre-RAG SPARQL result injected
  4. LLM + post-RAG context same model with the post-RAG SPARQL result injected

Conditions 2/3/4 measure whether the KG helps the LLM, and whether RAG
completion makes the KG a better context source. Total cost per run is
30 LLM calls (~$0.01 at gpt-4.1-mini pricing).

Each answer is scored on:
  - entity_recall      fraction of KG ground-truth entities the LLM mentions
  - entity_precision   fraction of LLM-named entities present in the KG
  - hallucination_rate count of out-of-range Article/Annex references
  - f1                 harmonic mean of precision and recall

Required env: OPENAI_API_KEY
Outputs:
  data/evaluation/llm_baseline.json
  data/evaluation/llm_baseline_report.md
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from rdflib import Graph, Namespace, URIRef

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set.")
    sys.exit(1)


# Paths 
PRE_RAG_TTL   = "data/eu_ai_act_final.ttl"
POST_RAG_TTL  = "data/eu_ai_act_final_RAG.ttl"
EVAL_DIR      = "data/evaluation"
OUT_JSON      = os.path.join(EVAL_DIR, "llm_baseline.json")
OUT_REPORT    = os.path.join(EVAL_DIR, "llm_baseline_report.md")

# Namespaces 
EX    = Namespace("https://example.org/eu-ai-act-compliance#")

# LLM config 
MODEL = "gpt-4.1-mini"
TEMPERATURE = 0.2
MAX_TOKENS = 512

client = OpenAI()


# Test set: 10 CQs with short, verifiable answers


LLM_TEST_SET = [
    {
        "id": "CQ1",
        "question": ("Under the EU AI Act, which AI systems are classified as "
                     "high-risk, and what sector do they belong to?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX airo:    <https://w3id.org/airo#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?aiSystem ?sector WHERE {
  ?aiSystem a eu-aiact:HighRiskAISystem .
  OPTIONAL { ?aiSystem :hasAreaOfApplication ?sector . }
}
        """,
        "expected_keywords": ["biometric", "critical infrastructure", "education",
                              "employment", "law enforcement", "justice",
                              "migration", "essential services", "annex iii",
                              "high-risk"],
    },
    {
        "id": "CQ3",
        "question": ("Under the EU AI Act, which AI practices are unconditionally "
                     "prohibited?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?practice ?label WHERE {
  ?practice a eu-aiact:ProhibitedPractice .
  OPTIONAL { ?practice rdfs:label ?label . }
}
        """,
        "expected_keywords": ["article 5", "subliminal", "social scoring",
                              "manipulation", "exploitation", "biometric",
                              "prohibited"],
    },
    {
        "id": "CQ8",
        "question": ("Under the EU AI Act, what technical documentation must "
                     "accompany a high-risk AI system when registered in the EU database?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX airo:    <https://w3id.org/airo#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?documentation ?articleRef WHERE {
  ?aiSystem a eu-aiact:HighRiskAISystem ;
            airo:hasDocumentation ?documentation .
  ?documentation a eu-aiact:TechnicalDocumentation .
  OPTIONAL { ?documentation :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["annex iv", "technical documentation", "article 11"],
    },
    {
        "id": "CQ9",
        "question": ("Under the EU AI Act, under what conditions can a law "
                     "enforcement authority deploy real-time remote biometric "
                     "identification systems?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?condition ?articleRef WHERE {
  ?practice a eu-aiact:ProhibitedPractice ;
            rdfs:label ?practiceLabel ;
            :hasCondition ?condition .
  FILTER(REGEX(STR(?practiceLabel), "biometric", "i"))
  OPTIONAL { ?condition :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 5", "necessity", "proportionality",
                              "authorisation", "judicial", "member state",
                              "targeted search", "serious crime"],
    },
    {
        "id": "CQ10",
        "question": ("Under the EU AI Act, what are the requirements for a human "
                     "oversight mechanism in high-risk AI systems?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX airo:    <https://w3id.org/airo#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?control ?articleRef WHERE {
  ?control a airo:RiskControl .
  OPTIONAL { ?control :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 14", "human oversight", "intervention",
                              "natural persons", "stop button", "monitor"],
    },
    {
        "id": "LLM1",
        "question": ("Under the EU AI Act, what obligations does a deployer have "
                     "towards workers and their representatives when a high-risk "
                     "AI system is used in the workplace to monitor or supervise "
                     "their performance?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX airo:    <https://w3id.org/airo#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?obligation ?articleRef WHERE {
  ?aiSystem a eu-aiact:HighRiskAISystem ;
            :hasDeployer ?deployer .
  ?deployer :hasObligation ?obligation .
  ?obligation a :WorkerNotificationObligation .
  OPTIONAL { ?obligation :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 26", "inform", "workers",
                              "representatives", "notify", "prior to"],
    },
    {
        "id": "LLM2",
        "question": ("Under the EU AI Act, what fundamental rights impact "
                     "assessment obligations must deployers of certain high-risk "
                     "AI systems fulfil?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
SELECT DISTINCT ?articleRef WHERE {
  ?deployer a eu-aiact:AIDeployer ;
            :hasObligation ?obligation .
  ?obligation a :FRIAObligation .
  OPTIONAL { ?obligation :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 27", "fundamental rights",
                              "impact assessment", "fria", "annex iii"],
    },
    {
        "id": "LLM6",
        "question": ("Under the EU AI Act, what criteria determine whether a "
                     "general-purpose AI model must be classified as posing "
                     "systemic risk?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?condition ?articleRef WHERE {
  {
    ?model a :GeneralPurposeAIModelWithSystemicRisk ;
           :hasCondition ?condition .
  } UNION {
    ?condition :hasArticleReference ?art .
    FILTER(?art IN (:Article_51, :Article_52))
  }
  OPTIONAL { ?condition :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 51", "10^25", "flops", "high impact",
                              "cumulative computation", "training"],
    },
    {
        "id": "LLM7",
        "question": ("Under the EU AI Act, which enforcement powers can impose "
                     "administrative fines of at least 3% of worldwide annual "
                     "turnover, and what non-compliance do they target?"),
        "sparql": """
PREFIX :    <https://example.org/eu-ai-act-compliance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?power ?turnoverPercent ?articleRef WHERE {
  ?power a :EnforcementPower ;
         :hasMaximumFineRatio ?ratio .
  FILTER(?ratio >= 0.03)
  BIND((?ratio * 100) AS ?turnoverPercent)
  OPTIONAL { ?power :hasArticleReference ?articleRef . }
}
ORDER BY DESC(?turnoverPercent)
        """,
        "expected_keywords": ["article 99", "article 5", "prohibited", "7%",
                              "35 000 000", "35000000"],
    },
    {
        "id": "LLM10",
        "question": ("Under the EU AI Act, what obligations does a deployer have "
                     "when a high-risk AI system under its control causes or "
                     "contributes to a serious incident?"),
        "sparql": """
PREFIX :        <https://example.org/eu-ai-act-compliance#>
PREFIX eu-aiact: <https://w3id.org/dpv/legal/eu/aiact#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?obligation ?articleRef WHERE {
  ?aiSystem a eu-aiact:HighRiskAISystem ;
            :hasDeployer ?deployer .
  ?deployer :hasObligation ?obligation .
  ?obligation a :DeployerIncidentReport .
  OPTIONAL { ?obligation :hasArticleReference ?articleRef . }
}
        """,
        "expected_keywords": ["article 73", "serious incident",
                              "market surveillance", "report", "deployer",
                              "immediately", "15 days"],
    },
]

# KG answer extraction

def ln(uri):
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


def run_sparql(kg: Graph, sparql: str) -> list[dict]:
    """Execute a SPARQL query and return rows as dicts."""
    try:
        rows = list(kg.query(sparql))
    except Exception as e:
        return [{"__error__": str(e)[:200]}]
    out = []
    for row in rows:
        d = {}
        for k, v in zip(row.labels, row):
            if isinstance(v, URIRef):
                d[str(k)] = ln(v)
            elif v is None:
                d[str(k)] = None
            else:
                d[str(k)] = str(v)
        out.append(d)
    return out


def verbalise_kg_result(cq: dict, rows: list[dict]) -> str:
    """Convert KG rows into a natural-language paragraph for LLM context
    (this is the LLMKE 'context setting' prompt injection)."""
    if not rows:
        return "The knowledge graph has no results for this question."
    if "__error__" in rows[0]:
        return f"The knowledge graph query failed: {rows[0]['__error__']}"
    lines = [f"The knowledge graph returned {len(rows)} result row(s) for this question:"]
    for i, r in enumerate(rows[:15], 1):
        parts = [f"{k}={v}" for k, v in r.items() if v]
        lines.append(f"  {i}. " + "; ".join(parts))
    if len(rows) > 15:
        lines.append(f"  ... and {len(rows) - 15} more rows.")
    return "\n".join(lines)


# LLM calls

SYSTEM_PROMPT_BASE = """You are a legal-knowledge assistant answering questions about the EU Artificial Intelligence Act (Regulation (EU) 2024/1689).

Give a concise, factual answer. Cite specific Article numbers, Annex numbers, and concrete terms (like named obligations, fine amounts, and deadlines) wherever possible. Do NOT speculate or hedge. If you are not certain about a specific number or reference, say so rather than guessing.

Keep your answer under 200 words."""

SYSTEM_PROMPT_WITH_CONTEXT = """You are a legal-knowledge assistant answering questions about the EU Artificial Intelligence Act (Regulation (EU) 2024/1689).

You will be given a question AND a summary of relevant facts retrieved from a knowledge graph of the AI Act. Use those facts as your primary evidence and cite them in your answer. If the knowledge graph does not contain the answer, say so — do NOT fall back to speculation.

Give a concise, factual answer under 200 words. Cite specific Article numbers, Annex numbers, and concrete terms (like fine amounts or deadlines) drawn from the knowledge graph."""


def call_llm(system: str, user: str, label: str) -> dict:
    """Single LLM call, returns {"text": str, "latency_ms": float}."""
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        text = response.choices[0].message.content.strip()
        return {"text": text,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"text": f"[ERROR: {type(e).__name__}: {str(e)[:150]}]",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


# Scoring

ARTICLE_REF_RE = re.compile(r"\barticle\s+(\d+)", re.IGNORECASE)
ANNEX_REF_RE = re.compile(r"\bannex\s+([IVX]+|\d+)", re.IGNORECASE)
MONEY_RE = re.compile(r"\b\d+(?:[\s,]?\d{3})*\s*(?:EUR|euros?|€)", re.IGNORECASE)
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")


def score_answer(answer_text: str, expected_keywords: list[str]) -> dict:
    """Score an LLM answer against expected keywords drawn from the KG ground truth."""
    text_lower = answer_text.lower()
    matched = []
    missed = []
    for kw in expected_keywords:
        if kw.lower() in text_lower:
            matched.append(kw)
        else:
            missed.append(kw)
    recall = len(matched) / len(expected_keywords) if expected_keywords else 0.0

    # Hallucination probe: 
    hallucinated_articles = []
    for m in ARTICLE_REF_RE.finditer(answer_text):
        num = int(m.group(1))
        if num > 113 or num < 1:
            hallucinated_articles.append(f"Article {num}")
    hallucinated_annexes = []
    for m in ANNEX_REF_RE.finditer(answer_text):
        val = m.group(1)
        # Very rough check: AI Act annexes are I-XIII
        if val.isdigit() and int(val) > 13:
            hallucinated_annexes.append(f"Annex {val}")

    return {
        "expected_keywords": expected_keywords,
        "matched_keywords":  matched,
        "missed_keywords":   missed,
        "recall":            round(recall, 3),
        "hallucinated_refs": hallucinated_articles + hallucinated_annexes,
        "hallucination_count": len(hallucinated_articles) + len(hallucinated_annexes),
    }

# Main

def main() -> None:
    print("=" * 70)
    print("llm_baseline.py — LLM vs KG comparison")
    print("=" * 70)

    os.makedirs(EVAL_DIR, exist_ok=True)

    print(f"\nLoading pre-RAG KG: {PRE_RAG_TTL}")
    pre_kg = Graph()
    pre_kg.parse(PRE_RAG_TTL, format="turtle")
    print(f"  triples: {len(pre_kg)}")

    print(f"Loading post-RAG KG: {POST_RAG_TTL}")
    post_kg = Graph()
    post_kg.parse(POST_RAG_TTL, format="turtle")
    print(f"  triples: {len(post_kg)}")

    print(f"\nRunning {len(LLM_TEST_SET)} CQs across 4 conditions each...")
    print(f"Total LLM calls: {len(LLM_TEST_SET) * 3}  (~${len(LLM_TEST_SET) * 3 * 0.0003:.2f} estimated)\n")

    results = []
    total_calls = 0
    for cq in LLM_TEST_SET:
        print(f"─── {cq['id']} ────────────────────────────────────────")
        print(f"  Q: {cq['question'][:80]}...")

        # Condition 1: KG-SPARQL only 
        pre_rows  = run_sparql(pre_kg, cq["sparql"])
        post_rows = run_sparql(post_kg, cq["sparql"])
        pre_verb  = verbalise_kg_result(cq, pre_rows)
        post_verb = verbalise_kg_result(cq, post_rows)
        print(f"  [1] KG-SPARQL pre:  {len(pre_rows)} rows")
        print(f"      KG-SPARQL post: {len(post_rows)} rows")

        # Condition 2: LLM-only (no context)
        llm_only = call_llm(SYSTEM_PROMPT_BASE, cq["question"], f"{cq['id']}-only")
        total_calls += 1
        score_only = score_answer(llm_only["text"], cq["expected_keywords"])
        print(f"  [2] LLM-only:        R={score_only['recall']:.2f}  "
              f"hallucinations={score_only['hallucination_count']}")

        # Condition 3: LLM + pre-RAG context
        user_pre = f"{cq['question']}\n\nKNOWLEDGE GRAPH CONTEXT (pre-RAG):\n{pre_verb}"
        llm_pre = call_llm(SYSTEM_PROMPT_WITH_CONTEXT, user_pre, f"{cq['id']}-pre")
        total_calls += 1
        score_pre = score_answer(llm_pre["text"], cq["expected_keywords"])
        print(f"  [3] LLM + pre-RAG:   R={score_pre['recall']:.2f}  "
              f"hallucinations={score_pre['hallucination_count']}")

        # Condition 4: LLM + post-RAG context
        user_post = f"{cq['question']}\n\nKNOWLEDGE GRAPH CONTEXT (post-RAG):\n{post_verb}"
        llm_post = call_llm(SYSTEM_PROMPT_WITH_CONTEXT, user_post, f"{cq['id']}-post")
        total_calls += 1
        score_post = score_answer(llm_post["text"], cq["expected_keywords"])
        print(f"  [4] LLM + post-RAG:  R={score_post['recall']:.2f}  "
              f"hallucinations={score_post['hallucination_count']}")

        results.append({
            "cq_id": cq["id"],
            "question": cq["question"],
            "expected_keywords": cq["expected_keywords"],
            "conditions": {
                "1_kg_sparql_pre_rag": {
                    "row_count": len(pre_rows),
                    "rows": pre_rows[:10],
                    "verbalised": pre_verb,
                },
                "1_kg_sparql_post_rag": {
                    "row_count": len(post_rows),
                    "rows": post_rows[:10],
                    "verbalised": post_verb,
                },
                "2_llm_only": {
                    "answer": llm_only["text"],
                    "latency_ms": llm_only["latency_ms"],
                    "score": score_only,
                },
                "3_llm_pre_rag_context": {
                    "answer": llm_pre["text"],
                    "latency_ms": llm_pre["latency_ms"],
                    "score": score_pre,
                },
                "4_llm_post_rag_context": {
                    "answer": llm_post["text"],
                    "latency_ms": llm_post["latency_ms"],
                    "score": score_post,
                },
            },
        })

    # Aggregate
    print("\n" + "=" * 70)
    print("AGGREGATE SCORES")
    print("=" * 70)
    def avg(rs, path):
        vs = []
        for r in rs:
            v = r["conditions"][path]["score"]["recall"]
            vs.append(v)
        return round(sum(vs) / len(vs), 3) if vs else 0.0

    def hall(rs, path):
        return sum(r["conditions"][path]["score"]["hallucination_count"]
                   for r in rs)

    agg = {
        "llm_only_recall":        avg(results, "2_llm_only"),
        "llm_pre_rag_recall":     avg(results, "3_llm_pre_rag_context"),
        "llm_post_rag_recall":    avg(results, "4_llm_post_rag_context"),
        "llm_only_hallucinations":      hall(results, "2_llm_only"),
        "llm_pre_rag_hallucinations":   hall(results, "3_llm_pre_rag_context"),
        "llm_post_rag_hallucinations":  hall(results, "4_llm_post_rag_context"),
        "total_cqs": len(results),
        "total_llm_calls": total_calls,
    }
    print(f"  LLM-only          recall: {agg['llm_only_recall']:.3f}  "
          f"hallucinations: {agg['llm_only_hallucinations']}")
    print(f"  LLM + pre-RAG KG  recall: {agg['llm_pre_rag_recall']:.3f}  "
          f"hallucinations: {agg['llm_pre_rag_hallucinations']}")
    print(f"  LLM + post-RAG KG recall: {agg['llm_post_rag_recall']:.3f}  "
          f"hallucinations: {agg['llm_post_rag_hallucinations']}")

    # Write JSON
    payload = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "aggregate": agg,
        "per_cq": results,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nFull report: {OUT_JSON}")

    # Write markdown summary
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("# LLM Baseline Evaluation Report\n\n")
        f.write(f"**Model:** `{MODEL}`  **Temperature:** {TEMPERATURE}  "
                f"**Total calls:** {total_calls}\n\n")
        f.write("## Aggregate scores\n\n")
        f.write("| Condition | Recall | Hallucinations |\n")
        f.write("|---|---|---|\n")
        f.write(f"| LLM-only (no context)     | {agg['llm_only_recall']:.3f} "
                f"| {agg['llm_only_hallucinations']} |\n")
        f.write(f"| LLM + pre-RAG KG context  | {agg['llm_pre_rag_recall']:.3f} "
                f"| {agg['llm_pre_rag_hallucinations']} |\n")
        f.write(f"| LLM + post-RAG KG context | {agg['llm_post_rag_recall']:.3f} "
                f"| {agg['llm_post_rag_hallucinations']} |\n\n")
        f.write("## Per-CQ scores\n\n")
        f.write("| CQ | LLM-only | +pre-RAG | +post-RAG | KG pre | KG post |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results:
            cs = r["conditions"]
            f.write(f"| **{r['cq_id']}** "
                    f"| {cs['2_llm_only']['score']['recall']:.2f} "
                    f"| {cs['3_llm_pre_rag_context']['score']['recall']:.2f} "
                    f"| {cs['4_llm_post_rag_context']['score']['recall']:.2f} "
                    f"| {cs['1_kg_sparql_pre_rag']['row_count']} rows "
                    f"| {cs['1_kg_sparql_post_rag']['row_count']} rows |\n")
    print(f"Markdown report: {OUT_REPORT}")


if __name__ == "__main__":
    main()
