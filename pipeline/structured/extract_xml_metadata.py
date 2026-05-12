"""
Parses the EUR-Lex CELLAR XML for Regulation (EU) 2024/1689 and extracts
structured bibliographic metadata into JSON for downstream SPARQL Anything
CONSTRUCT mapping.

Extracts: regulation identifiers (CELEX, ELI, OJ, CELLAR URI), compliance
deadlines, entry-into-force dates, creating institutions, cited legislation,
and amended legislation. Each date and citation entry is annotated with
the article references it applies to.

Output: data/structured/eu_ai_act_metadata.json
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
XML_PATH = REPO_ROOT / "data" / "structured" / "eu_ai_act_32024R1689.xml"
OUT_PATH = REPO_ROOT / "data" / "structured" / "eu_ai_act_metadata.json"


def extract_identifiers(work):
    """Extract the regulation's own CELEX, ELI, and OJ identifiers."""
    identifiers = {}

    # take from top-level SAMEAS to avoid EMBEDDED_NOTICE duplicates
    for sameas in work.findall("SAMEAS"):
        uri = sameas.find("URI")
        if uri is not None:
            typ = uri.find("TYPE")
            ident = uri.find("IDENTIFIER")
            if typ is not None and ident is not None:
                if typ.text == "celex":
                    identifiers["celex"] = ident.text
                elif typ.text == "eli":
                    identifiers["eli"] = ident.text
                elif typ.text == "oj":
                    identifiers["oj"] = ident.text

    uri_el = work.find("URI")
    if uri_el is not None:
        val = uri_el.find("VALUE")
        if val is not None:
            identifiers["cellar_uri"] = val.text

    eli = work.find("RESOURCE_LEGAL_ELI")
    if eli is not None:
        val = eli.find("VALUE")
        if val is not None:
            identifiers["eli_canonical"] = val.text

    return identifiers


def parse_article_refs(annotation):
    """Extract article references from ANNOTATION elements."""
    if annotation is None:
        return []

    refs = []
    article_pattern = r"(?:ART|AR)\}?\s*(\d+)(?:\.\d+)?"

    comment = annotation.find("COMMENT_ON_DATE")
    if comment is not None and comment.text:
        refs.extend(re.findall(article_pattern, comment.text))

    modified = annotation.find("REFERENCE_TO_MODIFIED_LOCATION")
    if modified is not None and modified.text:
        refs.extend(re.findall(article_pattern, modified.text))

    return list(dict.fromkeys(refs))


def extract_dates(work, tag):
    """Extract date entries (deadlines or entry-into-force) with article refs."""
    dates = []
    for el in work.findall(tag):
        value = el.find("VALUE")
        if value is None:
            continue
        entry = {"date": value.text}

        annotation = el.find("ANNOTATION")
        refs = parse_article_refs(annotation)
        if refs:
            entry["article_references"] = refs

        dates.append(entry)

    return dates


def extract_legislation_refs(work, tag):
    """Extract CELEX IDs and EUR-Lex URIs from WORK_CITES_WORK or AMENDS elements."""
    refs = []
    seen = set()

    for el in work.findall(tag):
        entry = {}

        uri = el.find("URI")
        if uri is not None:
            val = uri.find("VALUE")
            if val is not None:
                entry["cellar_uri"] = val.text

        for sameas in el.findall("SAMEAS"):
            s_uri = sameas.find("URI")
            if s_uri is not None:
                s_typ = s_uri.find("TYPE")
                s_ident = s_uri.find("IDENTIFIER")
                if s_typ is not None and s_ident is not None:
                    if s_typ.text == "celex":
                        entry["celex"] = s_ident.text
                    elif s_typ.text == "eli":
                        entry["eli"] = s_ident.text

        annotation = el.find("ANNOTATION")
        refs_in_annotation = parse_article_refs(annotation)
        if refs_in_annotation:
            entry["article_references"] = refs_in_annotation

        if annotation is not None:
            modified = annotation.find("REFERENCE_TO_MODIFIED_LOCATION")
            if modified is not None and modified.text:
                entry["modified_location"] = modified.text

        celex = entry.get("celex", "")
        if celex and celex not in seen:
            seen.add(celex)
            refs.append(entry)
        elif not celex and entry.get("cellar_uri"):
            refs.append(entry)

    return refs


def extract_created_by(work):
    """Extract institutions responsible for creating the regulation."""
    created_by = []

    for el in work.findall("CREATED_BY"):
        entry = {}

        label = el.find("PREFLABEL")
        if label is not None:
            entry["label"] = label.text

        ident = el.find("IDENTIFIER")
        if ident is not None:
            entry["identifier"] = ident.text

        uri = el.find("URI")
        if uri is not None:
            val = uri.find("VALUE")
            if val is not None:
                entry["uri"] = val.text

        if entry:
            created_by.append(entry)

    return created_by


def main():
    if not XML_PATH.exists():
        print(f"ERROR: XML file not found at {XML_PATH}")
        return

    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    work = root.find("WORK")

    if work is None:
        print("ERROR: No <WORK> element found in XML")
        return

    metadata = {
        "source": "EUR-Lex CELLAR metadata",
        "source_file": "eu_ai_act_32024R1689.xml",
        "regulation": extract_identifiers(work),
        "deadlines": extract_dates(work, "RESOURCE_LEGAL_DATE_DEADLINE"),
        "entry_into_force": extract_dates(work, "RESOURCE_LEGAL_DATE_ENTRY-INTO-FORCE"),
        "created_by": extract_created_by(work),
        "cites": extract_legislation_refs(work, "WORK_CITES_WORK"),
        "amends": extract_legislation_refs(work, "RESOURCE_LEGAL_AMENDS_RESOURCE_LEGAL"),
    }

    # Summary
    print(f"Regulation: {metadata['regulation'].get('celex', '?')}")
    print(f"Deadlines:        {len(metadata['deadlines'])}")
    print(f"Entry-into-force: {len(metadata['entry_into_force'])}")
    print(f"Created-by:       {len(metadata['created_by'])}")
    print(f"Cites:            {len(metadata['cites'])}")
    print(f"Amends:           {len(metadata['amends'])}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\nOutput: {OUT_PATH}")


if __name__ == "__main__":
    main()
