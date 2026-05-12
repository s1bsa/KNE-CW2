"""
Stage 1 of the HTML extraction pipeline: deterministic rule-based extraction
of ontology-aligned instances from enumerated content (annex bullets and
article list items). Pure Python, zero LLM cost.

Extracts:
  - Annex IV   → DocumentationComponent
  - Annex VIII → RegistrationField
  - Annex IX   → TestingPlanField
  - Annex VII  → ConformityAssessmentStep
  - Annex VI   → ConformityAssessmentStep
  - Annex III  → AreaOfApplication
  - Article 5  → ProhibitedPractice
  - Article 14 → RiskControl
  - Article 31 → Requirement (12 named individuals)

Input:  data/unstructured/html/eu_ai_act_articles.json
Output: data/unstructured/html/rule_extraction.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

INPUT_PATH  = "data/unstructured/html/eu_ai_act_articles.json"
OUTPUT_PATH = "data/unstructured/html/rule_extraction.json"

# Helpers

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def truncate(text: str, n: int = 400) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"


def annex_ref_to_slug(ref: str) -> str:
    """'Annex IV(1)(a)' -> 'anniv_1_a'."""
    if not ref:
        return "unknown"
    s = ref.replace("Annex ", "ann").lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def find_annex(annexes: list[dict], roman: str) -> dict | None:
    return next((a for a in annexes if str(a.get("annex_number", "")).upper() == roman), None)


def find_article(articles: list[dict], num: int) -> dict | None:
    return next((a for a in articles if a.get("article_number") == num), None)


# Synthesised content_items fallback for annexes

def synthesise_annex_content_items(annex: dict) -> list[dict]:
    """Best-effort regex extraction of numbered items + lettered sub-items
    from a flat annex text. Returns a list shaped like parser content_items."""
    text = (annex or {}).get("text", "") or ""
    if not text:
        return []
    annex_num = str(annex.get("annex_number", "")).upper()

    # Split on numbered items "1. ", "2. ", etc. — keeping the number
    # We require a leading whitespace to avoid spurious matches like "11."
    parts = re.split(r"(?:^|\s)(\d+)\.\s+", text)
    # parts is [preamble, "1", "<item 1 text>", "2", "<item 2 text>", ...]
    items = []
    if len(parts) <= 1:
        return []

    section = None
    section_match = re.search(r"Section\s+([A-Z])", parts[0])
    if section_match:
        section = section_match.group(1).upper()

    # Walk pairs (number, body)
    pairs = list(zip(parts[1::2], parts[2::2]))
    for num, body in pairs:
        # Detect a section heading inside this item's body — Annex VIII has
        # "Section B" appear partway through.
        sm = re.search(r"Section\s+([A-Z])", body)
        if sm:
            section_in_body = sm.group(1).upper()
            # If we hit a new section, the rest of the body belongs to it.
            # We split and treat the pre-section part as the current item.
            head, _, tail = body.partition(sm.group(0))
            body = head
            section = section_in_body
            # The tail will resume numbering at "1." again, which our split
            # already handled — but we may have lost it. Synthesised pass
            # is a fallback only; the parser should be populating content_items.

        # Build the top-level numbered item
        ref = f"Annex {annex_num}"
        if section:
            ref += f"({section})"
        ref += f"({num})"
        items.append({
            "section": section,
            "paragraph_number": num,
            "list_label": None,
            "reference": ref,
            "text": f"{num}. {body.strip()}",
        })

        # Lettered sub-items inside this item's body: "(a) ... (b) ... (c) ..."
        sub_parts = re.split(r"\(([a-z])\)\s+", body)
        if len(sub_parts) > 1:
            sub_pairs = list(zip(sub_parts[1::2], sub_parts[2::2]))
            for letter, sub_body in sub_pairs:
                sub_ref = f"Annex {annex_num}"
                if section:
                    sub_ref += f"({section})"
                sub_ref += f"({num})({letter})"
                # Cut sub_body at the next sentence-ending semicolon, which
                # in EU legal style separates sub-items.
                sub_body_cut = re.split(r";\s*", sub_body, maxsplit=1)[0]
                items.append({
                    "section": section,
                    "paragraph_number": num,
                    "list_label": letter,
                    "reference": sub_ref,
                    "text": f"({letter}) {sub_body_cut.strip()}",
                })
    return items


def get_annex_content_items(annex: dict) -> list[dict]:
    """Return content_items, synthesising from text if the parser didn't."""
    items = annex.get("content_items") or []
    if items:
        return items
    return synthesise_annex_content_items(annex)


# Extractor: Annex IV — DocumentationComponent

def extract_annex_iv_components(annexes: list[dict]) -> list[dict]:
    annex_iv = find_annex(annexes, "IV")
    if not annex_iv:
        return []
    out = []
    seen_refs = set()
    for ci in get_annex_content_items(annex_iv):
        ref = ci.get("reference")
        text = (ci.get("text") or "").strip()
        if not ref or not text:
            continue
        if text.lower().startswith("section "):
            continue
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        out.append({
            "uri_suffix":      f"documentation_component_{annex_ref_to_slug(ref)}",
            "type":            "DocumentationComponent",
            "summary":         truncate(text),
            "paragraph_ref":   ref,
            "parent_artefact": "TechnicalDocumentation_Annex_IV",
            "source_kind":     "rule",
            "rule_id":         "annex_iv_components",
        })
    return out

# Extractor: Annex VIII — RegistrationField

def extract_annex_viii_fields(annexes: list[dict]) -> list[dict]:
    annex = find_annex(annexes, "VIII")
    if not annex:
        return []
    out = []
    seen_refs = set()
    for ci in get_annex_content_items(annex):
        ref = ci.get("reference")
        text = (ci.get("text") or "").strip()
        if not ref or not text:
            continue
        # Skip pure section heading paragraphs ("Section A — ...")
        if text.lower().startswith("section "):
            continue
        # Skip preamble sentences (no number, no letter, no useful structure)
        # but keep them if they contain genuine content. Heuristic: must have
        # at least 20 chars of text after stripping the marker prefix.
        if (ci.get("paragraph_number") is None
                and ci.get("list_label") is None
                and len(text) < 30):
            continue
        # Dedupe by reference (prevents the synthetic fallback from emitting
        # duplicates when the parser already populated content_items).
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        out.append({
            "uri_suffix":      f"registration_field_{annex_ref_to_slug(ref)}",
            "type":            "RegistrationField",
            "summary":         truncate(text),
            "paragraph_ref":   ref,
            "parent_artefact": "RegistrationRecord_Annex_VIII",
            "source_kind":     "rule",
            "rule_id":         "annex_viii_fields",
        })
    return out


# Extractor: Annex IX — TestingPlanField

def extract_annex_ix_fields(annexes: list[dict]) -> list[dict]:
    annex = find_annex(annexes, "IX")
    if not annex:
        return []
    out = []
    seen_refs = set()
    for ci in get_annex_content_items(annex):
        ref = ci.get("reference")
        text = (ci.get("text") or "").strip()
        if not ref or not text:
            continue
        if text.lower().startswith("section "):
            continue
        if (ci.get("paragraph_number") is None
                and ci.get("list_label") is None
                and len(text) < 30):
            continue
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        out.append({
            "uri_suffix":      f"testing_plan_field_{annex_ref_to_slug(ref)}",
            "type":            "TestingPlanField",
            "summary":         truncate(text),
            "paragraph_ref":   ref,
            "parent_artefact": "TestingPlan_Annex_IX",
            "source_kind":     "rule",
            "rule_id":         "annex_ix_fields",
        })
    return out

# Extractor: Annex VII — ConformityAssessmentStep (third-party)

def extract_annex_vii_steps(annexes: list[dict]) -> list[dict]:
    annex = find_annex(annexes, "VII")
    if not annex:
        return []
    out = []
    seen_refs = set()
    for ci in get_annex_content_items(annex):
        ref = ci.get("reference")
        text = (ci.get("text") or "").strip()
        if not ref or not text:
            continue
        if text.lower().startswith("section "):
            continue
        if (ci.get("paragraph_number") is None
                and ci.get("list_label") is None
                and len(text) < 30):
            continue
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        out.append({
            "uri_suffix":      f"conformity_step_{annex_ref_to_slug(ref)}",
            "type":            "ConformityAssessmentStep",
            "summary":         truncate(text),
            "paragraph_ref":   ref,
            "parent_artefact": "ThirdPartyAssessment_Annex_VII",
            "source_kind":     "rule",
            "rule_id":         "annex_vii_steps",
        })
    return out

# Extractor: Annex VI — ConformityAssessmentStep (internal control)

def extract_annex_vi_steps(annexes: list[dict]) -> list[dict]:
    annex = find_annex(annexes, "VI")
    if not annex:
        return []
    out = []
    seen_refs = set()
    for ci in get_annex_content_items(annex):
        ref = ci.get("reference")
        text = (ci.get("text") or "").strip()
        if not ref or not text:
            continue
        if text.lower().startswith("section "):
            continue
        if (ci.get("paragraph_number") is None
                and ci.get("list_label") is None
                and len(text) < 30):
            continue
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        out.append({
            "uri_suffix":      f"conformity_step_{annex_ref_to_slug(ref)}",
            "type":            "ConformityAssessmentStep",
            "summary":         truncate(text),
            "paragraph_ref":   ref,
            "parent_artefact": "InternalControl_Annex_VI",
            "source_kind":     "rule",
            "rule_id":         "annex_vi_steps",
        })
    return out

# Extractor: Annex III sectors → AreaOfApplication (× 8)

ANNEX_III_SECTORS = [
    ("biometrics", "Biometrics",
     "Remote biometric identification, biometric categorisation by sensitive "
     "attributes, and emotion recognition systems."),
    ("critical_infrastructure", "Critical infrastructure",
     "Safety components in the management and operation of critical digital "
     "infrastructure, road traffic, and the supply of water, gas, heating and "
     "electricity."),
    ("education", "Education and vocational training",
     "AI used to determine access, admission, evaluation of learning outcomes, "
     "assessing appropriate level of education, or monitoring prohibited "
     "behaviour during tests."),
    ("employment", "Employment, workers management and access to self-employment",
     "Recruitment, selection, decisions affecting terms of work, promotion, "
     "termination, task allocation based on individual behaviour or traits, "
     "and monitoring/evaluation of performance."),
    ("essential_services", "Access to and enjoyment of essential private and public services",
     "Eligibility for public assistance benefits, creditworthiness evaluation, "
     "risk assessment and pricing in life and health insurance, and emergency "
     "call dispatch and triage."),
    ("law_enforcement", "Law enforcement",
     "Risk assessment of natural persons, polygraphs, evidence reliability "
     "assessment, profiling, and crime analytics."),
    ("migration", "Migration, asylum and border control management",
     "Polygraphs, risk assessments, examination of applications for asylum/visa/"
     "residence, and detection/recognition of natural persons at borders."),
    ("justice", "Administration of justice and democratic processes",
     "AI assisting judicial authorities in researching and interpreting facts "
     "and the law, and AI intended to influence the outcome of an election or "
     "voting behaviour."),
]


def extract_annex_iii_sectors() -> list[dict]:
    out = []
    for slug, label, summary in ANNEX_III_SECTORS:
        out.append({
            "uri_suffix":    f"area_of_application_{slug}",
            "type":          "AreaOfApplication",
            "label":         label,
            "summary":       summary,
            "paragraph_ref": "Annex III",
            "sector_slug":   slug,  # consumed by serialiser to mint paired HighRiskAISystem
            "source_kind":   "rule",
            "rule_id":       "annex_iii_sectors",
        })
    return out

# Extractor: Article 5 prohibited practices (a)–(h)

def extract_article_5_practices(articles: list[dict]) -> list[dict]:
    art5 = find_article(articles, 5)
    if not art5:
        return []
    out = []
    seen_labels: set[str] = set()
    valid_letters = set("abcdefgh")
    for ci in art5.get("content_items", []):
        if ci.get("paragraph_number") != "1":
            continue
        label = ci.get("list_label")
        if not label:
            continue
        if not (len(label) == 1 and label.isalpha() and label.lower() != "i"):
            continue
        if label.lower() not in valid_letters:
            continue
        if label in seen_labels:
            continue
        seen_labels.add(label)
        text = (ci.get("text") or "").strip()
        is_biometric = (label == "h")
        out.append({
            "uri_suffix":   f"prohibited_practice_art5_1_{label}",
            "type":         "ProhibitedPractice",
            "label":        f"Article 5(1)({label}) prohibited practice"
                            + (" — real-time remote biometric identification"
                               if is_biometric else ""),
            "summary":      truncate(text, 800),
            "paragraph_ref": ci.get("reference") or f"Article 5(1)({label})",
            "is_biometric": is_biometric,
            "source_kind":  "rule",
            "rule_id":      "article_5_practices",
        })
    return out

# Extractor: Article 14 risk controls (paragraph 4 sub-items)

def extract_article_14_risk_controls(articles: list[dict]) -> list[dict]:
    art14 = find_article(articles, 14)
    if not art14:
        return []
    out = []
    seen = set()
    for ci in art14.get("content_items", []):
        if ci.get("paragraph_number") != "4":
            continue
        label = ci.get("list_label")
        if not label or label in seen:
            continue
        if not (len(label) == 1 and label.isalpha()):
            continue
        seen.add(label)
        text = (ci.get("text") or "").strip()
        out.append({
            "uri_suffix":    f"risk_control_art14_4_{label}",
            "type":          "RiskControl",
            "summary":       truncate(text),
            "paragraph_ref": ci.get("reference") or f"Article 14(4)({label})",
            "source_kind":   "rule",
            "rule_id":       "article_14_risk_controls",
        })
    return out

# Extractor: Article 31 notified body requirements (TBox-driven)

NOTIFIED_BODY_REQUIREMENTS = [
    "OrganisationalRequirement",
    "QualityManagementRequirement",
    "ResourceRequirement",
    "ProcessRequirement",
    "CybersecurityRequirement",
    "IndependenceRequirement",
    "ObjectivityRequirement",
    "ImpartialityRequirement",
    "ProfessionalIntegrityRequirement",
    "CompetenceRequirement",
    "ConfidentialityRequirement",
    "LiabilityInsuranceRequirement",
]


def extract_notified_body_requirements() -> list[dict]:
    out = []
    for req_name in NOTIFIED_BODY_REQUIREMENTS:
        out.append({
            "uri_suffix":    req_name,  # already a TBox individual
            "type":          "Requirement",
            "paragraph_ref": "Article 31",
            "tbox_individual": True,    # flag for serialiser — do not re-type
            "source_kind":   "rule",
            "rule_id":       "notified_body_requirements",
        })
    return out

# Main

def main() -> None:
    print(f"Loading {INPUT_PATH}")
    with open(INPUT_PATH, encoding="utf-8") as f:
        payload = json.load(f)

    articles = payload.get("articles", [])
    annexes  = payload.get("annexes", [])
    print(f"  Articles: {len(articles)}")
    print(f"  Annexes:  {len(annexes)}")

    # Diagnostic: how many annexes have parser-populated content_items?
    populated = sum(1 for a in annexes if a.get("content_items"))
    print(f"  Annexes with content_items: {populated}/{len(annexes)}")
    if populated < len(annexes):
        print("  (synthesising fallback content_items via regex for the rest)")

    print("\n=== Running rule extractors ===")
    extractors = [
        ("annex_iv_components",        extract_annex_iv_components,    [annexes]),
        ("annex_vi_steps",             extract_annex_vi_steps,         [annexes]),
        ("annex_vii_steps",            extract_annex_vii_steps,        [annexes]),
        ("annex_viii_fields",          extract_annex_viii_fields,      [annexes]),
        ("annex_ix_fields",            extract_annex_ix_fields,        [annexes]),
        ("annex_iii_sectors",          extract_annex_iii_sectors,      []),
        ("article_5_practices",        extract_article_5_practices,    [articles]),
        ("article_14_risk_controls",   extract_article_14_risk_controls, [articles]),
        ("notified_body_requirements", extract_notified_body_requirements, []),
    ]

    all_instances = []
    summary = {}
    for name, fn, args in extractors:
        result = fn(*args)
        summary[name] = len(result)
        all_instances.extend(result)
        print(f"  {name:32} {len(result):>4} instances")

    print(f"\n  Total: {len(all_instances)}")

    # Type breakdown for visibility
    type_counts: dict[str, int] = {}
    for inst in all_instances:
        t = inst["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print("\n  Type breakdown:")
    for t, n in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {t}")

    output = {
        "source": "rule-based extraction",
        "input_path": INPUT_PATH,
        "summary": {
            "by_extractor": summary,
            "by_type":      type_counts,
            "total":        len(all_instances),
        },
        "instances": all_instances,
    }

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()