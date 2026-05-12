"""
Evaluates the NER quality of the live extraction pipeline against a
hand-built gold standard of 30 sentences sampled from Articles 3, 5, 10,
14, 26, 73, 99 and Annex III.

Benchmarks two extractors against the same gold standard:

  A) spaCy en_core_web_sm native NER (generic types: PERSON, ORG, GPE,
     DATE, MONEY, LAW, mapped onto our gold-standard entity types where
     possible).

  B) The regex pipeline reproduced from ner_enrich.py (legal-citation
     and numeric types: REGULATION_REF, LEGISLATION, DEADLINE, MONEY,
     PERCENT).

Computes per-entity-type and overall precision / recall / F1. The story
the report tells: spaCy alone catches the generic entity types; the
regex layer surgically catches the legal-citation patterns spaCy can't
detect; neither catches the AI_SYSTEM and STAKEHOLDER semantic types,
which justifies the third LLM extraction layer.

The gold standard is persisted to ner_gold_standard.json for
reproducibility.

Output: data/evaluation/ner_benchmark.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import spacy
except ImportError:
    print("ERROR: spacy not installed. Run: pip install spacy")
    sys.exit(1)


# Paths
EVAL_DIR         = "data/evaluation"
OUT_JSON         = os.path.join(EVAL_DIR, "ner_benchmark.json")
GOLD_OUT         = os.path.join(EVAL_DIR, "ner_gold_standard.json")


# Gold Standard — 30 sentences from the EU AI Act


GOLD_STANDARD = [
    # Article 3 (Definitions) 
    {
        "source": "Article 3(1)",
        "text": "'AI system' means a machine-based system that is designed to operate with varying levels of autonomy and that may exhibit adaptiveness after deployment.",
        "entities": [
            {"text": "AI system", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 3(3)",
        "text": "'provider' means a natural or legal person, public authority, agency or other body that develops an AI system or a general-purpose AI model or that has an AI system or a general-purpose AI model developed and places it on the market.",
        "entities": [
            {"text": "provider", "type": "STAKEHOLDER"},
            {"text": "AI system", "type": "AI_SYSTEM"},
            {"text": "general-purpose AI model", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 3(4)",
        "text": "'deployer' means a natural or legal person, public authority, agency or other body using an AI system under its authority except where the AI system is used in the course of a personal non-professional activity.",
        "entities": [
            {"text": "deployer", "type": "STAKEHOLDER"},
            {"text": "AI system", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 3(5)",
        "text": "'authorised representative' means any natural or legal person located or established in the Union who has received and accepted a written mandate from a provider of an AI system or a general-purpose AI model to perform the obligations and procedures established by this Regulation.",
        "entities": [
            {"text": "authorised representative", "type": "STAKEHOLDER"},
            {"text": "provider", "type": "STAKEHOLDER"},
            {"text": "AI system", "type": "AI_SYSTEM"},
            {"text": "general-purpose AI model", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 3(44)",
        "text": "'notified body' means a conformity assessment body notified in accordance with this Regulation and other relevant Union harmonisation legislation.",
        "entities": [
            {"text": "notified body", "type": "STAKEHOLDER"},
            {"text": "conformity assessment body", "type": "STAKEHOLDER"},
        ],
    },

    # Article 5 (Prohibited practices)
    {
        "source": "Article 5(1)(a)",
        "text": "The placing on the market, the putting into service or the use of an AI system that deploys subliminal techniques beyond a person's consciousness with the objective to or the effect of materially distorting a person's behaviour shall be prohibited.",
        "entities": [
            {"text": "AI system", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 5(1)(h)",
        "text": "The use of real-time remote biometric identification systems in publicly accessible spaces for the purposes of law enforcement shall be prohibited unless and in so far as such use is strictly necessary.",
        "entities": [
            {"text": "real-time remote biometric identification systems", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 5(2)",
        "text": "The use of real-time remote biometric identification systems referred to in paragraph 1, point (h) shall be deployed for the purposes listed in that point only to confirm the specifically targeted individual's identity.",
        "entities": [
            {"text": "real-time remote biometric identification systems", "type": "AI_SYSTEM"},
            {"text": "paragraph 1, point (h)", "type": "REGULATION_REF"},
        ],
    },

    # Article 6 (High-risk classification) 
    {
        "source": "Article 6(1)",
        "text": "An AI system shall be considered to be high-risk where it is intended to be used as a safety component of a product covered by the Union harmonisation legislation listed in Annex I.",
        "entities": [
            {"text": "AI system", "type": "AI_SYSTEM"},
            {"text": "high-risk", "type": "AI_SYSTEM"},
            {"text": "Annex I", "type": "REGULATION_REF"},
        ],
    },
    {
        "source": "Article 6(2)",
        "text": "In addition to the high-risk AI systems referred to in paragraph 1, AI systems referred to in Annex III shall also be considered high-risk.",
        "entities": [
            {"text": "high-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "AI systems", "type": "AI_SYSTEM"},
            {"text": "Annex III", "type": "REGULATION_REF"},
        ],
    },

    # Article 10 (Data governance) 
    {
        "source": "Article 10(1)",
        "text": "High-risk AI systems which make use of techniques involving the training of AI models with data shall be developed on the basis of training, validation and testing data sets that meet the quality criteria referred to in paragraphs 2 to 5.",
        "entities": [
            {"text": "High-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "AI models", "type": "AI_SYSTEM"},
            {"text": "paragraphs 2 to 5", "type": "REGULATION_REF"},
        ],
    },
    {
        "source": "Article 10(5)",
        "text": "To the extent that it is strictly necessary, providers of such systems are allowed to process special categories of personal data, subject to appropriate safeguards for the fundamental rights and freedoms of natural persons.",
        "entities": [
            {"text": "providers", "type": "STAKEHOLDER"},
        ],
    },

    # Article 14 (Human oversight) 
    {
        "source": "Article 14(1)",
        "text": "High-risk AI systems shall be designed and developed in such a way, including with appropriate human-machine interface tools, that they can be effectively overseen by natural persons during the period in which they are in use.",
        "entities": [
            {"text": "High-risk AI systems", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Article 14(4)",
        "text": "For the purpose of implementing paragraphs 1, 2 and 3, the high-risk AI system shall be provided to the deployer in such a way that natural persons to whom human oversight is assigned are enabled to properly understand the relevant capacities and limitations of the high-risk AI system.",
        "entities": [
            {"text": "paragraphs 1, 2 and 3", "type": "REGULATION_REF"},
            {"text": "high-risk AI system", "type": "AI_SYSTEM"},
            {"text": "deployer", "type": "STAKEHOLDER"},
        ],
    },

    # Article 26 (Deployer obligations) 
    {
        "source": "Article 26(1)",
        "text": "Deployers of high-risk AI systems shall take appropriate technical and organisational measures to ensure they use such systems in accordance with the instructions for use accompanying the systems, pursuant to paragraphs 3 and 6.",
        "entities": [
            {"text": "Deployers", "type": "STAKEHOLDER"},
            {"text": "high-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "paragraphs 3 and 6", "type": "REGULATION_REF"},
        ],
    },
    {
        "source": "Article 26(5)",
        "text": "Deployers of high-risk AI systems referred to in Annex III that make decisions or assist in making decisions related to natural persons shall inform the natural persons that they are subject to the use of the high-risk AI system.",
        "entities": [
            {"text": "Deployers", "type": "STAKEHOLDER"},
            {"text": "high-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "Annex III", "type": "REGULATION_REF"},
            {"text": "high-risk AI system", "type": "AI_SYSTEM"},
        ],
    },

    # Article 43 (Conformity assessment) 
    {
        "source": "Article 43(4)",
        "text": "High-risk AI systems that have already been subject to a conformity assessment procedure shall undergo a new conformity assessment procedure in the event of a substantial modification, regardless of whether the modified system is intended to be further distributed or continues to be used by the current deployer.",
        "entities": [
            {"text": "High-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "deployer", "type": "STAKEHOLDER"},
        ],
    },

    # Article 50 (Transparency obligations) 
    {
        "source": "Article 50(1)",
        "text": "Providers shall ensure that AI systems intended to interact directly with natural persons are designed and developed in such a way that the natural persons concerned are informed that they are interacting with an AI system.",
        "entities": [
            {"text": "Providers", "type": "STAKEHOLDER"},
            {"text": "AI systems", "type": "AI_SYSTEM"},
            {"text": "AI system", "type": "AI_SYSTEM"},
        ],
    },

    # Article 56 (Codes of practice) 
    {
        "source": "Article 56(1)",
        "text": "The AI Office shall encourage and facilitate the drawing up of codes of practice at Union level in order to contribute to the proper application of this Regulation, taking into account international approaches.",
        "entities": [
            {"text": "AI Office", "type": "STAKEHOLDER"},
        ],
    },

    # Article 73 (Reporting of serious incidents) 
    {
        "source": "Article 73(1)",
        "text": "Providers of high-risk AI systems placed on the Union market shall report any serious incident to the market surveillance authorities of the Member States where that incident occurred.",
        "entities": [
            {"text": "Providers", "type": "STAKEHOLDER"},
            {"text": "high-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "market surveillance authorities", "type": "STAKEHOLDER"},
        ],
    },
    {
        "source": "Article 73(2)",
        "text": "The report referred to in paragraph 1 shall be made immediately after the provider has established a causal link between the AI system and the serious incident or the reasonable likelihood of such a link, and, in any event, not later than 15 days after the provider becomes aware of the serious incident.",
        "entities": [
            {"text": "paragraph 1", "type": "REGULATION_REF"},
            {"text": "provider", "type": "STAKEHOLDER"},
            {"text": "AI system", "type": "AI_SYSTEM"},
            {"text": "15 days", "type": "DEADLINE"},
        ],
    },
    {
        "source": "Article 73(3)",
        "text": "In the event of a widespread infringement or a serious and irreversible disruption of critical infrastructure, the report referred to in paragraph 1 of this Article shall be provided immediately, and not later than 2 days after the provider becomes aware of that incident.",
        "entities": [
            {"text": "paragraph 1", "type": "REGULATION_REF"},
            {"text": "2 days", "type": "DEADLINE"},
            {"text": "provider", "type": "STAKEHOLDER"},
        ],
    },

    # Article 99 (Penalties) 
    {
        "source": "Article 99(3)",
        "text": "Non-compliance with the prohibition of the AI practices referred to in Article 5 shall be subject to administrative fines of up to 35 000 000 EUR or, if the offender is an undertaking, up to 7 % of its total worldwide annual turnover for the preceding financial year, whichever is higher.",
        "entities": [
            {"text": "Article 5", "type": "REGULATION_REF"},
            {"text": "35 000 000 EUR", "type": "MONEY"},
            {"text": "7 %", "type": "MONEY"},
        ],
    },
    {
        "source": "Article 99(4)",
        "text": "Non-compliance with any of the following provisions related to operators or notified bodies shall be subject to administrative fines of up to 15 000 000 EUR or, if the offender is an undertaking, up to 3 % of its total worldwide annual turnover for the preceding financial year, whichever is higher.",
        "entities": [
            {"text": "operators", "type": "STAKEHOLDER"},
            {"text": "notified bodies", "type": "STAKEHOLDER"},
            {"text": "15 000 000 EUR", "type": "MONEY"},
            {"text": "3 %", "type": "MONEY"},
        ],
    },
    {
        "source": "Article 99(5)",
        "text": "The supply of incorrect, incomplete or misleading information to notified bodies or national competent authorities in reply to a request shall be subject to administrative fines of up to 7 500 000 EUR or, if the offender is an undertaking, up to 1 % of its total worldwide annual turnover for the preceding financial year, whichever is higher.",
        "entities": [
            {"text": "notified bodies", "type": "STAKEHOLDER"},
            {"text": "national competent authorities", "type": "STAKEHOLDER"},
            {"text": "7 500 000 EUR", "type": "MONEY"},
            {"text": "1 %", "type": "MONEY"},
        ],
    },

    # Article 113 (Entry into force) 
    {
        "source": "Article 113",
        "text": "This Regulation shall enter into force on the twentieth day following that of its publication in the Official Journal of the European Union and shall apply from 2 August 2026.",
        "entities": [
            {"text": "2 August 2026", "type": "DEADLINE"},
        ],
    },

    # Cross-reference to GDPR 
    {
        "source": "Article 2(7)",
        "text": "Union law on the protection of personal data, privacy and the confidentiality of communications applies to personal data processed in connection with the rights and obligations laid down in this Regulation, in particular Regulation (EU) 2016/679.",
        "entities": [
            {"text": "Regulation (EU) 2016/679", "type": "LEGISLATION"},
        ],
    },

    # Annex III (High-risk use cases)
    {
        "source": "Annex III(1)",
        "text": "Biometrics, in so far as their use is permitted under relevant Union or national law: remote biometric identification systems, excluding AI systems intended to be used for biometric verification the sole purpose of which is to confirm that a specific natural person is the person he or she claims to be.",
        "entities": [
            {"text": "remote biometric identification systems", "type": "AI_SYSTEM"},
            {"text": "AI systems", "type": "AI_SYSTEM"},
        ],
    },
    {
        "source": "Annex III(6)",
        "text": "AI systems intended to be used by or on behalf of law enforcement authorities, or by Union institutions, bodies, offices or agencies in support of law enforcement authorities as polygraphs and similar tools.",
        "entities": [
            {"text": "AI systems", "type": "AI_SYSTEM"},
            {"text": "law enforcement authorities", "type": "STAKEHOLDER"},
        ],
    },
    {
        "source": "Annex IV(1)",
        "text": "The technical documentation referred to in Article 11(1) shall contain at least a general description of the AI system including its intended purpose, the name of the provider and the version of the system reflecting its relation to previous versions.",
        "entities": [
            {"text": "Article 11(1)", "type": "REGULATION_REF"},
            {"text": "AI system", "type": "AI_SYSTEM"},
            {"text": "provider", "type": "STAKEHOLDER"},
        ],
    },
    {
        "source": "Article 46(1)",
        "text": "By way of derogation from Article 43 and upon a duly justified request, any market surveillance authority may authorise the placing on the market of specific high-risk AI systems within the territory of the Member State concerned for a period not exceeding 12 months.",
        "entities": [
            {"text": "Article 43", "type": "REGULATION_REF"},
            {"text": "market surveillance authority", "type": "STAKEHOLDER"},
            {"text": "high-risk AI systems", "type": "AI_SYSTEM"},
            {"text": "12 months", "type": "DEADLINE"},
        ],
    },
]

# spaCy extractor — maps spaCy's native entity types to our gold-standard types


SPACY_TYPE_MAP = {
    "LAW":     "LEGISLATION",
    "DATE":    "DEADLINE",
    "MONEY":   "MONEY",
    "PERCENT": "MONEY",
}


def extract_spacy(nlp, sentence: str) -> list[dict]:
    """Run spaCy NER on a sentence and return entities mapped to our schema."""
    doc = nlp(sentence)
    out = []
    for ent in doc.ents:
        mapped_type = SPACY_TYPE_MAP.get(ent.label_)
        if mapped_type:
            out.append({"text": ent.text, "type": mapped_type,
                       "spacy_label": ent.label_})
    return out


# Regex extractor — reproduces the patterns from ner_enrich.py

REGEX_PATTERNS = [
    # Article references: "Article 5", "Article 10(1)", "Articles 5 to 10"
    (re.compile(r"\bArticle\s+\d+(?:\s*\(\d+\))?(?:\s*\([a-z]\))?", re.IGNORECASE),
     "REGULATION_REF"),
    # Paragraph references: "paragraph 1", "paragraphs 2 to 5", "paragraph 1, point (h)"
    (re.compile(r"\bparagraphs?\s+\d+(?:\s+and\s+\d+)?(?:\s+to\s+\d+)?(?:,\s*point\s*\([a-z]\))?",
                re.IGNORECASE),
     "REGULATION_REF"),
    # Annex references: "Annex III", "Annex IV(1)", "Annex I"
    (re.compile(r"\bAnnex\s+(?:I{1,3}|IV|V|VI{0,3}|IX|X{1,2})(?:\s*\(\d+\))?"),
     "REGULATION_REF"),
    # External EU regulations: "Regulation (EU) 2016/679", "Directive 2014/90/EU"
    (re.compile(r"\b(?:Regulation|Directive)\s*\(EU\)\s*\d{4}/\d+"),
     "LEGISLATION"),
    (re.compile(r"\b(?:Regulation|Directive)\s*\d{4}/\d+/EU"),
     "LEGISLATION"),
    # Fine amounts in EUR: "35 000 000 EUR", "15 000 000 EUR", "7 500 000 EUR"
    (re.compile(r"\b\d{1,3}(?:\s?\d{3}){1,3}\s*EUR\b"),
     "MONEY"),
    # Percentage ratios: "7 %", "3%", "1 %"
    (re.compile(r"\b\d+(?:\.\d+)?\s*%"),
     "MONEY"),
    # Duration expressions: "15 days", "12 months", "2 days", "10 years"
    (re.compile(r"\b\d+\s+(?:day|days|month|months|year|years|week|weeks)\b",
                re.IGNORECASE),
     "DEADLINE"),
    # Absolute date: "2 August 2026"
    (re.compile(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|"
                r"August|September|October|November|December)\s+\d{4}\b"),
     "DEADLINE"),
]


def extract_regex(sentence: str) -> list[dict]:
    """Run the regex pipeline on a sentence."""
    out = []
    seen = set()
    for pattern, type_tag in REGEX_PATTERNS:
        for match in pattern.finditer(sentence):
            text = match.group(0).strip()
            key = (text.lower(), type_tag)
            if key in seen:
                continue
            seen.add(key)
            out.append({"text": text, "type": type_tag})
    return out


# Scoring — per-entity-type precision / recall / F1

def normalise(text: str) -> str:
    """Normalise entity text for matching: lowercase, collapse whitespace,
    strip trailing punctuation."""
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(".,;:!?")
    return t


def score_against_gold(predicted: list[dict], gold: list[dict],
                       entity_types: list[str]) -> dict:
    """Compute per-type and overall precision/recall/F1.

    Matching is CASE-INSENSITIVE and SUBSTRING-TOLERANT: a predicted entity
    matches a gold entity if either is a substring of the other AND the
    types match. This is more lenient than exact matching but more strict
    than bag-of-words.
    """
    # Group by type
    pred_by_type = defaultdict(list)
    for p in predicted:
        pred_by_type[p["type"]].append(normalise(p["text"]))
    gold_by_type = defaultdict(list)
    for g in gold:
        gold_by_type[g["type"]].append(normalise(g["text"]))

    per_type = {}
    total_tp = total_fp = total_fn = 0
    for t in entity_types:
        preds = pred_by_type[t]
        golds = gold_by_type[t]
        if not preds and not golds:
            per_type[t] = {"tp": 0, "fp": 0, "fn": 0,
                          "precision": None, "recall": None, "f1": None,
                          "support": 0}
            continue
        # Greedy matching
        matched_gold = set()
        tp = 0
        for p in preds:
            best_idx = None
            for i, g in enumerate(golds):
                if i in matched_gold:
                    continue
                if p == g or p in g or g in p:
                    best_idx = i
                    break
            if best_idx is not None:
                matched_gold.add(best_idx)
                tp += 1
        fp = len(preds) - tp
        fn = len(golds) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall    = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) else 0.0)
        per_type[t] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3),
            "recall":    round(recall, 3),
            "f1":        round(f1, 3),
            "support":   len(golds),
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    overall_f = (2 * overall_p * overall_r / (overall_p + overall_r)
                 if (overall_p + overall_r) else 0.0)

    return {
        "per_type": per_type,
        "overall": {
            "tp": total_tp, "fp": total_fp, "fn": total_fn,
            "precision": round(overall_p, 3),
            "recall":    round(overall_r, 3),
            "f1":        round(overall_f, 3),
        },
    }

# Main

ENTITY_TYPES = ["AI_SYSTEM", "STAKEHOLDER", "REGULATION_REF",
                "LEGISLATION", "DEADLINE", "MONEY"]


def main() -> None:
    print("=" * 70)
    print("ner_benchmark.py — spaCy + regex pipeline vs gold standard")
    print("=" * 70)

    os.makedirs(EVAL_DIR, exist_ok=True)

    # Persist the gold standard for reproducibility
    with open(GOLD_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "description": ("Hand-annotated gold standard for NER benchmarking. "
                           "30 sentences drawn from the EU AI Act with per-entity "
                           "annotations under 6 domain-relevant entity types."),
            "entity_types": ENTITY_TYPES,
            "total_sentences": len(GOLD_STANDARD),
            "total_entities": sum(len(s["entities"]) for s in GOLD_STANDARD),
            "sentences": GOLD_STANDARD,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nGold standard: {len(GOLD_STANDARD)} sentences, "
          f"{sum(len(s['entities']) for s in GOLD_STANDARD)} entity annotations")
    print(f"  Written to: {GOLD_OUT}")

    # Per-type support count
    type_support = defaultdict(int)
    for s in GOLD_STANDARD:
        for e in s["entities"]:
            type_support[e["type"]] += 1
    print("\nGold-standard entity distribution:")
    for t in ENTITY_TYPES:
        print(f"  {t:15}  {type_support[t]:>3} entities")

    # Load spaCy
    print("\nLoading spaCy en_core_web_sm...")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("ERROR: en_core_web_sm model not installed.")
        print("Run: python -m spacy download en_core_web_sm")
        sys.exit(1)

    # Run extractors on every gold sentence
    print("\nRunning extractors...")
    spacy_preds = []
    regex_preds = []
    per_sentence = []
    t0_spacy = time.perf_counter()
    for s in GOLD_STANDARD:
        sp = extract_spacy(nlp, s["text"])
        spacy_preds.extend(sp)
        per_sentence.append({
            "source": s["source"],
            "text": s["text"][:100],
            "gold": s["entities"],
            "spacy": sp,
        })
    t_spacy = time.perf_counter() - t0_spacy

    t0_regex = time.perf_counter()
    for i, s in enumerate(GOLD_STANDARD):
        rg = extract_regex(s["text"])
        regex_preds.extend(rg)
        per_sentence[i]["regex"] = rg
    t_regex = time.perf_counter() - t0_regex

    print(f"  spaCy:  {len(spacy_preds):>4} entities extracted  ({t_spacy*1000:.1f} ms)")
    print(f"  regex:  {len(regex_preds):>4} entities extracted  ({t_regex*1000:.1f} ms)")

    # Also compute combined extractor (spaCy + regex) since that's what
    # the live pipeline actually uses
    # Combined extractor: de-duplicate by (normalised text, type) so a single
    # gold entity matched by BOTH spaCy and regex doesn't get counted as a
    # false positive against itself. Without this, the combined precision is
    # artificially halved on entity types where both extractors fire.
    combined_preds_raw = spacy_preds + regex_preds
    seen_combined = set()
    combined_preds = []
    for p in combined_preds_raw:
        key = (normalise(p["text"]), p["type"])
        if key in seen_combined:
            continue
        seen_combined.add(key)
        combined_preds.append(p)

    # Flatten gold
    gold_flat = []
    for s in GOLD_STANDARD:
        for e in s["entities"]:
            gold_flat.append({"type": e["type"], "text": e["text"]})

    print("\n" + "─" * 70)
    print("Scoring: spaCy alone")
    print("─" * 70)
    spacy_results = score_against_gold(spacy_preds, gold_flat, ENTITY_TYPES)
    for t in ENTITY_TYPES:
        r = spacy_results["per_type"][t]
        if r["support"] == 0:
            continue
        print(f"  {t:15}  P={r['precision'] if r['precision'] is not None else '--':>5}  "
              f"R={r['recall'] if r['recall'] is not None else '--':>5}  "
              f"F1={r['f1'] if r['f1'] is not None else '--':>5}  "
              f"(support={r['support']})")
    o = spacy_results["overall"]
    print(f"  {'OVERALL':15}  P={o['precision']:>5}  R={o['recall']:>5}  F1={o['f1']:>5}")

    print("\n" + "─" * 70)
    print("Scoring: regex pipeline alone")
    print("─" * 70)
    regex_results = score_against_gold(regex_preds, gold_flat, ENTITY_TYPES)
    for t in ENTITY_TYPES:
        r = regex_results["per_type"][t]
        if r["support"] == 0:
            continue
        print(f"  {t:15}  P={r['precision'] if r['precision'] is not None else '--':>5}  "
              f"R={r['recall'] if r['recall'] is not None else '--':>5}  "
              f"F1={r['f1'] if r['f1'] is not None else '--':>5}  "
              f"(support={r['support']})")
    o = regex_results["overall"]
    print(f"  {'OVERALL':15}  P={o['precision']:>5}  R={o['recall']:>5}  F1={o['f1']:>5}")

    print("\n" + "─" * 70)
    print("Scoring: combined (spaCy + regex, the live pipeline)")
    print("─" * 70)
    combined_results = score_against_gold(combined_preds, gold_flat, ENTITY_TYPES)
    for t in ENTITY_TYPES:
        r = combined_results["per_type"][t]
        if r["support"] == 0:
            continue
        print(f"  {t:15}  P={r['precision'] if r['precision'] is not None else '--':>5}  "
              f"R={r['recall'] if r['recall'] is not None else '--':>5}  "
              f"F1={r['f1'] if r['f1'] is not None else '--':>5}  "
              f"(support={r['support']})")
    o = combined_results["overall"]
    print(f"  {'OVERALL':15}  P={o['precision']:>5}  R={o['recall']:>5}  F1={o['f1']:>5}")

    # Write the full benchmark report
    report = {
        "gold_standard": {
            "path": GOLD_OUT,
            "sentences": len(GOLD_STANDARD),
            "total_entities": len(gold_flat),
            "per_type_support": dict(type_support),
        },
        "extractors": {
            "spacy_en_core_web_sm": {
                "entities_extracted": len(spacy_preds),
                "runtime_ms": round(t_spacy * 1000, 2),
                "results": spacy_results,
            },
            "regex_pipeline": {
                "entities_extracted": len(regex_preds),
                "runtime_ms": round(t_regex * 1000, 2),
                "results": regex_results,
            },
            "combined_spacy_plus_regex": {
                "entities_extracted": len(combined_preds),
                "results": combined_results,
            },
        },
        "per_sentence": per_sentence,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nBenchmark report written to: {OUT_JSON}")


if __name__ == "__main__":
    main()