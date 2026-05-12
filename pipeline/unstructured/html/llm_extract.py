"""
Stage 2 of the HTML extraction pipeline: LLM-based extraction of the
domain-semantic instances that require judgement — obligations, powers,
conditions, and a small set of anchor entities (NaturalPersonSubject,
AIRegulatorySandbox, CEMarking).

Calls gpt-4.1-mini once per article and once per annex. Uses a subtype
anchor table to force the right ontology subclass for high-value articles
(Articles 26, 53, 55, 73, 99). Each emitted instance carries `cq_targets`
(which CQs it's meant to support) and `evidence_text` (the supporting
clause excerpt).

Annex/structural content is owned by the rule-based stage and explicitly
forbidden in the prompt.

Required env: OPENAI_API_KEY
Output: data/unstructured/html/llm_extraction.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Optional .env loading 
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
        "ERROR: OPENAI_API_KEY not set.\n"
        "Set it in your shell:\n"
        "    export OPENAI_API_KEY=sk-proj-...\n"
        "Or create a .env file at the repo root containing:\n"
        "    OPENAI_API_KEY=sk-proj-...",
        file=sys.stderr,
    )
    sys.exit(1)

# Paths 
INPUT_PATH  = "data/unstructured/html/eu_ai_act_articles.json"
OUTPUT_PATH = "data/unstructured/html/llm_extraction.json"

# LLM config 
MODEL = "gpt-4.1-mini"
MAX_TOKENS = 4096
RETRY_LIMIT = 3
RETRY_BACKOFF = 4.0

client = OpenAI()

# Single-pass instance extraction prompt

INSTANCE_SYSTEM_PROMPT = """You are extracting ontology-aligned instances from a single article (or annex) of the EU AI Act for a knowledge graph.

You MUST return a single JSON object — no prose, no markdown fences. The JSON has one top-level key: "instances", whose value is a list of objects.

Each instance object has these fields:
  - uri_suffix:    string, lowercase ASCII with underscores, unique within this source
  - type:          one of the allowed type values listed below (case-sensitive)
  - summary:       string, 1-3 sentences describing what this instance IS, drawn from the source text
  - paragraph_ref: string or null — the most specific reference like "Article 5(1)(a)" if known, otherwise the article reference like "Article 5"
  - cq_targets:    list of strings — competency-question ids this instance supports (e.g. ["CQ2", "LLM4"]). Use the CQ MAP at the end of this prompt to choose. Empty list [] is acceptable.
  - evidence_text: string ≤200 chars — the minimal clause from the source text that justifies this extraction. Used for traceability.

Allowed type values (case-sensitive — use the exact string):

  ── OBLIGATIONS (duties that someone must perform) ──
    "ConformityAssessmentObligation"        general duty to undergo conformity assessment
    "InternalControlObligation"             Annex VI internal-control procedure
    "ThirdPartyAssessmentObligation"        Annex VII third-party (notified body) procedure
    "TransparencyObligation"                Articles 13, 26(8), 50 — disclosure to users / natural persons
    "PostMarketMonitoringObligation"        Articles 9, 72
    "WorkerNotificationObligation"          Article 26(7) — informing workers and reps
    "FRIAObligation"                        Article 27 — fundamental rights impact assessment
    "ProviderIncidentReport"                Article 73 — provider reports incidents
    "DeployerIncidentReport"                Article 26(5) — deployer reports incidents
    "GPAISystemicRiskIncidentReport"        Article 55(1)(c) — GPAI provider reports to AI Office
    "IncidentReportingObligation"           parent — only if subtype is unclear
    "GeneralGPAIObligation"                 Articles 53, 54
    "SystemicRiskGPAIObligation"            Article 55(1)(a,b,d)
    "GPAIObligation"                        parent — only if subtype is unclear
    "SupportMeasureObligation"              Article 62 — SME / startup support measures

  ── POWERS (regulatory authority competences) ──
    "OversightPower"                        general supervision / monitoring
    "InvestigativePower"                    inspection, document requests, evidence gathering
    "EnforcementPower"                      sanctions, fines, market withdrawal (Articles 99-101)
    "AdvisoryPower"                         issuing guidance, opinions, recommendations

  ── CONDITIONS (gating clauses, exceptions, derogations, eligibility criteria) ──
    "NecessityCondition"                    "strictly necessary for…"
    "ProportionalityCondition"              "proportionate to…"
    "ProceduralCondition"                   prior authorisation, notification, registration
    "PurposeCondition"                      restricted to specific purposes (e.g. one of an enumerated list)

  ── DOMAIN ENTITIES (judgement required) ──
    "CEMarking"                             Articles 47, 48, 49
    "AIRegulatorySandbox"                   Articles 57-63 — at most ONE per article (see rule 5)
    "NaturalPersonSubject"                  emit ONCE per source article only when the article explicitly says the AI system interacts with, affects, or is exposed to natural persons (e.g. Articles 26(11), 50)

══ EXTRACTION RULES ══

1. SUBTYPE ANCHOR TABLE — for the following articles you MUST use the indicated subtype, NOT the parent type:
     Article 53(1)(a)–(d)   → GeneralGPAIObligation       (NOT GPAIObligation)
     Article 55(1)(a),(b),(d) → SystemicRiskGPAIObligation
     Article 55(1)(c)       → GPAISystemicRiskIncidentReport (NOT SystemicRiskGPAIObligation — this is the incident-reporting clause)
     Article 26(5)          → DeployerIncidentReport      (NOT IncidentReportingObligation)
     Article 73 (any clause) → ProviderIncidentReport     (NOT IncidentReportingObligation)
     Article 99             → EnforcementPower
     Article 65, 74         → InvestigativePower
     Article 56, 66, 67     → AdvisoryPower
   These articles produce predictable subtype mismatches if you go on intuition. Apply the table.

2. SUBTYPE PRECISION (other articles)
   Always use the most specific subtype available. If the article describes the
   Annex VI internal control procedure, use "InternalControlObligation", not
   "ConformityAssessmentObligation". Use parent types only when the article
   genuinely talks about the parent in the abstract.

3. ONE INSTANCE PER DISTINCT DUTY/POWER/CONDITION/ENTITY
   If Article 16 lists five separate provider duties (a)-(e), emit FIVE
   obligation instances, each with a distinct uri_suffix and a paragraph_ref
   pointing at the specific sub-paragraph. Don't merge them into one.

4. URI SUFFIX RULES
   - lowercase ASCII, underscores only
   - include the article number to keep it unique, e.g. "conformity_assessment_obligation_art43"
   - for sub-items use the list label, e.g. "deployer_incident_report_art26_5"

5. CARDINALITY CAP — AIRegulatorySandbox
   Emit AT MOST ONE AIRegulatorySandbox instance per article. The regulatory
   sandbox is a single concept the article describes; do not mint a separate
   instance per sub-paragraph. If you find yourself about to emit a second
   sandbox in the same article, stop — emit conditions on the first one
   instead.

6. SUMMARY REQUIREMENT
   Every instance MUST have a summary that is at least one sentence drawn from
   the source text. Do NOT copy the entire article — summarise the specific
   duty/power/condition/entity in your own words OR with a short faithful
   excerpt of the relevant clause.

7. NEGATIVE PROHIBITION LIST — DO NOT EMIT THESE TYPES
   The following types are handled by the rule-based extraction layer.
   Do NOT emit them, even if you see content that would fit:
     - "ProhibitedPractice"     (handled from Article 5 by rule-based)
     - "TechnicalDocumentation" (handled from Annex IV by rule-based)
     - "DocumentationComponent" (handled from Annex IV by rule-based)
     - "RegistrationField"      (handled from Annex VIII by rule-based)
     - "TestingPlanField"       (handled from Annex IX by rule-based)
     - "ConformityAssessmentStep" (handled from Annex VI/VII by rule-based)
     - "CEMarkingComponent"     (out of scope for now)
     - "AreaOfApplication"      (handled from Annex III by rule-based)
     - "RiskControl"            (handled from Article 14 by rule-based)
     - "Requirement"            (handled from Article 31 by rule-based)
   Also do NOT emit ANY of these structural / anchor types:
     - "Article", "Annex", "Paragraph"
     - "Provider", "Deployer", "AIOperator", "AISystem", "HighRiskAISystem"
     - "GeneralPurposeAIModel", "GPAI Model"
     - "AIOffice", "MarketSurveillanceAuthority"
     - "ConformityAssessmentBody", "NotifiedBody"

8. SCOPE PER ARTICLE
   Most articles will produce 0-8 instances. Procedural / definitional /
   delegation-of-power articles often produce nothing — that is fine, return
   {"instances": []}.

9. JSON ONLY
   Output VALID JSON ONLY. No comments, no trailing commas, no markdown fences.

══ CQ MAP (use for cq_targets field) ══
  CQ1   high-risk AI systems by sector    → emit when type=AreaOfApplication (rule layer handles)
  CQ2   provider obligations              → emit for any provider obligation
  CQ3   prohibited practices              → rule layer handles
  CQ4   transparency obligations          → emit for TransparencyObligation
  CQ5   GPAI obligations                  → emit for GeneralGPAIObligation, SystemicRiskGPAIObligation
  CQ6   deployer obligations              → emit for any deployer obligation
  CQ7   AI Office powers                  → emit for any Power instance
  CQ8   technical documentation           → rule layer handles
  CQ9   conditions on prohibited practices → emit for conditions in Article 5
  CQ10  risk controls (Article 14)        → rule layer handles
  LLM1  high-risk providers/obligations   → emit for provider obligations on high-risk articles
  LLM2  conformity assessment             → emit for ConformityAssessmentObligation, InternalControlObligation, ThirdPartyAssessmentObligation
  LLM3  CE marking                        → emit for CEMarking
  LLM4  enforcement / fines               → emit for EnforcementPower
  LLM5  sandbox conditions                → emit for conditions in Article 57-63 + the AIRegulatorySandbox itself
  LLM6  GPAI systemic risk criteria       → emit for conditions in Article 51
  LLM7  systemic-risk incident reporting  → emit for GPAISystemicRiskIncidentReport
  LLM8  SME support measures              → emit for SupportMeasureObligation
  LLM9  necessity/proportionality conditions → emit for NecessityCondition, ProportionalityCondition
  LLM10 incident reports + deadlines      → emit for ProviderIncidentReport, DeployerIncidentReport
"""


def build_instance_prompt(article: dict) -> str:
    """Build the user message for an article-extraction call."""
    return (
        f"Article {article['article_number']} — {article.get('title', '')}\n\n"
        f"{article['text']}\n\n"
        "Extract instances as a JSON object with key 'instances'. "
        "If the article contains nothing extractable from the allowed types, "
        "return {\"instances\": []}."
    )


def build_annex_instance_prompt(annex: dict) -> str:
    """Build the user message for an annex-extraction call."""
    return (
        f"Annex {annex['annex_number']} — {annex.get('title', '')}\n\n"
        f"{annex['text']}\n\n"
        "Extract instances as a JSON object with key 'instances'. "
        "REMINDER: annex content (technical documentation components, "
        "registration fields, conformity assessment steps, prohibited "
        "practices, sectors) is handled by the rule-based extraction layer. "
        "Only emit instances of types NOT on the negative prohibition list. "
        "Most annexes will produce {\"instances\": []}."
    )


# LLM call helper

def call_llm(system: str, user: str, label: str) -> dict:
    """Call the OpenAI API and parse a single JSON object from the response."""
    last_err = None
    text = ""
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
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
            last_err = f"JSONDecodeError: {e}; response head: {text[:200]!r}"
            print(f"    [{label}] attempt {attempt}: bad JSON, retrying...")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"    [{label}] attempt {attempt}: {last_err}, retrying...")
        time.sleep(RETRY_BACKOFF * attempt)
    print(f"    [{label}] FAILED after {RETRY_LIMIT} attempts: {last_err}")
    return {}

# Helpers

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalise_instance_uri(raw: str, source_tag: str) -> str:
    """Make a uri_suffix safe and source-stamped."""
    suffix = slugify(raw)
    if not suffix:
        suffix = "instance"
    if source_tag not in suffix:
        suffix = f"{suffix}_{source_tag}"
    return suffix


def normalise_cq_targets(raw) -> list[str]:
    """Coerce LLM cq_targets into a clean list of strings."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        item = item.strip().upper().replace(" ", "")
        if re.fullmatch(r"(?:CQ|LLM)\d+", item):
            out.append(item)
    return out


def normalise_evidence(raw) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    return raw.strip()[:200]


# Single pass over articles + annexes (with sandbox cardinality cap)

def run_extraction(articles: list[dict], annexes: list[dict]) -> list[dict]:
    """One pass over every article and every annex."""
    print("\n=== Single-pass instance extraction ===")
    all_instances: list[dict] = []

    # Articles 
    for i, article in enumerate(articles, 1):
        art_num = article["article_number"]
        source_tag = f"art{art_num}"
        title_preview = (article.get("title") or "")[:60]
        print(f"  [{i:>3}/{len(articles)}] Article {art_num}: {title_preview}")
        result = call_llm(
            INSTANCE_SYSTEM_PROMPT,
            build_instance_prompt(article),
            label=f"art_{art_num}",
        )
        # Cardinality cap: at most one AIRegulatorySandbox per article
        sandbox_seen = False
        for inst in result.get("instances", []):
            if not isinstance(inst, dict):
                continue
            type_str = (inst.get("type") or "").strip()
            if type_str == "AIRegulatorySandbox":
                if sandbox_seen:
                    continue
                sandbox_seen = True
            uri_suffix = normalise_instance_uri(
                inst.get("uri_suffix", ""), source_tag
            )
            all_instances.append({
                "uri_suffix":    uri_suffix,
                "type":          type_str,
                "summary":       (inst.get("summary") or "").strip(),
                "paragraph_ref": inst.get("paragraph_ref"),
                "source_article": art_num,
                "source_kind":    "article",
                "cq_targets":    normalise_cq_targets(inst.get("cq_targets")),
                "evidence_text": normalise_evidence(inst.get("evidence_text")),
            })

    # Annexes (mostly empty after Phase 2 narrowing)
    for i, annex in enumerate(annexes, 1):
        annex_num = annex.get("annex_number")
        if not annex_num:
            continue
        source_tag = f"ann{str(annex_num).lower()}"
        title_preview = (annex.get("title") or "")[:60]
        print(f"  [{i:>3}/{len(annexes)}] Annex {annex_num}: {title_preview}")
        result = call_llm(
            INSTANCE_SYSTEM_PROMPT,
            build_annex_instance_prompt(annex),
            label=f"annex_{annex_num}",
        )
        for inst in result.get("instances", []):
            if not isinstance(inst, dict):
                continue
            uri_suffix = normalise_instance_uri(
                inst.get("uri_suffix", ""), source_tag
            )
            all_instances.append({
                "uri_suffix":    uri_suffix,
                "type":          (inst.get("type") or "").strip(),
                "summary":       (inst.get("summary") or "").strip(),
                "paragraph_ref": inst.get("paragraph_ref"),
                "source_article": f"annex_{annex_num}",
                "source_kind":    "annex",
                "cq_targets":    normalise_cq_targets(inst.get("cq_targets")),
                "evidence_text": normalise_evidence(inst.get("evidence_text")),
            })

    print(f"  Total instances extracted: {len(all_instances)}")
    return all_instances

# Main

def main() -> None:
    print(f"Loading {INPUT_PATH}")
    with open(INPUT_PATH, encoding="utf-8") as f:
        payload = json.load(f)

    articles = payload["articles"]
    annexes = payload.get("annexes", [])
    print(f"  Articles: {len(articles)}")
    print(f"  Annexes:  {len(annexes)}")

    instances = run_extraction(articles, annexes)

    # Type breakdown for visibility
    type_counts: dict[str, int] = {}
    for inst in instances:
        t = inst["type"] or "(empty)"
        type_counts[t] = type_counts.get(t, 0) + 1

    output = {
        "source": "EUR-Lex (LLM extraction)",
        "model": MODEL,
        "input_path": INPUT_PATH,
        "summary": {
            "total_articles": len(articles),
            "total_annexes": len(annexes),
            "total_instances": len(instances),
            "type_breakdown": type_counts,
        },
        "instances": instances,
    }

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\n=== Done ===")
    print(f"  Total instances: {len(instances)}")
    print("  Top 10 types:")
    for t, n in sorted(type_counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>4}  {t}")
    print(f"  Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()