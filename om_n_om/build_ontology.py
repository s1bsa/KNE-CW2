"""
Builds the EU AI Act compliance ontology (TBox) and writes it to
om_n_om/aiact_ontology.ttl.

Defines all custom classes, object properties, datatype properties, named
individuals, defined-class equivalence axioms, and disjointness axioms in
our namespace, plus embedded stubs of the external AIRO, DPV, and
DPV-AIAct classes we reference (avoids pulling in full owl:imports).
"""

from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, URIRef, XSD, BNode, BNode
import os

EX     = Namespace("https://example.org/eu-ai-act-compliance#")
AIRO   = Namespace("https://w3id.org/airo#")
AIACT  = Namespace("https://w3id.org/dpv/legal/eu/aiact#")
DPV    = Namespace("https://w3id.org/dpv#")
DCT    = Namespace("http://purl.org/dc/terms/")

# Source ontology IRIs (for rdfs:isDefinedBy provenance on stubs)
AIRO_IRI  = URIRef("https://w3id.org/airo")
AIACT_IRI = URIRef("https://w3id.org/dpv/legal/eu/aiact")
DPV_IRI   = URIRef("https://w3id.org/dpv")

g = Graph()
g.bind("",         EX)
g.bind("airo",     AIRO)
g.bind("eu-aiact", AIACT)
g.bind("dpv",      DPV)
g.bind("dct",      DCT)
g.bind("owl",      OWL)
g.bind("rdfs",     RDFS)
g.bind("xsd",      XSD)

# ONTOLOGY METADATA 

ONTOLOGY_IRI = URIRef("https://example.org/eu-ai-act-compliance")

for triple in [
    (ONTOLOGY_IRI, RDF.type,        OWL.Ontology),
    (ONTOLOGY_IRI, RDFS.label,      Literal("EU AI Act Compliance Ontology", lang="en")),
    (ONTOLOGY_IRI, RDFS.comment,    Literal(
        "An OWL 2 ontology extending AIRO (https://w3id.org/airo) and the DPV "
        "core ontology (https://w3id.org/dpv) to model obligations, regulatory "
        "powers, legal conditions, and document structure of Regulation (EU) "
        "2024/1689 (the EU AI Act). The DPV EU AI Act extension "
        "(https://w3id.org/dpv/legal/eu/aiact) is reused via direct IRI "
        "references rather than subclassing. CQ-driven design: every custom "
        "term is justified by at least one competency question, and every "
        "general extension by at least three. External terms are stubbed "
        "inline (with rdfs:isDefinedBy provenance) rather than imported, to "
        "avoid hierarchy pollution and OWL punning artefacts.",
        lang="en")),
    (ONTOLOGY_IRI, DCT.created,     Literal("2026-04-07", datatype=XSD.date)),
    (ONTOLOGY_IRI, DCT.license,     URIRef("https://creativecommons.org/licenses/by/4.0/")),
    (ONTOLOGY_IRI, OWL.versionInfo, Literal("3.3.0")),
    (ONTOLOGY_IRI, RDFS.seeAlso,    AIRO_IRI),
    (ONTOLOGY_IRI, RDFS.seeAlso,    DPV_IRI),
    (ONTOLOGY_IRI, RDFS.seeAlso,    AIACT_IRI),
]:
    g.add(triple)

# SECTION 1 — EMBEDDED STUBS OF EXTERNAL TERMS
# Each stub declares the external class as owl:Class and attributes it to its
# source ontology via rdfs:isDefinedBy.

external_classes = [
    # AIRO classes 
    (AIRO.AISystem,      "AI System (AIRO)",            AIRO_IRI, []),
    (AIRO.RiskConcept,   "Risk Concept (AIRO)",         AIRO_IRI, []),
    (AIRO.RiskControl,   "Risk Control (AIRO)",         AIRO_IRI, [AIRO.RiskConcept]),
    (EX.RiskLevel,       "Risk Level",                  EX,       [AIRO.RiskConcept]),
    (AIRO.Documentation, "Documentation (AIRO)",        AIRO_IRI, []),
    (AIRO.Regulation,    "Regulation (AIRO)",           AIRO_IRI, []),
    (EX.AreaOfApplication, "Area of Application",       EX,       []),
    (DPV.NaturalPerson, "Natural Person (DPV)", DPV_IRI, []),
    (AIRO.AISubject,    "AI Subject (AIRO)",    AIRO_IRI, []),

    # DPV core classes 
    (DPV.Obligation, "Obligation (DPV)", DPV_IRI, []),
    (DPV.Authority,  "Authority (DPV)",  DPV_IRI, []),

    # DPV EU AI Act classes
    (AIACT.ProhibitedAISystem,                     "Prohibited AI System (EU AI Act)",       AIACT_IRI, [AIRO.AISystem]),
    (AIACT.ProhibitedPractice,                     "Prohibited Practice (EU AI Act)",        AIACT_IRI, []),
    (AIACT.GeneralPurposeAIModel,                  "General Purpose AI Model (EU AI Act)",   AIACT_IRI, []),
    (EX.GeneralPurposeAIModelWithSystemicRisk,  "GPAI Model with Systemic Risk", EX, [AIACT.GeneralPurposeAIModel]),
    (AIACT.AIOperator,                             "AI Operator (EU AI Act)",                AIACT_IRI, []),
    (AIACT.AIProvider,                             "AI Provider (EU AI Act)",                AIACT_IRI, [AIACT.AIOperator]),
    (AIACT.AIDeployer,                             "AI Deployer (EU AI Act)",                AIACT_IRI, [AIACT.AIOperator]),
    (AIACT.TechnicalDocumentation,                 "Technical Documentation (EU AI Act)",    AIACT_IRI, [AIRO.Documentation]),
    (AIACT.ConformityAssessment,                   "Conformity Assessment (EU AI Act)",      AIACT_IRI, []),
    (AIACT.AIRegulatorySandbox,                    "AI Regulatory Sandbox (EU AI Act)",      AIACT_IRI, []),
]

for uri, label, source, parents in external_classes:
    g.add((uri, RDF.type, OWL.Class))
    g.add((uri, RDFS.label, Literal(label, lang="en")))
    if source != EX:
        g.add((uri, RDFS.isDefinedBy, source))
    for parent in parents:
        g.add((uri, RDFS.subClassOf, parent))

external_properties = [
    (AIRO.hasRisk,                "has risk (AIRO)",                  AIRO_IRI),
    (AIRO.hasRiskControl,         "has risk control (AIRO)",          AIRO_IRI),
    (AIRO.compliesWithRegulation, "complies with regulation (AIRO)",  AIRO_IRI),
    (AIRO.hasAISubject,           "has AI subject (AIRO)",            AIRO_IRI),
    (AIRO.hasDocumentation,       "has documentation (AIRO)",         AIRO_IRI),
    (DPV.hasLegalBasis,           "has legal basis (DPV)",            DPV_IRI),
    (EX.hasAreaOfApplication,     "has area of application",          EX),
    (EX.hasRiskLevel,             "has risk level",                   EX),
    (EX.hasProvider,              "has provider",                     EX),
    (EX.hasDeployer,              "has deployer",                     EX),
]

for uri, label, source in external_properties:
    g.add((uri, RDF.type, OWL.ObjectProperty))
    g.add((uri, RDFS.label, Literal(label, lang="en")))
    if source != EX:
        g.add((uri, RDFS.isDefinedBy, source))


# SECTION 2 — CUSTOM CLASSES

classes = [
    # Obligation hierarchy 
    {
        "name": "ConformityAssessmentObligation",
        "label": "Conformity Assessment Obligation",
        "comment": "An obligation requiring a high-risk AI system provider to undergo conformity assessment before placing the system on the market (Articles 16, 17, 43, 49, Annexes VI and VII).",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "InternalControlObligation",
        "label": "Internal Control Conformity Assessment Obligation",
        "comment": "Conformity assessment obligation discharged by the provider through an internal control procedure under Annex VI, without involvement of a notified body. Disjoint with :ThirdPartyAssessmentObligation — a high-risk AI system follows exactly one of the two pathways.",
        "subclass_of": [EX.ConformityAssessmentObligation],
    },
    {
        "name": "ThirdPartyAssessmentObligation",
        "label": "Third-Party Conformity Assessment Obligation",
        "comment": "Conformity assessment obligation requiring involvement of a notified body under the Annex VII procedure, mandatory for biometric AI systems and any system whose harmonised standards do not fully apply.",
        "subclass_of": [EX.ConformityAssessmentObligation],
    },
    {
        "name": "TransparencyObligation",
        "label": "Transparency Obligation",
        "comment": "An obligation requiring disclosure of information about an AI system's nature, capabilities, limitations, or AI-generated outputs (Articles 13, 26(8), 50).",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "GPAIObligation",
        "label": "GPAI Provider Obligation",
        "comment": "Parent class for obligations applicable to providers of general-purpose AI models (Articles 53, 54, 55, 56). Subdivided into general obligations applicable to all GPAI providers and additional obligations applicable only to providers of GPAI models with systemic risk.",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "GeneralGPAIObligation",
        "label": "General GPAI Obligation",
        "comment": "Obligation applicable to all general-purpose AI model providers regardless of systemic risk classification: technical documentation, downstream-information sharing, copyright policy, training-data summary (Articles 53, 54).",
        "subclass_of": [EX.GPAIObligation],
    },
    {
        "name": "SystemicRiskGPAIObligation",
        "label": "Systemic Risk GPAI Obligation",
        "comment": "Additional obligation applicable only to providers of GPAI models classified as posing systemic risk under Article 51: model evaluation, adversarial testing, incident reporting to the AI Office, and cybersecurity measures (Article 55).",
        "subclass_of": [EX.GPAIObligation],
    },
    {
        "name": "PostMarketMonitoringObligation",
        "label": "Post-Market Monitoring Obligation",
        "comment": "An obligation requiring providers to establish a proportionate post-market monitoring system to collect and review experience gained from deployed high-risk AI systems (Articles 9, 72).",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "WorkerNotificationObligation",
        "label": "Worker Notification Obligation",
        "comment": "An obligation requiring deployers to inform workers and their representatives before deploying a high-risk AI system in the workplace to monitor or supervise their performance (Article 26(7)).",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "FRIAObligation",
        "label": "Fundamental Rights Impact Assessment Obligation",
        "comment": "An obligation requiring specific deployer categories (public-law bodies, private entities providing public services, certain Annex III deployers) to assess fundamental-rights impacts before deploying a high-risk AI system (Article 27).",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "IncidentReportingObligation",
        "label": "Serious Incident Reporting Obligation",
        "comment": "Parent class for obligations to report serious incidents to a relevant authority within a specified timeframe. Subdivided by who must report (provider, deployer, GPAI systemic-risk provider) and to whom.",
        "subclass_of": [DPV.Obligation],
    },
    {
        "name": "ProviderIncidentReport",
        "label": "Provider Incident Report",
        "comment": "Obligation on a high-risk AI system provider to report serious incidents to the relevant national market surveillance authority within the deadlines set out in Article 73.",
        "subclass_of": [EX.IncidentReportingObligation],
    },
    {
        "name": "DeployerIncidentReport",
        "label": "Deployer Incident Report",
        "comment": "Obligation on a deployer of a high-risk AI system to report serious incidents to the relevant market surveillance authority and to inform the provider, under Article 26(5).",
        "subclass_of": [EX.IncidentReportingObligation],
    },
    {
        "name": "GPAISystemicRiskIncidentReport",
        "label": "GPAI Systemic-Risk Incident Report",
        "comment": "Obligation on a provider of a GPAI model with systemic risk to report serious incidents and possible corrective measures to the AI Office without undue delay, under Article 55.",
        "subclass_of": [EX.IncidentReportingObligation],
    },
    {
        "name": "SupportMeasureObligation",
        "label": "SME Support Measure Obligation",
        "comment": "An obligation on Member States to provide support measures (priority sandbox access, dedicated communication channels, reduced fees, tailored guidance) to SME and start-up providers (Article 62).",
        "subclass_of": [DPV.Obligation],
    },

    # Power hierarchy 
    {
        "name": "Power",
        "label": "Regulatory Power",
        "comment": "Parent class for legal competences held by regulatory bodies under the EU AI Act. The mirror of :Obligation: a Power is what an authority MAY do, an Obligation is what a regulated entity MUST do.",
    },
    {
        "name": "OversightPower",
        "label": "Oversight Power",
        "comment": "A power to monitor compliance and supervise the operation of regulated entities or AI systems (e.g. AI Office oversight of GPAI models under Articles 51-52, 88).",
        "subclass_of": [EX.Power],
    },
    {
        "name": "InvestigativePower",
        "label": "Investigative Power",
        "comment": "A power to request information, conduct evaluations, or carry out investigations of regulated entities (Articles 65, 74).",
        "subclass_of": [EX.Power],
    },
    {
        "name": "EnforcementPower",
        "label": "Enforcement Power",
        "comment": "A power to impose corrective measures, fines, or other sanctions for non-compliance (Articles 99-101). Optionally quantified via :hasFine and :hasMaximumFineRatio for monetary penalties.",
        "subclass_of": [EX.Power],
    },
    {
        "name": "AdvisoryPower",
        "label": "Advisory Power",
        "comment": "A power to issue guidance, opinions, or codes of practice without binding force (Articles 56, 66, 67).",
        "subclass_of": [EX.Power],
    },

    # Condition hierarchy
    {
        "name": "Condition",
        "label": "Legal Condition",
        "comment": "Parent class for legal conditions that gate permissions, exceptions, derogations, or sandbox participation under the EU AI Act. A Condition is the IF in 'IF X holds THEN Y is permitted/required'.",
    },
    {
        "name": "NecessityCondition",
        "label": "Necessity Condition",
        "comment": "A condition requiring that the action be strictly necessary for a specified legitimate purpose (e.g. real-time biometric identification only when no less intrusive means would suffice).",
        "subclass_of": [EX.Condition],
    },
    {
        "name": "ProportionalityCondition",
        "label": "Proportionality Condition",
        "comment": "A condition requiring that the action be proportionate to the objective pursued, balancing the intrusion against the public interest at stake.",
        "subclass_of": [EX.Condition],
    },
    {
        "name": "ProceduralCondition",
        "label": "Procedural Condition",
        "comment": "A condition imposing a procedural safeguard, such as prior judicial authorisation or third-party conformity assessment.",
        "subclass_of": [EX.Condition],
    },
    {
        "name": "PurposeCondition",
        "label": "Purpose Condition",
        "comment": "A condition limiting an action to specific legitimate purposes (e.g. biometric identification permitted only for victim search, terrorist threat prevention, or serious-crime suspect identification).",
        "subclass_of": [EX.Condition],
    },

    # Small standalone extensions
    {
        "name": "SMEProvider",
        "label": "SME Provider",
        "comment": "A small or medium-sized enterprise providing AI systems, entitled to specific support measures under Article 62. Modelled as a subclass of eu-aiact:AIProvider so all Provider properties (incl. obligations) apply.",
        "subclass_of": [AIACT.AIProvider],
    },
    {
        "name": "CEMarking",
        "label": "CE Marking",
        "comment": "A conformity marking affixed to a high-risk AI system indicating compliance with EU requirements (Articles 47, 48, 49). Optionally accompanied by a notified body identification number when third-party conformity assessment was used.",
        "subclass_of": [AIRO.Documentation],
    },

    # Document structure 
    {
        "name": "LegalText",
        "label": "Legal Text",
        "comment": "Superclass grouping the structural units of the EU AI Act's legislative text: Articles, Annexes, Paragraphs, and Recitals. Provides a common type for properties that may reference any textual unit of the regulation.",
    },
    {
        "name": "Article",
        "label": "Article",
        "comment": "A numbered article within the EU AI Act, representing a discrete legal provision of the regulation.",
        "subclass_of": [EX.LegalText],
    },
    {
        "name": "Annex",
        "label": "Annex",
        "comment": "A numbered annex of the EU AI Act, containing supplementary provisions (e.g. Annex I harmonised legislation, Annex III high-risk areas, Annexes VI/VII conformity assessment procedures).",
        "subclass_of": [EX.LegalText],
    },
    {
        "name": "Paragraph",
        "label": "Paragraph",
        "comment": "A numbered or lettered paragraph within an Article or Annex, carrying the primary textual content of a legal provision.",
        "subclass_of": [EX.LegalText],
    },
    {
        "name": "Recital",
        "label": "Recital",
        "comment": "A numbered recital from the preamble of the EU AI Act, providing the rationale for the operative provisions.",
        "subclass_of": [EX.LegalText],
    },

    # Regulation metadata
    {
        "name": "AIActRegulation",
        "label": "AI Act Regulation",
        "comment": "A binding legislative act governing AI systems, represented as a subclass of airo:Regulation and used to associate AI systems with their regulatory context.",
        "subclass_of": [AIRO.Regulation],
    },
    {
        "name": "EULegislation",
        "label": "EU Legislation",
        "comment": "A European Union legislative act cited or amended by the EU AI Act, including regulations, directives, treaties, and institutional opinions.",
        "subclass_of": [AIRO.Regulation],
    },
    {
        "name": "ProvisionDeadline",
        "label": "Provision Deadline",
        "comment": "An intermediate node bundling a date and an article reference for a regulation-level temporal provision of the EU AI Act.",
    },
    {
        "name": "ComplianceDeadlineProvision",
        "label": "Compliance Deadline Provision",
        "comment": "A regulation-level deadline by which specific provisions of the EU AI Act must be complied with, each tied to a specific article.",
        "subclass_of": [EX.ProvisionDeadline],
    },
    {
        "name": "EntryIntoForceProvision",
        "label": "Entry Into Force Provision",
        "comment": "A date on which a specific part of the EU AI Act becomes legally active, referencing the relevant article (typically Art. 113).",
        "subclass_of": [EX.ProvisionDeadline],
    },
    {
        "name": "EntryIntoForceDate",
        "label": "Entry Into Force Date",
        "comment": "A specific date on which a provision of the EU AI Act enters into force, as extracted from the EUR-Lex CELLAR XML metadata.",
        "subclass_of": [EX.ProvisionDeadline],
    },
    {
        "name": "ConformityAssessmentBody",
        "label": "Conformity Assessment Body",
        "comment": "A body designated and notified under the EU AI Act to carry out third-party conformity assessment activities for high-risk AI systems (Articles 29–39). Modelled as a subclass of dpv:Authority.",
        "subclass_of": [DPV.Authority],
    },
    {
        "name": "NotifiedBody",
        "label": "Notified Body",
        "comment": "A conformity assessment body that has been formally notified under Article 30 of the EU AI Act because it meets all the substantive requirements of Article 31 (independence, competence, impartiality, resources, etc.). Defined class: any ConformityAssessmentBody that meets the full set of twelve requirements is classified as a NotifiedBody.",
        "subclass_of": [EX.ConformityAssessmentBody],
    },
    {
        "name": "Requirement",
        "label": "Requirement",
        "comment": "A substantive requirement that a conformity assessment body must meet to be designated and notified under the EU AI Act (e.g. independence, competence, impartiality, confidentiality, and operational requirements set out in Article 31).",
    },

    # Required-component class hierarchy
    {
        "name": "RequiredComponent",
        "label": "Required Component",
        "comment": "Parent class for fine-grained required parts of compliance artefacts under the EU AI Act. Subdivided by the kind of artefact each component belongs to. Used by the rule-based extraction layer to decompose enumerated annex content (e.g. Annex IV documentation requirements, Annex VIII registration fields) into addressable individuals rather than collapsing them into a single text blob.",
    },
    {
        "name": "DocumentationComponent",
        "label": "Documentation Component",
        "comment": "A required component of a technical documentation artefact, corresponding to one bullet of Annex IV (e.g. 'general description of the AI system', 'detailed information about the system's monitoring, functioning and control'). Each high-risk AI system's technical documentation must contain all required documentation components.",
        "subclass_of": [EX.RequiredComponent, AIRO.Documentation],
    },
    {
        "name": "RegistrationField",
        "label": "Registration Field",
        "comment": "A required field in the EU database registration record for a high-risk AI system, as enumerated in Annex VIII (e.g. provider name, AI system trade name, intended purpose, status). Each provider's registration record must populate all required registration fields.",
        "subclass_of": [EX.RequiredComponent, AIRO.Documentation],
    },
    {
        "name": "ConformityAssessmentStep",
        "label": "Conformity Assessment Step",
        "comment": "A step in the conformity assessment procedure as enumerated in Annex VI (internal control procedure) or Annex VII (third-party assessment procedure). Models the procedural decomposition of the assessment activity itself, distinct from the obligation to undergo it.",
        "subclass_of": [EX.RequiredComponent],
    },
    {
        "name": "TestingPlanField",
        "label": "Testing Plan Field",
        "comment": "A required field in a real-world testing plan for high-risk AI systems, as enumerated in Annex IX. Tied to the regulatory sandbox and real-world testing provisions of Articles 57–60.",
        "subclass_of": [EX.RequiredComponent, AIRO.Documentation],
    },
    {
        "name": "CEMarkingComponent",
        "label": "CE Marking Component",
        "comment": "A required visible or structural component of the CE marking affixed to a high-risk AI system, as enumerated in Article 48 (e.g. the CE marking itself, the notified body identification number where applicable, the provider's name and address).",
        "subclass_of": [EX.RequiredComponent],
    },
]


def _add_class(graph, cls_dict):
    cls_uri = EX[cls_dict["name"]]
    graph.add((cls_uri, RDF.type, OWL.Class))
    graph.add((cls_uri, RDFS.label, Literal(cls_dict["label"], lang="en")))
    graph.add((cls_uri, RDFS.comment, Literal(cls_dict["comment"], lang="en")))
    for parent in (cls_dict.get("subclass_of") or []):
        graph.add((cls_uri, RDFS.subClassOf, parent))
    for disjoint in (cls_dict.get("disjoint_with") or []):
        graph.add((cls_uri, OWL.disjointWith, disjoint))

for cls in classes:
    _add_class(g, cls)

# DISJOINTNESS 
g.add((EX.InternalControlObligation, OWL.disjointWith, EX.ThirdPartyAssessmentObligation))

# EQUIVALENT CLASS AXIOMS 

def _rdf_list(graph, items):
    """Build an RDF collection (rdf:first / rdf:rest / rdf:nil) and return its head node."""
    if not items:
        return RDF.nil
    head = BNode()
    current = head
    for i, item in enumerate(items):
        graph.add((current, RDF.first, item))
        if i == len(items) - 1:
            graph.add((current, RDF.rest, RDF.nil))
        else:
            nxt = BNode()
            graph.add((current, RDF.rest, nxt))
            current = nxt
    return head

def _has_value_restriction(graph, prop, value):
    """Build an owl:Restriction with owl:hasValue and return its node."""
    r = BNode()
    graph.add((r, RDF.type, OWL.Restriction))
    graph.add((r, OWL.onProperty, prop))
    graph.add((r, OWL.hasValue, value))
    return r

def _intersection_class(graph, members):
    """Build an anonymous owl:Class with owl:intersectionOf and return its node."""
    c = BNode()
    graph.add((c, RDF.type, OWL.Class))
    graph.add((c, OWL.intersectionOf, _rdf_list(graph, members)))
    return c

# HighRiskAISystem ≡ AISystem ⊓ (hasRiskLevel value HighRisk)

_hras_members = [
    AIRO.AISystem,
    _has_value_restriction(g, EX.hasRiskLevel, EX.HighRisk),
]
g.add((AIACT.HighRiskAISystem, OWL.equivalentClass, _intersection_class(g, _hras_members)))

# NotifiedBody ≡ ConformityAssessmentBody ⊓ (meetsRequirement value R1) ⊓ ... ⊓ (meetsRequirement value R12)

_nb_requirements = [
    EX.OrganisationalRequirement,
    EX.QualityManagementRequirement,
    EX.ResourceRequirement,
    EX.ProcessRequirement,
    EX.CybersecurityRequirement,
    EX.IndependenceRequirement,
    EX.ObjectivityRequirement,
    EX.ImpartialityRequirement,
    EX.ProfessionalIntegrityRequirement,
    EX.CompetenceRequirement,
    EX.ConfidentialityRequirement,
    EX.LiabilityInsuranceRequirement,
]
_nb_members = [EX.ConformityAssessmentBody] + [
    _has_value_restriction(g, EX.meetsRequirement, req) for req in _nb_requirements
]
g.add((EX.NotifiedBody, OWL.equivalentClass, _intersection_class(g, _nb_members)))

# SECTION 3 — NAMED INDIVIDUALS 

individuals = [
    {
        "name": "ProviderStakeholder",
        "label": "Provider (stakeholder role)",
        "comment": "Named individual representing the provider role under the EU AI Act. Used as the subject of obligation triples linking all provider-applicable obligations.",
        "types": [AIACT.AIProvider],
    },
    {
        "name": "DeployerStakeholder",
        "label": "Deployer (stakeholder role)",
        "comment": "Named individual representing the deployer role under the EU AI Act. Used as the subject of obligation triples linking all deployer-applicable obligations.",
        "types": [AIACT.AIDeployer],
    },
    {
        "name": "AIOffice",
        "label": "AI Office",
        "comment": "Named individual representing the AI Office established under the EU AI Act. Acts as a central authority for oversight, coordination, and enforcement activities referenced throughout the Regulation.",
        "types": [DPV.Authority],
    },
    {
        "name": "HighRisk",
        "label": "High Risk",
        "comment": "Named individual representing the high-risk level under the EU AI Act. Used as the filler in the equivalent-class definition of eu-aiact:HighRiskAISystem.",
        "types": [EX.RiskLevel],
    },
    {
        "name": "OrganisationalRequirement",
        "label": "Organisational Requirement",
        "comment": "Requirement concerning the organisational structure of a conformity assessment body under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "QualityManagementRequirement",
        "label": "Quality Management Requirement",
        "comment": "Requirement concerning the quality management system of a conformity assessment body under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ResourceRequirement",
        "label": "Resource Requirement",
        "comment": "Requirement concerning the human, technical, and financial resources a conformity assessment body must possess under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ProcessRequirement",
        "label": "Process Requirement",
        "comment": "Requirement concerning the processes and procedures a conformity assessment body must follow under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "CybersecurityRequirement",
        "label": "Cybersecurity Requirement",
        "comment": "Requirement concerning the cybersecurity posture of a conformity assessment body under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "IndependenceRequirement",
        "label": "Independence Requirement",
        "comment": "Requirement that a conformity assessment body be independent of the entities it assesses, under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ObjectivityRequirement",
        "label": "Objectivity Requirement",
        "comment": "Requirement that a conformity assessment body carry out its activities objectively, under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ImpartialityRequirement",
        "label": "Impartiality Requirement",
        "comment": "Requirement that a conformity assessment body act impartially in its assessment activities, under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ProfessionalIntegrityRequirement",
        "label": "Professional Integrity Requirement",
        "comment": "Requirement that staff of a conformity assessment body act with professional integrity, under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "CompetenceRequirement",
        "label": "Competence Requirement",
        "comment": "Requirement that a conformity assessment body possess the technical competence needed for its assessment activities, under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "ConfidentialityRequirement",
        "label": "Confidentiality Requirement",
        "comment": "Requirement that a conformity assessment body observe confidentiality obligations under Article 31.",
        "types": [EX.Requirement],
    },
    {
        "name": "LiabilityInsuranceRequirement",
        "label": "Liability Insurance Requirement",
        "comment": "Requirement that a conformity assessment body hold adequate liability insurance, under Article 31.",
        "types": [EX.Requirement],
    },
]

for ind in individuals:
    uri = EX[ind["name"]]
    g.add((uri, RDF.type, OWL.NamedIndividual))
    for t in ind["types"]:
        g.add((uri, RDF.type, t))
    g.add((uri, RDFS.label, Literal(ind["label"], lang="en")))
    g.add((uri, RDFS.comment, Literal(ind["comment"], lang="en")))

# SECTION 4 — CUSTOM OBJECT PROPERTIES

object_properties = [
    {   
        "name": "hasObligation",
        "label": "has obligation",
        "comment": "Links a regulated entity (provider, deployer, AI system, GPAI model, Member State) to an obligation it must fulfil under the EU AI Act. Sub-property of dpv:hasLegalBasis to inherit DPV's legal-grounding semantics.",
        "domain": None,
        "range":  DPV.Obligation,
        "subproperty_of": DPV.hasLegalBasis,
    },
    {   
        "name": "hasReportingTarget",
        "label": "has reporting target",
        "comment": "Links an incident-reporting obligation to the authority that receives the report (e.g. AI Office for GPAI systemic-risk incidents, Market Surveillance Authority for high-risk system incidents). Functional: each obligation has exactly one designated target authority.",
        "domain": EX.IncidentReportingObligation,
        "range":  DPV.Authority,
        "characteristics": [OWL.FunctionalProperty],
    },
    {   
        "name": "requiresControl",
        "label": "requires control",
        "comment": "Links an obligation to a risk control whose implementation it mandates. Sub-property of airo:hasRiskControl, scoped to the legal-obligation context. Used to express, e.g., that a post-market monitoring obligation requires the implementation of specific monitoring controls.",
        "domain": DPV.Obligation,
        "range":  AIRO.RiskControl,
        "subproperty_of": AIRO.hasRiskControl,
    },
    {   
        "name": "hasPower",
        "label": "has power",
        "comment": "Links a regulatory authority to a power it holds under the EU AI Act.",
        "domain": DPV.Authority,
        "range":  EX.Power,
    },
    {   
        "name": "hasCondition",
        "label": "has condition",
        "comment": "Links an obligation, prohibition, exception, sandbox permission, or compliance artefact to a legal condition that must hold for it to apply (e.g. necessity, proportionality, prior judicial authorisation, purpose limitation).",
        "domain": None,
        "range":  EX.Condition,
    },
    {   
        "name": "hasReference",
        "label": "has reference",
        "comment": "Links any entity (obligation, power, condition, risk control, requirement, etc.) to a unit of the EU AI Act's legislative text that grounds, defines, or justifies it. Parent of the four structural sub-properties hasArticleReference, hasAnnexReference, hasParagraphReference, and hasRecitalReference. Also used by the NER+regex enrichment layer to express article-to-article cross-references found inside paragraph text (e.g. when an obligation summary contains 'as referred to in Article 43').",
        "domain": None,
        "range":  EX.LegalText,
    },
    {
        "name": "hasArticleReference",
        "label": "has article reference",
        "comment": "Links an entity to a specific Article of the EU AI Act. Sub-property of :hasReference, narrowed to Article.",
        "domain": None,
        "range":  EX.Article,
        "subproperty_of": EX.hasReference,
    },
    {
        "name": "hasAnnexReference",
        "label": "has annex reference",
        "comment": "Links an entity to a specific Annex of the EU AI Act. Sub-property of :hasReference, narrowed to Annex.",
        "domain": None,
        "range":  EX.Annex,
        "subproperty_of": EX.hasReference,
    },
    {
        "name": "hasParagraphReference",
        "label": "has paragraph reference",
        "comment": "Links an entity to a specific Paragraph within an Article or Annex of the EU AI Act. Sub-property of :hasReference, narrowed to Paragraph.",
        "domain": None,
        "range":  EX.Paragraph,
        "subproperty_of": EX.hasReference,
    },
    {
        "name": "hasRecitalReference",
        "label": "has recital reference",
        "comment": "Links an entity to a specific Recital in the preamble of the EU AI Act. Sub-property of :hasReference, narrowed to Recital.",
        "domain": None,
        "range":  EX.Recital,
        "subproperty_of": EX.hasReference,
    },
    {
        "name": "isRegulatedBy",
        "label": "is regulated by",
        "comment": "Associates an AI system or obligation with the legislative instrument that governs it.",
        "domain": None,
        "range":  EX.AIActRegulation,
        "subproperty_of": AIRO.compliesWithRegulation,
    },
    {
        "name": "hasComplianceProvision",
        "label": "has compliance provision",
        "comment": "Links the AI Act regulation to its compliance deadline provisions.",
        "domain": EX.AIActRegulation,
        "range":  EX.ComplianceDeadlineProvision,
    },
    {
        "name": "hasEntryIntoForceProvision",
        "label": "has entry into force provision",
        "comment": "Links the AI Act regulation to its entry-into-force provisions.",
        "domain": EX.AIActRegulation,
        "range":  EX.EntryIntoForceProvision,
    },
    {
        "name": "cites",
        "label": "cites",
        "comment": "Links a regulation to other legislation that it cites.",
        "domain": None,
        "range":  EX.EULegislation,
    },
    {
        "name": "amends",
        "label": "amends",
        "comment": "Links a regulation to legislation that it amends.",
        "domain": EX.AIActRegulation,
        "range":  EX.EULegislation,
    },
    {
        "name": "createdBy",
        "label": "created by",
        "comment": "Links a regulation to the EU institution that adopted it.",
        "domain": EX.AIActRegulation,
        "range":  DPV.Authority,
    },
    {
        "name": "meetsRequirement",
        "label": "meets requirement",
        "comment": "Links a conformity assessment body to a substantive requirement (independence, competence, impartiality, etc.) it must satisfy to be designated and notified under Article 31 of the EU AI Act.",
        "domain": EX.ConformityAssessmentBody,
        "range":  EX.Requirement,
    },

    # Required-component object properties

    {
        "name": "hasRequiredComponent",
        "label": "has required component",
        "comment": "Links a compliance artefact (TechnicalDocumentation, CEMarking, registration record, conformity assessment procedure, testing plan) to one of its required components, as enumerated in the relevant annex (IV, VI, VII, VIII, IX). Inverse of :hasComponentOf. Domain and range are intentionally unconstrained so the property can be used uniformly across all artefact-component pairings.",
        "domain": None,
        "range":  EX.RequiredComponent,
        "inverse_of": None,  # set below after both properties exist
    },
    {
        "name": "hasComponentOf",
        "label": "has component of",
        "comment": "Inverse of :hasRequiredComponent. Links a required component to the compliance artefact it belongs to. Provided to enable symmetric SPARQL traversal in both directions (artefact → components and component → artefact).",
        "domain": EX.RequiredComponent,
        "range":  None,
        "inverse_of": EX.hasRequiredComponent,
    },
]


def _add_object_property(graph, prop_dict):
    prop_uri = EX[prop_dict["name"]]
    graph.add((prop_uri, RDF.type, OWL.ObjectProperty))
    graph.add((prop_uri, RDFS.label, Literal(prop_dict["label"], lang="en")))
    graph.add((prop_uri, RDFS.comment, Literal(prop_dict["comment"], lang="en")))
    if prop_dict.get("domain"):
        graph.add((prop_uri, RDFS.domain, prop_dict["domain"]))
    if prop_dict.get("range"):
        graph.add((prop_uri, RDFS.range, prop_dict["range"]))
    if prop_dict.get("subproperty_of"):
        graph.add((prop_uri, RDFS.subPropertyOf, prop_dict["subproperty_of"]))
    for char in (prop_dict.get("characteristics") or []):
        graph.add((prop_uri, RDF.type, char))
    if prop_dict.get("inverse_of"):
        graph.add((prop_uri, OWL.inverseOf, prop_dict["inverse_of"]))

for prop in object_properties:
    _add_object_property(g, prop)

# SECTION 5 — CUSTOM DATATYPE PROPERTIES

datatype_properties = [
    {
        "name": "hasSummary",
        "label": "has summary",
        "comment": "The summary or descriptive text of a unit of the EU AI Act's legislative text (Article, Annex, Paragraph, or Recital). The primary text-carrying datatype property used across all CQs to ground the KG in the legislative text and the artificialintelligenceact.eu plain-language summaries.",
        "domain": EX.LegalText,
        "range":  XSD.string,
    },
    {
        "name": "hasCellarURI",
        "label": "has Cellar URI",
        "comment": "The CELLAR repository URI for the regulation. Declared as ObjectProperty because the pipeline outputs bare URIs (not quoted xsd:anyURI literals).",
        "domain": EX.AIActRegulation,
        "range":  XSD.string,
    },
    {
        "name": "hasSourceURL",
        "label": "has source URL",
        "comment": "The source URL on EUR-Lex of a unit of the EU AI Act's legislative text (Article, Annex, Paragraph, or Recital). Declared as ObjectProperty because the pipeline outputs bare URIs.",
        "domain": EX.LegalText,
        "range":  XSD.string,
    },
    {   
        "name": "hasDeadline",
        "label": "has deadline",
        "comment": "The maximum permitted time within which an obligation must be discharged (e.g. 15 days for high-risk system incident reports under Art. 73, immediate for GPAI systemic-risk incidents under Art. 55). Functional: a single obligation has at most one deadline.",
        "domain": DPV.Obligation,
        "range":  XSD.duration,
        "characteristics": [OWL.FunctionalProperty],
    },
    {
        "name": "hasComplianceDeadline",
        "label": "has compliance deadline",
        "comment": "The date by which a provider or deployer must fulfil a given obligation under the EU AI Act's phased entry-into-force schedule.",
        "domain": DPV.Obligation,
        "range":  XSD.date,
    },
    {
        "name": "hasEffectiveDate",
        "label": "has effective date",
        "comment": "The date on which a provision of the EU AI Act becomes effective.",
        "domain": EX.EntryIntoForceDate,
        "range":  XSD.date,
    },
    {
        "name": "hasModifiedLocation",
        "label": "has modified location",
        "comment": "A string describing the specific location (article, paragraph, annex point) within an amended legislative act that is modified.",
        "domain": EX.EULegislation,
        "range":  XSD.string,
    },
    {
        "name": "hasProvisionDate",
        "label": "has provision date",
        "comment": "The date associated with a provision deadline.",
        "domain": EX.ProvisionDeadline,
        "range":  XSD.date,
    },
    {
        "name": "hasCELEXNumber",
        "label": "has CELEX number",
        "comment": "The CELEX number uniquely identifying a legal act in EUR-Lex.",
        "domain": EX.AIActRegulation,
        "range":  XSD.string,
    },
    {
        "name": "hasOJReference",
        "label": "has OJ reference",
        "comment": "The Official Journal reference for a legal act.",
        "domain": EX.AIActRegulation,
        "range":  XSD.string,
    },
    {
        "name": "hasFine",
        "label": "has fine",
        "comment": "The maximum monetary fine an enforcement power may impose, expressed in euros (e.g. 35000000 for the maximum administrative fine under Article 99(3) for prohibited-practice infringements). Attached to :EnforcementPower instances by the NER+regex enrichment layer.",
        "domain": EX.EnforcementPower,
        "range":  XSD.decimal,
    },
    {
        "name": "hasMaximumFineRatio",
        "label": "has maximum fine ratio",
        "comment": "The maximum fine an enforcement power may impose, expressed as a fraction of the offender's worldwide annual turnover (e.g. 0.07 for '7% of total worldwide annual turnover' under Article 99(3)). Attached to :EnforcementPower instances by the NER+regex enrichment layer alongside the absolute :hasFine value.",
        "domain": EX.EnforcementPower,
        "range":  XSD.decimal,
    },
]


def _add_datatype_property(graph, prop_dict):
    prop_uri = EX[prop_dict["name"]]
    graph.add((prop_uri, RDF.type, OWL.DatatypeProperty))
    graph.add((prop_uri, RDFS.label, Literal(prop_dict["label"], lang="en")))
    graph.add((prop_uri, RDFS.comment, Literal(prop_dict["comment"], lang="en")))
    if prop_dict.get("domain"):
        graph.add((prop_uri, RDFS.domain, prop_dict["domain"]))
    if prop_dict.get("range"):
        graph.add((prop_uri, RDFS.range, prop_dict["range"]))
    for char in (prop_dict.get("characteristics") or []):
        graph.add((prop_uri, RDF.type, char))

for prop in datatype_properties:
    _add_datatype_property(g, prop)

# SERIALISE

output_file = "om_n_om/aiact_ontology.ttl"
os.makedirs(os.path.dirname(output_file), exist_ok=True)
g.serialize(destination=output_file, format="turtle")

# Counts
custom_classes = sum(
    1 for s in g.subjects(RDF.type, OWL.Class)
    if str(s).startswith(str(EX))
)
stub_classes = sum(
    1 for s in g.subjects(RDF.type, OWL.Class)
    if not str(s).startswith(str(EX))
)
custom_obj_props = sum(
    1 for s in g.subjects(RDF.type, OWL.ObjectProperty)
    if str(s).startswith(str(EX))
)
stub_obj_props = sum(
    1 for s in g.subjects(RDF.type, OWL.ObjectProperty)
    if not str(s).startswith(str(EX))
)
custom_dt_props = sum(
    1 for s in g.subjects(RDF.type, OWL.DatatypeProperty)
    if str(s).startswith(str(EX))
)
named_inds     = len(list(g.subjects(RDF.type, OWL.NamedIndividual)))
functional     = len(list(g.subjects(RDF.type, OWL.FunctionalProperty)))
inv_functional = len(list(g.subjects(RDF.type, OWL.InverseFunctionalProperty)))
inverse_pairs  = len(list(g.triples((None, OWL.inverseOf, None))))
disjointness   = len(list(g.triples((None, OWL.disjointWith, None))))

print(f"Ontology serialised to '{output_file}'")
print(f"  Custom classes:           {custom_classes}")
print(f"  Stub (external) classes:  {stub_classes}")
print(f"  Custom object properties: {custom_obj_props}")
print(f"  Stub (external) object properties: {stub_obj_props}")
print(f"  Custom datatype properties: {custom_dt_props}")
print(f"  Named individuals:        {named_inds}")
print(f"  Functional properties:    {functional}")
print(f"  Inverse-functional:       {inv_functional}")
print(f"  Inverse-of axioms:        {inverse_pairs}")
print(f"  Disjointness axioms:      {disjointness}")
print(f"  Total triples:            {len(g)}")