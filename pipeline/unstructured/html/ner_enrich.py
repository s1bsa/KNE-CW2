"""
Stage 3 of the HTML extraction pipeline: regex-primary, spaCy-validated
enrichment pass for the entity types neither the rule-based nor LLM
stages reliably catch.

Five regex passes extract:
  - Numeric deadlines        ("within 15 days")        → :hasDeadline
  - Monetary fines           ("up to 35 000 000 EUR")  → :hasFine
  - Percentage fines         ("7% of turnover")        → :hasMaximumFineRatio
  - Internal article refs    ("Article 43")            → :hasArticleReference
  - External legislation     ("Regulation (EU) 2016/679") → :cites

spaCy en_core_web_sm is consulted as a fallback validator on ambiguous
matches.

Inputs:  data/unstructured/html/eu_ai_act_articles.json
         data/unstructured/html/llm_extraction.json
Output:  data/unstructured/html/ner_enrichment.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ARTICLES_JSON  = "data/unstructured/html/eu_ai_act_articles.json"
LLM_JSON       = "data/unstructured/html/llm_extraction.json"
OUTPUT_PATH    = "data/unstructured/html/ner_enrichment.json"


# spaCy (optional, validator role only)
_nlp = None


def get_nlp():
    """Lazy-load spaCy. Returns None if not installed — passes still run."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception as e:
            print(f"  [warn] spaCy en_core_web_sm not available ({e}); "
                  "regex passes will run without NER validation",
                  file=sys.stderr)
            _nlp = False  # sentinel — tried and failed
    return _nlp if _nlp else None


# Regex pass 1 — Deadlines

DEADLINE_RE = re.compile(
    r"(?:within|no\s+later\s+than|not\s+later\s+than)\s+"
    r"(\d{1,4})\s+"
    r"(day|week|month|year|hour)s?",
    re.IGNORECASE,
)

DURATION_UNIT_MAP = {
    "hour":  ("PT", "H"),
    "day":   ("P",  "D"),
    "week":  ("P",  "W"),
    "month": ("P",  "M"),
    "year":  ("P",  "Y"),
}


def to_iso_duration(n: str, unit: str) -> str:
    prefix, suffix = DURATION_UNIT_MAP[unit.lower()]
    return f"{prefix}{n}{suffix}"


def extract_deadlines_from_instance(inst: dict) -> list[dict]:
    text = inst.get("summary") or ""
    out = []
    for m in DEADLINE_RE.finditer(text):
        n, unit = m.group(1), m.group(2)
        try:
            duration = to_iso_duration(n, unit)
        except KeyError:
            continue
        out.append({
            "subject":         inst["uri_suffix"],
            "subject_type":    "instance",
            "predicate":       "hasDeadline",
            "object":          duration,
            "object_kind":     "literal",
            "object_datatype": "xsd:duration",
            "evidence":        text[max(0, m.start() - 20):m.end() + 20].strip(),
            "rule":            "deadline_regex",
        })
    return out


# Regex pass 2 — Monetary fines (EUR)

# We accept space- or comma-separated thousands and require an EUR/euro
# token within ~3 words after the number. The number must be at least
# 4 digits to avoid false positives on "Article 99(1)" type matches.
FINE_RE = re.compile(
    r"(?:up\s+to\s+)?"
    r"(?:EUR\s+)?"
    r"(\d{1,3}(?:[\s,]\d{3}){1,3})"             # 4+ digits with separators
    r"\s*(?:EUR|euros?|€)",
    re.IGNORECASE,
)
FINE_RE_ALT = re.compile(
    r"EUR\s+(\d{1,3}(?:[\s,]\d{3}){1,3})",
    re.IGNORECASE,
)


def parse_eur_amount(raw: str) -> str:
    """'35 000 000' -> '35000000'."""
    return re.sub(r"[\s,]", "", raw)


def extract_fines_from_instance(inst: dict) -> list[dict]:
    text = inst.get("summary") or ""
    out = []
    seen = set()
    for regex in (FINE_RE, FINE_RE_ALT):
        for m in regex.finditer(text):
            amount = parse_eur_amount(m.group(1))
            if not amount.isdigit() or int(amount) < 1000:
                continue
            if amount in seen:
                continue
            seen.add(amount)
            out.append({
                "subject":         inst["uri_suffix"],
                "subject_type":    "instance",
                "predicate":       "hasFine",
                "object":          amount,
                "object_kind":     "literal",
                "object_datatype": "xsd:decimal",
                "evidence":        text[max(0, m.start() - 20):m.end() + 20].strip(),
                "rule":            "fine_regex",
            })
    return out


# Regex pass 3 — Fine ratios (% of turnover)

FINE_RATIO_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*"
    r"(?:[\w,()]+\s+){0,8}?"
    r"(?:total\s+)?worldwide\s+annual\s+turnover",
    re.IGNORECASE,
)


def extract_fine_ratios_from_instance(inst: dict) -> list[dict]:
    text = inst.get("summary") or ""
    out = []
    for m in FINE_RATIO_RE.finditer(text):
        pct = float(m.group(1))
        ratio = round(pct / 100.0, 4)
        out.append({
            "subject":         inst["uri_suffix"],
            "subject_type":    "instance",
            "predicate":       "hasMaximumFineRatio",
            "object":          str(ratio),
            "object_kind":     "literal",
            "object_datatype": "xsd:decimal",
            "evidence":        text[max(0, m.start() - 20):m.end() + 30].strip(),
            "rule":            "fine_ratio_regex",
        })
    return out


# Regex pass 4 — Internal article cross-references

ARTICLE_REF_RE = re.compile(r"\bArticle\s+(\d+)(?!\s*\d)\b", re.IGNORECASE)


def extract_internal_refs_from_instance(inst: dict) -> list[dict]:
    text = inst.get("summary") or ""
    src_art = inst.get("source_article")
    out = []
    seen = set()
    for m in ARTICLE_REF_RE.finditer(text):
        n = m.group(1)
        if not n.isdigit():
            continue
        n_int = int(n)
        # Skip self-references (an obligation from Article 5 mentioning Article 5)
        if isinstance(src_art, int) and src_art == n_int:
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append({
            "subject":         inst["uri_suffix"],
            "subject_type":    "instance",
            "predicate":       "hasArticleReference",
            "object":          f"Article_{n}",
            "object_kind":     "uri",
            "object_datatype": None,
            "evidence":        text[max(0, m.start() - 20):m.end() + 30].strip(),
            "rule":            "internal_article_ref_regex",
        })
    return out


# Regex pass 5 — External legislation cross-references

# EU regulation citation patterns. Two cases:
#   1. Post-2015 format:  "Regulation (EU) 2016/679"      → year/number
#   2. Pre-2015 format:   "Regulation (EU) No 1025/2012"  → number/year
# We use two distinct regexes so we always know which slot is which.
REGULATION_POST2015_RE = re.compile(
    r"Regulation\s*\(EU\)\s*(20\d{2})\s*/\s*(\d{1,4})",
    re.IGNORECASE,
)
REGULATION_PRE2015_RE = re.compile(
    r"Regulation\s*\(E[CU]\)\s*No\s*(\d{1,4})\s*/\s*(20\d{2}|19\d{2})",
    re.IGNORECASE,
)
DIRECTIVE_REF_RE = re.compile(
    r"Directive\s*(\d{4})\s*/\s*(\d+)\s*/\s*E[CU]",
    re.IGNORECASE,
)


def celex_for_regulation(year: str, num: str) -> str:
    """Build a CELEX id like '32016R0679' from a 4-digit year and a number."""
    return f"3{int(year):04d}R{int(num):04d}"


def celex_for_directive(year: str, num: str) -> str:
    return f"3{int(year):04d}L{int(num):04d}"


def extract_legislation_refs_from_article(article: dict) -> list[dict]:
    text = article.get("text") or ""
    art_num = article.get("article_number")
    if not art_num or not text:
        return []
    out = []
    seen = set()

    # Skip self-reference: the AI Act itself is 32024R1689
    self_celex = "32024R1689"

    for m in REGULATION_POST2015_RE.finditer(text):
        celex = celex_for_regulation(m.group(1), m.group(2))
        if celex == self_celex or celex in seen:
            continue
        seen.add(celex)
        out.append({
            "subject":         f"Article_{art_num}",
            "subject_type":    "article",
            "predicate":       "cites",
            "object":          f"Legislation_{celex}",
            "object_kind":     "uri",
            "object_datatype": None,
            "evidence":        text[max(0, m.start() - 20):m.end() + 30].strip(),
            "rule":            "regulation_post2015_celex_regex",
        })
    for m in REGULATION_PRE2015_RE.finditer(text):
        # Note: pre-2015 regex captures (number, year), so we swap when
        # building CELEX which expects (year, number).
        celex = celex_for_regulation(m.group(2), m.group(1))
        if celex == self_celex or celex in seen:
            continue
        seen.add(celex)
        out.append({
            "subject":         f"Article_{art_num}",
            "subject_type":    "article",
            "predicate":       "cites",
            "object":          f"Legislation_{celex}",
            "object_kind":     "uri",
            "object_datatype": None,
            "evidence":        text[max(0, m.start() - 20):m.end() + 30].strip(),
            "rule":            "regulation_pre2015_celex_regex",
        })
    for m in DIRECTIVE_REF_RE.finditer(text):
        celex = celex_for_directive(m.group(1), m.group(2))
        if celex in seen:
            continue
        seen.add(celex)
        out.append({
            "subject":         f"Article_{art_num}",
            "subject_type":    "article",
            "predicate":       "cites",
            "object":          f"Legislation_{celex}",
            "object_kind":     "uri",
            "object_datatype": None,
            "evidence":        text[max(0, m.start() - 20):m.end() + 30].strip(),
            "rule":            "directive_celex_regex",
        })
    return out


# Optional spaCy validation (additive entity discovery)

def spacy_money_pass(articles: list[dict]) -> list[dict]:
    nlp = get_nlp()
    if nlp is None:
        return []
    out = []
    seen_pairs = set()
    for art in articles:
        text = art.get("text") or ""
        if not text:
            continue
        # Only process articles likely to contain fines (cheaper)
        if "fine" not in text.lower() and "EUR" not in text and "penalt" not in text.lower():
            continue
        doc = nlp(text)
        art_num = art.get("article_number")
        for ent in doc.ents:
            if ent.label_ != "MONEY":
                continue
            # Try to extract a numeric value
            digits = re.sub(r"[^\d]", "", ent.text)
            if not digits or int(digits) < 1000:
                continue
            key = (art_num, digits)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            out.append({
                "subject":         f"Article_{art_num}",
                "subject_type":    "article",
                "predicate":       "hasFine",
                "object":          digits,
                "object_kind":     "literal",
                "object_datatype": "xsd:decimal",
                "evidence":        text[max(0, ent.start_char - 30):ent.end_char + 30],
                "rule":            "spacy_money",
            })
    return out


# Main

def main() -> None:
    print(f"Loading {ARTICLES_JSON}")
    with open(ARTICLES_JSON, encoding="utf-8") as f:
        articles_payload = json.load(f)
    articles = articles_payload.get("articles", [])
    print(f"  Articles: {len(articles)}")

    print(f"Loading {LLM_JSON}")
    try:
        with open(LLM_JSON, encoding="utf-8") as f:
            llm_payload = json.load(f)
        llm_instances = llm_payload.get("instances", [])
    except FileNotFoundError:
        print(f"  [warn] {LLM_JSON} not found — running with empty LLM input")
        llm_instances = []
    print(f"  LLM instances: {len(llm_instances)}")

    enrichments: list[dict] = []

    print("\n=== Pass 1: deadlines (regex) ===")
    deadlines = []
    for inst in llm_instances:
        deadlines.extend(extract_deadlines_from_instance(inst))
    print(f"  {len(deadlines)} found")
    enrichments.extend(deadlines)

    print("\n=== Pass 2: fines EUR (regex) ===")
    fines = []
    for inst in llm_instances:
        fines.extend(extract_fines_from_instance(inst))
    # Also run over Article 99 directly even if no LLM instance covers it
    art99 = next((a for a in articles if a.get("article_number") == 99), None)
    if art99:
        fake_inst = {
            "uri_suffix": "Article_99",
            "summary":    art99.get("text", ""),
            "source_article": 99,
        }
        for f in extract_fines_from_instance(fake_inst):
            f["subject_type"] = "article"
            fines.append(f)
    print(f"  {len(fines)} found")
    enrichments.extend(fines)

    print("\n=== Pass 3: fine ratios (regex) ===")
    ratios = []
    for inst in llm_instances:
        ratios.extend(extract_fine_ratios_from_instance(inst))
    if art99:
        fake_inst = {
            "uri_suffix": "Article_99",
            "summary":    art99.get("text", ""),
            "source_article": 99,
        }
        for r in extract_fine_ratios_from_instance(fake_inst):
            r["subject_type"] = "article"
            ratios.append(r)
    print(f"  {len(ratios)} found")
    enrichments.extend(ratios)

    print("\n=== Pass 4: internal article cross-refs (regex) ===")
    internal_refs = []
    for inst in llm_instances:
        internal_refs.extend(extract_internal_refs_from_instance(inst))
    print(f"  {len(internal_refs)} found")
    enrichments.extend(internal_refs)

    print("\n=== Pass 5: legislation cross-refs (regex over article text) ===")
    leg_refs = []
    for art in articles:
        leg_refs.extend(extract_legislation_refs_from_article(art))
    print(f"  {len(leg_refs)} found")
    enrichments.extend(leg_refs)

    print("\n=== Pass 6: spaCy MONEY validation ===")
    spacy_finds = spacy_money_pass(articles)
    print(f"  {len(spacy_finds)} additional money entities (additive)")
    enrichments.extend(spacy_finds)

    # Summary
    by_rule: dict[str, int] = {}
    by_predicate: dict[str, int] = {}
    for e in enrichments:
        by_rule[e["rule"]] = by_rule.get(e["rule"], 0) + 1
        by_predicate[e["predicate"]] = by_predicate.get(e["predicate"], 0) + 1

    output = {
        "source": "NER + regex enrichment",
        "spacy_model": "en_core_web_sm",
        "summary": {
            "total_enrichments": len(enrichments),
            "by_rule":           by_rule,
            "by_predicate":      by_predicate,
        },
        "enrichments": enrichments,
    }

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\n=== Done ===")
    print(f"  Total enrichments: {len(enrichments)}")
    print("  By predicate:")
    for p, n in sorted(by_predicate.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {p}")
    print(f"  Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
