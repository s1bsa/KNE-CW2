"""
Combines the three HTML-pipeline JSON outputs (rule-based, LLM, NER+regex)
into the HTML-layer TTL.

Responsibilities:
  - Mints canonical parent artefacts (:TechnicalDocumentation_Annex_IV,
    :RegistrationRecord_Annex_VIII, :TestingPlan_Annex_IX,
    :ThirdPartyAssessment_Annex_VII, :InternalControl_Annex_VI) and wires
    components to them via :hasRequiredComponent.
  - Coalesces SINGLETON_TYPES (e.g. AIRegulatorySandbox) into one canonical
    URI per type to prevent cartesian-product blowup in CQ results.
  - Ingests NER enrichments as typed literals (xsd:duration, xsd:decimal)
    and as object-property edges (:hasArticleReference, :cites).
  - Mints fallback :EULegislation instances for cited legislation that
    doesn't already exist in the structured pipeline output.

Inputs:  eu_ai_act_articles.json, rule_extraction.json,
         llm_extraction.json, ner_enrichment.json
Output:  data/unstructured/html/eu_ai_act_html.ttl
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

# Paths 
ARTICLES_JSON   = "data/unstructured/html/eu_ai_act_articles.json"
RULE_JSON       = "data/unstructured/html/rule_extraction.json"
LLM_JSON        = "data/unstructured/html/llm_extraction.json"
NER_JSON        = "data/unstructured/html/ner_enrichment.json"
OUTPUT_TTL      = "data/unstructured/html/eu_ai_act_html.ttl"

# Namespaces 
EX    = Namespace("https://example.org/eu-ai-act-compliance#")
AIRO  = Namespace("https://w3id.org/airo#")
AIACT = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
DPV   = Namespace("https://w3id.org/dpv#")

# Type → ontology IRI mapping

TYPE_MAP = {
    # Obligation hierarchy 
    "ConformityAssessmentObligation":     EX.ConformityAssessmentObligation,
    "InternalControlObligation":          EX.InternalControlObligation,
    "ThirdPartyAssessmentObligation":     EX.ThirdPartyAssessmentObligation,
    "TransparencyObligation":             EX.TransparencyObligation,
    "PostMarketMonitoringObligation":     EX.PostMarketMonitoringObligation,
    "WorkerNotificationObligation":       EX.WorkerNotificationObligation,
    "FRIAObligation":                     EX.FRIAObligation,
    "ProviderIncidentReport":             EX.ProviderIncidentReport,
    "DeployerIncidentReport":             EX.DeployerIncidentReport,
    "GPAISystemicRiskIncidentReport":     EX.GPAISystemicRiskIncidentReport,
    "IncidentReportingObligation":        EX.IncidentReportingObligation,
    "GeneralGPAIObligation":              EX.GeneralGPAIObligation,
    "SystemicRiskGPAIObligation":         EX.SystemicRiskGPAIObligation,
    "GPAIObligation":                     EX.GPAIObligation,
    "SupportMeasureObligation":           EX.SupportMeasureObligation,
    # Power hierarchy 
    "OversightPower":                     EX.OversightPower,
    "InvestigativePower":                 EX.InvestigativePower,
    "EnforcementPower":                   EX.EnforcementPower,
    "AdvisoryPower":                      EX.AdvisoryPower,
    # Condition hierarchy 
    "NecessityCondition":                 EX.NecessityCondition,
    "ProportionalityCondition":           EX.ProportionalityCondition,
    "ProceduralCondition":                EX.ProceduralCondition,
    "PurposeCondition":                   EX.PurposeCondition,
    # Domain entities 
    "ProhibitedPractice":                 AIACT.ProhibitedPractice,
    "TechnicalDocumentation":             AIACT.TechnicalDocumentation,
    "CEMarking":                          EX.CEMarking,
    "RiskControl":                        AIRO.RiskControl,
    "AIRegulatorySandbox":                AIACT.AIRegulatorySandbox,
    "NaturalPersonSubject":               DPV.NaturalPerson,
    "AreaOfApplication":                  EX.AreaOfApplication,
    # component types 
    "DocumentationComponent":             EX.DocumentationComponent,
    "RegistrationField":                  EX.RegistrationField,
    "ConformityAssessmentStep":           EX.ConformityAssessmentStep,
    "TestingPlanField":                   EX.TestingPlanField,
    "CEMarkingComponent":                 EX.CEMarkingComponent,
    "Requirement":                        EX.Requirement,
}

TYPE_ALIASES = {
    "obligations":                      None,
    "powers":                           None,
    "conditions":                       None,
    "domain entities":                  None,
    "obligation":                       None,
    "power":                            None,
    "condition":                        None,
    # Anchor types we explicitly REJECT
    "provider":                         None,
    "deployer":                         None,
    "aioperator":                       None,
    "ai operator":                      None,
    "aisystem":                         None,
    "ai system":                        None,
    "highriskaisystem":                 None,
    "high-risk ai system":              None,
    "high risk ai system":              None,
    "generalpurposeaimodel":            None,
    "general purpose ai model":         None,
    "gpai model":                       None,
    "gpaimodelwithsystemicrisk":        None,
    "gpai model with systemic risk":    None,
    "aioffice":                         None,
    "ai office":                        None,
    "marketsurveillanceauthority":      None,
    "market surveillance authority":    None,
    "msa":                              None,
    "conformityassessmentbody":         None,
    "notifiedbody":                     None,
    "conformityassessment":             None,
    "conformity assessment":            None,
    "article":                          None,
    "annex":                            None,
    "paragraph":                        None,
    # Typos / variants we DO accept
    "proceeduralcondition":             "ProceduralCondition",
    "supportmeasuresobligation":        "SupportMeasureObligation",
    "supportmeasureobligations":        "SupportMeasureObligation",
    "naturalperson":                    "NaturalPersonSubject",
    "natural person":                   "NaturalPersonSubject",
    "naturalpersonsubject":             "NaturalPersonSubject",
    "documentation":                    "TechnicalDocumentation",
    "technicaldocumentation":           "TechnicalDocumentation",
    "riskcontrol":                      "RiskControl",
    "risk control":                     "RiskControl",
    "prohibitedpractice":               "ProhibitedPractice",
    "prohibited practice":              "ProhibitedPractice",
    "airegulatorysandbox":              "AIRegulatorySandbox",
    "ai regulatory sandbox":            "AIRegulatorySandbox",
    "regulatory sandbox":               "AIRegulatorySandbox",
    "cemarking":                        "CEMarking",
    "ce marking":                       "CEMarking",
    "areaofapplication":                "AreaOfApplication",
    "area of application":              "AreaOfApplication",
    "documentationcomponent":           "DocumentationComponent",
    "registrationfield":                "RegistrationField",
    "conformityassessmentstep":         "ConformityAssessmentStep",
    "testingplanfield":                 "TestingPlanField",
    "cemarkingcomponent":               "CEMarkingComponent",
    "requirement":                      "Requirement",
}


def map_type(type_str: str):
    """Map an LLM-emitted type string to (canonical_name, ontology_iri)."""
    if not type_str:
        return None, None
    if type_str in TYPE_MAP:
        return type_str, TYPE_MAP[type_str]
    folded = type_str.strip().lower()
    if folded in TYPE_ALIASES:
        target = TYPE_ALIASES[folded]
        if target is None:
            return None, None
        return target, TYPE_MAP.get(target)
    return None, None


# Cardinality / coalescing


SINGLETON_TYPES = {
    "AIRegulatorySandbox":    EX.AIRegulatorySandboxInstance,
    "TechnicalDocumentation": EX.TechnicalDocumentation_Annex_IV,
}


# Type → role bearer wiring rules

PROVIDER_OBLIGATION_TYPES = {
    "ConformityAssessmentObligation",
    "InternalControlObligation",
    "ThirdPartyAssessmentObligation",
    "TransparencyObligation",
    "PostMarketMonitoringObligation",
    "ProviderIncidentReport",
    "GeneralGPAIObligation",
    "SystemicRiskGPAIObligation",
    "GPAIObligation",
    "GPAISystemicRiskIncidentReport",
    "IncidentReportingObligation",
}

DEPLOYER_OBLIGATION_TYPES = {
    "WorkerNotificationObligation",
    "FRIAObligation",
    "DeployerIncidentReport",
}

SME_OBLIGATION_TYPES = {
    "SupportMeasureObligation",
}

POWER_TYPES = {
    "OversightPower",
    "InvestigativePower",
    "EnforcementPower",
    "AdvisoryPower",
}

GPAI_OBLIGATION_TYPES = {
    "GeneralGPAIObligation",
    "SystemicRiskGPAIObligation",
    "GPAIObligation",
    "GPAISystemicRiskIncidentReport",
}

SYSTEM_DIRECT_OBLIGATION_TYPES = {
    "TransparencyObligation",
}

REPORTING_TARGET_DEFAULTS = {
    "GPAISystemicRiskIncidentReport": "AIOffice",
    "ProviderIncidentReport":         "MarketSurveillanceAuthority",
    "DeployerIncidentReport":         "MarketSurveillanceAuthority",
}

# Component-type → parent-anchor URI
COMPONENT_PARENT_URI = {
    "DocumentationComponent":    EX.TechnicalDocumentation_Annex_IV,
    "RegistrationField":         EX.RegistrationRecord_Annex_VIII,
    "TestingPlanField":          EX.TestingPlan_Annex_IX,
    "ConformityAssessmentStep":  None,  # parent depends on rule_id (VI vs VII)
    "CEMarkingComponent":        None,  # not yet minted
}

# Paragraph reference parsing

PARAGRAPH_REF_RE = re.compile(
    r"Article\s+(\d+)(?:\s*\((\d+)\))?(?:\s*\(([a-zA-Z0-9]+)\))?",
    re.IGNORECASE,
)
ANNEX_REF_RE = re.compile(
    r"Annex\s+([IVXLCDMivxlcdm]+|\d+)",
    re.IGNORECASE,
)


def parse_paragraph_ref(ref):
    if not ref:
        return None, None, None
    m = PARAGRAPH_REF_RE.search(ref)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


def parse_annex_ref(ref):
    if not ref:
        return None
    m = ANNEX_REF_RE.search(ref)
    if not m:
        return None
    return m.group(1).upper()


def paragraph_uri(art_num, para_num, list_label):
    ref_str = f"Article {art_num}"
    if para_num:
        ref_str += f"({para_num})"
    if list_label:
        ref_str += f"({list_label})"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ref_str).strip("_")
    return EX[f"Paragraph_{slug}"]

# Helpers

def _safe_load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sanitise_uri_suffix(suffix):
    return re.sub(r"[^A-Za-z0-9_]", "_", suffix or "instance")

# Main

def main() -> None:
    print(f"Loading {ARTICLES_JSON}")
    articles_payload = _safe_load_json(ARTICLES_JSON) or {}
    print(f"Loading {RULE_JSON}")
    rule_payload = _safe_load_json(RULE_JSON) or {"instances": []}
    print(f"Loading {LLM_JSON}")
    llm_payload = _safe_load_json(LLM_JSON) or {"instances": []}
    print(f"Loading {NER_JSON}")
    ner_payload = _safe_load_json(NER_JSON) or {"enrichments": []}

    g = Graph()
    g.bind("",         EX)
    g.bind("airo",     AIRO)
    g.bind("eu-aiact", AIACT)
    g.bind("dpv",      DPV)
    g.bind("rdfs",     RDFS)
    g.bind("xsd",      XSD)

    # 1. Articles, Paragraphs, Annexes (structural layer) 
    print("\n=== 1. Structural layer ===")
    art_count = para_count = annex_count = 0
    article_lookup = {}
    annex_lookup = {}

    for article in articles_payload.get("articles", []):
        num = article.get("article_number")
        if num is None:
            continue
        article_lookup[num] = article
        article_uri = EX[f"Article_{num}"]
        g.add((article_uri, RDF.type, EX.Article))
        title = article.get("title")
        if title:
            g.add((article_uri, RDFS.label,
                   Literal(f"Article {num} — {title}", lang="en")))
        source_path = article.get("source_path")
        if source_path:
            g.add((article_uri, EX.hasSourceURL,
                   Literal(source_path, datatype=XSD.string)))
        art_count += 1

        for item in article.get("content_items", []):
            ref = item.get("reference")
            text = item.get("text")
            if not ref or not text:
                continue
            slug = re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_")
            paragraph_uri_ref = EX[f"Paragraph_{slug}"]
            g.add((paragraph_uri_ref, RDF.type, EX.Paragraph))
            g.add((paragraph_uri_ref, RDFS.label, Literal(ref, lang="en")))
            g.add((paragraph_uri_ref, EX.hasSummary,
                   Literal(text, datatype=XSD.string)))
            g.add((article_uri, EX.hasParagraphReference, paragraph_uri_ref))
            para_count += 1

    for annex in articles_payload.get("annexes", []):
        num = annex.get("annex_number")
        if not num:
            continue
        annex_lookup[str(num).upper()] = annex
        annex_uri = EX[f"Annex_{num}"]
        g.add((annex_uri, RDF.type, EX.Annex))
        title = annex.get("title")
        if title:
            g.add((annex_uri, RDFS.label,
                   Literal(f"Annex {num} — {title}", lang="en")))
        annex_count += 1

    print(f"  Articles:   {art_count}")
    print(f"  Paragraphs: {para_count}")
    print(f"  Annexes:    {annex_count}")

    # 2. Canonical anchors 
    print("\n=== 2. Canonical anchors ===")

    PROVIDER       = EX.ProviderStakeholder
    DEPLOYER       = EX.DeployerStakeholder
    AI_OFFICE      = EX.AIOffice
    HIGH_RISK_LVL  = EX.HighRisk

    g.add((PROVIDER,  RDF.type, AIACT.AIProvider))
    g.add((PROVIDER,  RDFS.label, Literal("Generic AI provider stakeholder", lang="en")))
    g.add((DEPLOYER,  RDF.type, AIACT.AIDeployer))
    g.add((DEPLOYER,  RDFS.label, Literal("Generic AI deployer stakeholder", lang="en")))
    g.add((AI_OFFICE, RDF.type, DPV.Authority))

    SME_STAKEHOLDER       = EX.SMEStakeholder
    NATURAL_PERSON_SUBJ   = EX.NaturalPersonSubject
    NOTIFIED_BODY_DEMO    = EX.NotifiedBody_Demo
    GPAI_MODEL            = EX.GPAIModelInstance
    GPAI_SYSTEMIC_MODEL   = EX.GPAISystemicRiskModelInstance
    SANDBOX               = EX.AIRegulatorySandboxInstance
    TECH_DOC_ANNEX_IV     = EX.TechnicalDocumentation_Annex_IV
    REGISTRATION_RECORD   = EX.RegistrationRecord_Annex_VIII
    TESTING_PLAN          = EX.TestingPlan_Annex_IX
    THIRD_PARTY_ASMT      = EX.ThirdPartyAssessment_Annex_VII
    INTERNAL_CONTROL      = EX.InternalControl_Annex_VI
    MARKET_SURVEILLANCE   = EX.MarketSurveillanceAuthority

    g.add((SME_STAKEHOLDER, RDF.type, EX.SMEProvider))
    g.add((SME_STAKEHOLDER, RDFS.label,
           Literal("SME provider stakeholder", lang="en")))

    g.add((NATURAL_PERSON_SUBJ, RDF.type, DPV.NaturalPerson))
    g.add((NATURAL_PERSON_SUBJ, RDF.type, AIRO.AISubject))
    g.add((NATURAL_PERSON_SUBJ, RDFS.label,
           Literal("Generic natural person subject", lang="en")))

    g.add((GPAI_MODEL, RDF.type, AIACT.GeneralPurposeAIModel))
    g.add((GPAI_MODEL, RDF.type, AIRO.AISystem))
    g.add((GPAI_MODEL, RDFS.label,
           Literal("Generic general-purpose AI model", lang="en")))
    g.add((GPAI_MODEL, EX.hasProvider, PROVIDER))

    g.add((GPAI_SYSTEMIC_MODEL, RDF.type, EX.GeneralPurposeAIModelWithSystemicRisk))
    g.add((GPAI_SYSTEMIC_MODEL, RDF.type, AIACT.GeneralPurposeAIModel))
    g.add((GPAI_SYSTEMIC_MODEL, RDF.type, AIRO.AISystem))
    g.add((GPAI_SYSTEMIC_MODEL, RDFS.label,
           Literal("Generic GPAI model with systemic risk", lang="en")))
    g.add((GPAI_SYSTEMIC_MODEL, EX.hasProvider, PROVIDER))

    g.add((SANDBOX, RDF.type, AIACT.AIRegulatorySandbox))
    g.add((SANDBOX, RDFS.label,
           Literal("Generic AI regulatory sandbox", lang="en")))

    g.add((TECH_DOC_ANNEX_IV, RDF.type, AIACT.TechnicalDocumentation))
    g.add((TECH_DOC_ANNEX_IV, RDF.type, AIRO.Documentation))
    g.add((TECH_DOC_ANNEX_IV, RDFS.label,
           Literal("Annex IV technical documentation", lang="en")))
    g.add((TECH_DOC_ANNEX_IV, EX.hasArticleReference, EX.Article_11))
    if "IV" in annex_lookup:
        g.add((TECH_DOC_ANNEX_IV, EX.hasAnnexReference, EX.Annex_IV))
    annex_iv = annex_lookup.get("IV")
    if annex_iv and annex_iv.get("text"):
        g.add((TECH_DOC_ANNEX_IV, EX.hasSummary,
               Literal(annex_iv["text"][:1500], datatype=XSD.string)))

    g.add((REGISTRATION_RECORD, RDF.type, AIRO.Documentation))
    g.add((REGISTRATION_RECORD, RDFS.label,
           Literal("Annex VIII registration record", lang="en")))
    g.add((REGISTRATION_RECORD, EX.hasArticleReference, EX.Article_49))
    if "VIII" in annex_lookup:
        g.add((REGISTRATION_RECORD, EX.hasAnnexReference, EX.Annex_VIII))

    g.add((TESTING_PLAN, RDF.type, AIRO.Documentation))
    g.add((TESTING_PLAN, RDFS.label,
           Literal("Annex IX real-world testing plan", lang="en")))
    g.add((TESTING_PLAN, EX.hasArticleReference, EX.Article_60))
    if "IX" in annex_lookup:
        g.add((TESTING_PLAN, EX.hasAnnexReference, EX.Annex_IX))

    g.add((THIRD_PARTY_ASMT, RDF.type, AIACT.ConformityAssessment))
    g.add((THIRD_PARTY_ASMT, RDFS.label,
           Literal("Annex VII third-party conformity assessment procedure", lang="en")))
    g.add((THIRD_PARTY_ASMT, EX.hasArticleReference, EX.Article_43))
    if "VII" in annex_lookup:
        g.add((THIRD_PARTY_ASMT, EX.hasAnnexReference, EX.Annex_VII))

    g.add((INTERNAL_CONTROL, RDF.type, AIACT.ConformityAssessment))
    g.add((INTERNAL_CONTROL, RDFS.label,
           Literal("Annex VI internal control conformity assessment procedure", lang="en")))
    g.add((INTERNAL_CONTROL, EX.hasArticleReference, EX.Article_43))
    if "VI" in annex_lookup:
        g.add((INTERNAL_CONTROL, EX.hasAnnexReference, EX.Annex_VI))

    g.add((MARKET_SURVEILLANCE, RDF.type, DPV.Authority))
    g.add((MARKET_SURVEILLANCE, RDFS.label,
           Literal("National market surveillance authority", lang="en")))

    g.add((NOTIFIED_BODY_DEMO, RDF.type, EX.ConformityAssessmentBody))
    g.add((NOTIFIED_BODY_DEMO, RDFS.label,
           Literal("Demonstration notified body (Article 31)", lang="en")))
    g.add((NOTIFIED_BODY_DEMO, EX.hasArticleReference, EX.Article_31))
    g.add((NOTIFIED_BODY_DEMO, RDF.type, EX.NotifiedBody))

    g.add((HIGH_RISK_LVL, RDF.type, EX.RiskLevel))
    g.add((HIGH_RISK_LVL, RDFS.label, Literal("High risk", lang="en")))

    print("  All canonical anchors emitted")

    # 3. Rule-based extraction ingestion 
    print("\n=== 3. Rule-based instances ===")
    rule_instances = rule_payload.get("instances", [])
    rule_added = 0
    rule_type_counts = {}
    high_risk_systems = []
    biometric_practice_uri = None

    # Track Annex III sectors so we can mint paired HighRiskAISystem instances
    sector_records = []  # list of (slug, label, summary, sector_uri)

    for inst in rule_instances:
        type_str = inst["type"]
        canonical, type_iri = map_type(type_str)
        if type_iri is None:
            continue
        rule_type_counts[type_str] = rule_type_counts.get(type_str, 0) + 1

        # Special handling: Requirement instances are pre-existing TBox individuals
        if type_str == "Requirement":
            # Wire NotifiedBody_Demo → :meetsRequirement → individual
            req_uri = EX[inst["uri_suffix"]]
            g.add((NOTIFIED_BODY_DEMO, EX.meetsRequirement, req_uri))
            rule_added += 1
            continue

        # Special handling: AreaOfApplication → also mint paired HighRiskAISystem
        if type_str == "AreaOfApplication":
            slug = inst.get("sector_slug") or inst["uri_suffix"].replace("area_of_application_", "")
            sector_uri = EX[f"AreaOfApplication_{slug}"]
            g.add((sector_uri, RDF.type, EX.AreaOfApplication))
            g.add((sector_uri, RDFS.label, Literal(inst.get("label", slug), lang="en")))
            g.add((sector_uri, EX.hasSummary,
                   Literal(inst.get("summary", ""), datatype=XSD.string)))
            g.add((sector_uri, EX.hasAnnexReference, EX.Annex_III))
            sector_records.append((slug, inst.get("label", slug),
                                   inst.get("summary", ""), sector_uri))
            rule_added += 1
            continue

        # Standard mint
        suffix = _sanitise_uri_suffix(inst["uri_suffix"])
        instance_uri = EX[suffix]
        g.add((instance_uri, RDF.type, type_iri))

        label = inst.get("label") or suffix
        g.add((instance_uri, RDFS.label, Literal(label, lang="en")))
        if inst.get("summary"):
            g.add((instance_uri, EX.hasSummary,
                   Literal(inst["summary"], datatype=XSD.string)))

        # paragraph_ref → article/annex/paragraph references
        para_ref = inst.get("paragraph_ref")
        art_num, para_num, list_label = parse_paragraph_ref(para_ref)
        annex_num = parse_annex_ref(para_ref)
        if art_num:
            g.add((instance_uri, EX.hasArticleReference,
                   EX[f"Article_{art_num}"]))
            if para_num:
                g.add((instance_uri, EX.hasParagraphReference,
                       paragraph_uri(art_num, para_num, list_label)))
        if annex_num:
            g.add((instance_uri, EX.hasAnnexReference,
                   EX[f"Annex_{annex_num}"]))

        # Component → parent artefact wiring
        if type_str in COMPONENT_PARENT_URI:
            parent_uri = COMPONENT_PARENT_URI[type_str]
            if type_str == "ConformityAssessmentStep":
                rule_id = inst.get("rule_id", "")
                if "vii" in rule_id:
                    parent_uri = THIRD_PARTY_ASMT
                elif "vi_" in rule_id or rule_id == "annex_vi_steps":
                    parent_uri = INTERNAL_CONTROL
                else:
                    parent_uri = THIRD_PARTY_ASMT
            if parent_uri is not None:
                g.add((parent_uri, EX.hasRequiredComponent, instance_uri))
                g.add((instance_uri, EX.hasComponentOf, parent_uri))

        # ProhibitedPractice rule-based seed
        if type_str == "ProhibitedPractice":
            if inst.get("is_biometric") and biometric_practice_uri is None:
                biometric_practice_uri = instance_uri

        # RiskControl from Article 14 → wire to all HighRiskAISystem (after sectors minted)
        # Stored for later in a list since sectors are processed in same loop;
        # we'll do the wiring in a follow-up pass below.

        rule_added += 1

    # Mint HighRiskAISystem_<sector> instances now that sectors are known
    for slug, label, summary, sector_uri in sector_records:
        hr_uri = EX[f"HighRiskAISystem_{slug}"]
        g.add((hr_uri, RDF.type, AIACT.HighRiskAISystem))
        g.add((hr_uri, RDF.type, AIRO.AISystem))
        g.add((hr_uri, RDFS.label,
               Literal(f"High-risk AI system in {label}", lang="en")))
        g.add((hr_uri, EX.hasRiskLevel, HIGH_RISK_LVL))
        g.add((hr_uri, EX.hasAreaOfApplication, sector_uri))
        g.add((hr_uri, EX.hasProvider, PROVIDER))
        g.add((hr_uri, EX.hasDeployer, DEPLOYER))
        g.add((hr_uri, AIRO.hasDocumentation, TECH_DOC_ANNEX_IV))
        g.add((hr_uri, AIRO.hasAISubject, NATURAL_PERSON_SUBJ))
        g.add((hr_uri, EX.hasArticleReference, EX.Article_6))
        high_risk_systems.append(hr_uri)

    # Wire Article 14 risk controls onto every HighRiskAISystem
    risk_control_uris = []
    for inst in rule_instances:
        if inst["type"] == "RiskControl":
            risk_control_uris.append(EX[_sanitise_uri_suffix(inst["uri_suffix"])])
    for hr in high_risk_systems:
        for rc in risk_control_uris:
            g.add((hr, AIRO.hasRiskControl, rc))

    print(f"  Rule instances added: {rule_added}")
    print(f"  HighRiskAISystem_<sector>: {len(high_risk_systems)}")
    print(f"  Article 14 risk controls wired: {len(risk_control_uris)}")
    print("  Type breakdown:")
    for t, n in sorted(rule_type_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {t}")

    # 4. LLM extraction ingestion (with singleton coalescing) 
    print("\n=== 4. LLM instances ===")
    llm_instances = llm_payload.get("instances", [])
    llm_added = 0
    llm_skipped_unmapped = 0
    llm_skipped_singleton = 0
    llm_type_counts = {}
    wirings_added = 0
    art5_conditions = []
    art51_conditions = []
    art57_conditions = []

    # Map from LLM uri_suffix → final URI (used by NER pass to find subjects)
    llm_uri_map = {}

    for inst in llm_instances:
        type_str = (inst.get("type") or "").strip()
        suffix = (inst.get("uri_suffix") or "").strip()
        summary = (inst.get("summary") or "").strip()
        para_ref = inst.get("paragraph_ref")
        source_article = inst.get("source_article")

        if not type_str or not suffix:
            llm_skipped_unmapped += 1
            continue

        canonical, type_iri = map_type(type_str)
        if type_iri is None:
            llm_skipped_unmapped += 1
            continue

        # Singleton coalescing: route into the canonical anchor
        if canonical in SINGLETON_TYPES:
            canonical_uri = SINGLETON_TYPES[canonical]
            if summary:
                g.add((canonical_uri, EX.hasSummary,
                       Literal(summary, datatype=XSD.string)))
            llm_uri_map[suffix] = canonical_uri
            llm_skipped_singleton += 1
            llm_type_counts[canonical] = llm_type_counts.get(canonical, 0) + 1

            # Sandbox conditions still need their wiring
            if canonical == "AIRegulatorySandbox":
                pass  # nothing extra — conditions get wired in the conditions branch below
            continue

        sanitized = _sanitise_uri_suffix(suffix)
        instance_uri = EX[sanitized]
        llm_uri_map[suffix] = instance_uri

        g.add((instance_uri, RDF.type, type_iri))
        g.add((instance_uri, RDFS.label, Literal(suffix, lang="en")))
        if summary:
            g.add((instance_uri, EX.hasSummary,
                   Literal(summary, datatype=XSD.string)))

        # cq_targets and evidence_text are stored as datatype-string-only
        # annotations (not in the TBox, but useful for evaluation traceback)
        cq_targets = inst.get("cq_targets") or []
        if cq_targets:
            for cq in cq_targets:
                g.add((instance_uri, RDFS.comment,
                       Literal(f"cq_target: {cq}", lang="en")))
        evidence = inst.get("evidence_text") or ""
        if evidence:
            g.add((instance_uri, RDFS.comment,
                   Literal(f"evidence: {evidence}", lang="en")))

        # Article / paragraph references
        art_num, para_num, list_label = parse_paragraph_ref(para_ref)
        annex_num = parse_annex_ref(para_ref)

        if art_num:
            g.add((instance_uri, EX.hasArticleReference,
                   EX[f"Article_{art_num}"]))
            if para_num:
                g.add((instance_uri, EX.hasParagraphReference,
                       paragraph_uri(art_num, para_num, list_label)))
        elif isinstance(source_article, int):
            g.add((instance_uri, EX.hasArticleReference,
                   EX[f"Article_{source_article}"]))

        if annex_num:
            g.add((instance_uri, EX.hasAnnexReference,
                   EX[f"Annex_{annex_num}"]))
        elif isinstance(source_article, str) and source_article.startswith("annex_"):
            ann_id = source_article.split("_", 1)[1].upper()
            g.add((instance_uri, EX.hasAnnexReference, EX[f"Annex_{ann_id}"]))

        # Rule-based wiring by canonical type 
        if canonical in PROVIDER_OBLIGATION_TYPES:
            g.add((PROVIDER, EX.hasObligation, instance_uri))
            wirings_added += 1
            if canonical in GPAI_OBLIGATION_TYPES:
                if canonical in {"SystemicRiskGPAIObligation", "GPAISystemicRiskIncidentReport"}:
                    g.add((GPAI_SYSTEMIC_MODEL, EX.hasObligation, instance_uri))
                else:
                    g.add((GPAI_MODEL, EX.hasObligation, instance_uri))

        elif canonical in DEPLOYER_OBLIGATION_TYPES:
            g.add((DEPLOYER, EX.hasObligation, instance_uri))
            wirings_added += 1

        elif canonical in SME_OBLIGATION_TYPES:
            g.add((SME_STAKEHOLDER, EX.hasObligation, instance_uri))
            g.add((PROVIDER, EX.hasObligation, instance_uri))
            wirings_added += 1

        elif canonical in POWER_TYPES:
            g.add((AI_OFFICE, EX.hasPower, instance_uri))
            wirings_added += 1

        if canonical in SYSTEM_DIRECT_OBLIGATION_TYPES:
            for hr in high_risk_systems:
                g.add((hr, EX.hasObligation, instance_uri))

        if canonical in REPORTING_TARGET_DEFAULTS:
            target_name = REPORTING_TARGET_DEFAULTS[canonical]
            target_uri = AI_OFFICE if target_name == "AIOffice" else MARKET_SURVEILLANCE
            g.add((instance_uri, EX.hasReportingTarget, target_uri))

        if canonical and canonical.endswith("Condition"):
            # Sandbox conditions: Articles 57-63 are the sandbox articles.
            # v3 only wired Article 57, which was too narrow — the LLM
            # extracts conditions from 58, 59, 60, 62, 63 as well and
            # they all belong on the canonical sandbox instance.
            try:
                art_n_int = int(art_num) if art_num else None
            except (TypeError, ValueError):
                art_n_int = None
            src_int = source_article if isinstance(source_article, int) else None
            if (art_n_int is not None and 57 <= art_n_int <= 63) or \
               (src_int is not None and 57 <= src_int <= 63):
                g.add((SANDBOX, EX.hasCondition, instance_uri))
                art57_conditions.append(instance_uri)
            if art_num == "51" or (isinstance(source_article, int) and source_article == 51):
                g.add((GPAI_SYSTEMIC_MODEL, EX.hasCondition, instance_uri))
                art51_conditions.append(instance_uri)
            if art_num == "5" or (isinstance(source_article, int) and source_article == 5):
                if biometric_practice_uri is not None:
                    g.add((biometric_practice_uri, EX.hasCondition, instance_uri))
                art5_conditions.append(instance_uri)

        llm_type_counts[canonical] = llm_type_counts.get(canonical, 0) + 1
        llm_added += 1

    print(f"  LLM instances added (non-singleton):  {llm_added}")
    print(f"  LLM instances coalesced (singleton):  {llm_skipped_singleton}")
    print(f"  LLM instances skipped (unmappable):   {llm_skipped_unmapped}")
    print(f"  Wirings to bearers:                   {wirings_added}")
    print(f"  Conditions on Art 5 biometric:        {len(art5_conditions)}")
    print(f"  Conditions on GPAI systemic:          {len(art51_conditions)}")
    print(f"  Conditions on sandbox:                {len(art57_conditions)}")
    print("  Top instance types:")
    for t, n in sorted(llm_type_counts.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    {n:>4}  {t}")

    # 5. NER + regex enrichment ingestion 
    print("\n=== 5. NER + regex enrichments ===")
    ner_enrichments = ner_payload.get("enrichments", [])
    ner_added = 0
    ner_orphan_legs_minted = 0
    ner_skipped_subject_unknown = 0
    ner_predicate_counts = {}

    PREDICATE_MAP = {
        "hasDeadline":          (EX.hasDeadline,          "literal"),
        "hasFine":              (EX.hasFine,              "literal"),
        "hasMaximumFineRatio":  (EX.hasMaximumFineRatio,  "literal"),
        "hasArticleReference":  (EX.hasArticleReference,  "uri"),
        "cites":                (EX.cites,                "uri"),
    }

    DATATYPE_MAP = {
        "xsd:duration": XSD.duration,
        "xsd:decimal":  XSD.decimal,
        "xsd:string":   XSD.string,
    }

    # Build set of legislation URIs that already exist in the structured TTL
    # (for orphan detection). At THIS point we don't have the merged TTL yet,
    # so we mint orphan legislation defensively for any Legislation_* object
    # we haven't seen before in the HTML graph.
    seen_legislation_uris = set()

    for e in ner_enrichments:
        pred_str = e["predicate"]
        if pred_str not in PREDICATE_MAP:
            continue
        pred_uri, kind = PREDICATE_MAP[pred_str]

        # Resolve subject
        subj_str = e["subject"]
        subj_type = e.get("subject_type", "instance")
        if subj_type == "article":
            subj_uri = EX[subj_str]  # already "Article_N"
        else:
            # Look up via llm_uri_map first (canonical form), fall back to direct
            subj_uri = llm_uri_map.get(subj_str)
            if subj_uri is None:
                # Subject was not in LLM extraction — try the literal suffix.
                # If no triples are emitted on it, it'll dangle harmlessly.
                sanitised = _sanitise_uri_suffix(subj_str)
                subj_uri = EX[sanitised]
                # Verify it's known to our graph (has any outgoing triple)
                if not list(g.triples((subj_uri, None, None))):
                    ner_skipped_subject_unknown += 1
                    continue

        # Resolve object
        if kind == "literal":
            datatype = DATATYPE_MAP.get(e.get("object_datatype", "xsd:string"), XSD.string)
            obj = Literal(e["object"], datatype=datatype)
        else:
            obj_str = e["object"]
            obj_uri = EX[obj_str]
            obj = obj_uri
            # If this is a Legislation_* reference and we haven't seen it yet,
            # mint a minimal :EULegislation stub so the link doesn't dangle.
            if obj_str.startswith("Legislation_") and obj_uri not in seen_legislation_uris:
                seen_legislation_uris.add(obj_uri)
                # Only mint if the structural pipeline hasn't already declared
                # it (we don't know that here, so we always mint — duplicate
                # type triples are idempotent at merge time).
                g.add((obj_uri, RDF.type, EX.EULegislation))
                celex = obj_str.replace("Legislation_", "")
                g.add((obj_uri, RDFS.label, Literal(f"EU legislation {celex}", lang="en")))
                g.add((obj_uri, EX.hasCELEXNumber, Literal(celex, datatype=XSD.string)))
                ner_orphan_legs_minted += 1

        g.add((subj_uri, pred_uri, obj))
        ner_predicate_counts[pred_str] = ner_predicate_counts.get(pred_str, 0) + 1
        ner_added += 1

    print(f"  NER triples added:                {ner_added}")
    print(f"  NER subjects unknown (skipped):   {ner_skipped_subject_unknown}")
    print(f"  Orphan legislation stubs minted:  {ner_orphan_legs_minted}")
    print("  By predicate:")
    for p, n in sorted(ner_predicate_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {p}")

    # 6. Backstops 
    if biometric_practice_uri is not None and not art5_conditions:
        stub_cond = EX.necessity_condition_art5_biometric_stub
        g.add((stub_cond, RDF.type, EX.NecessityCondition))
        g.add((stub_cond, RDFS.label,
               Literal("Strict necessity for law enforcement use", lang="en")))
        g.add((stub_cond, EX.hasSummary,
               Literal("Real-time remote biometric identification by law "
                       "enforcement requires that the use is strictly "
                       "necessary for one of the objectives listed in "
                       "Article 5(1)(h).",
                       datatype=XSD.string)))
        g.add((stub_cond, EX.hasArticleReference, EX.Article_5))
        g.add((biometric_practice_uri, EX.hasCondition, stub_cond))
        print("  (backstop) added necessity condition stub on biometric practice")

    if not art51_conditions:
        stub_cond = EX.proportionality_condition_art51_stub
        g.add((stub_cond, RDF.type, EX.ProportionalityCondition))
        g.add((stub_cond, RDFS.label,
               Literal("GPAI systemic risk computational threshold "
                       "(Article 51)", lang="en")))
        g.add((stub_cond, EX.hasSummary,
               Literal("A general-purpose AI model is presumed to have "
                       "high impact capabilities — and thus systemic risk — "
                       "when the cumulative amount of computation used for "
                       "its training measured in floating point operations "
                       "is greater than 10^25.",
                       datatype=XSD.string)))
        g.add((stub_cond, EX.hasArticleReference, EX.Article_51))
        g.add((GPAI_SYSTEMIC_MODEL, EX.hasCondition, stub_cond))
        print("  (backstop) added proportionality condition stub on GPAI systemic model")

    # 7. Serialise 
    os.makedirs(os.path.dirname(OUTPUT_TTL), exist_ok=True)
    g.serialize(destination=OUTPUT_TTL, format="turtle")

    print()
    print(f"HTML layer TTL serialisation complete")
    print(f"  Total triples: {len(g)}")
    print(f"  Output:        {OUTPUT_TTL}")


if __name__ == "__main__":
    main()