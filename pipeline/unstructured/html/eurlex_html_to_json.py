"""
Parses the saved EUR-Lex HTML of the EU AI Act into a structured JSON
representation of all 113 articles and 13 annexes.

For each article and annex, extracts the title, the flat text body, and
a `content_items` list with paragraph numbers, list labels, and a
canonical reference string (e.g. "Article 5(1)(a)", "Annex VIII(A)(1)").
This is the structural parser only — no entity extraction happens here.

Input:  data/unstructured/eu_ai_act_content.html
Output: data/unstructured/eu_ai_act_articles.json
"""

from html.parser import HTMLParser
import json
import os
import re


def normalize_text(text: str) -> str:
    """Collapse repeated whitespace and trim."""
    return re.sub(r"\s+", " ", text or "").strip()


def clean_extracted_text(text: str) -> str:
    """
    Remove a few noisy artefacts from the source HTML after normalisation.

    EUR-Lex occasionally includes a stray trailing backtick in titles
    (for example Article 1 in the locally saved file).
    """
    text = normalize_text(text)
    text = text.replace("\u00c2", "")
    text = re.sub(r"`+$", "", text)
    return text.strip()


# Paragraph classes that count as annex body content. We keep the original
# `oj-normal` and `oj-ti-grseq-1` and additionally accept the deeper grseq
# variants and table cells, which we see in Annex VI and others.
_ANNEX_BODY_CLASSES_EXACT = {"oj-normal", "oj-ti-grseq-1"}
_ANNEX_BODY_CLASS_PREFIXES = ("oj-ti-grseq-", "oj-table-cell")


def _is_annex_body_class(cls):
    if not cls:
        return False
    if cls in _ANNEX_BODY_CLASSES_EXACT:
        return True
    return any(cls.startswith(p) for p in _ANNEX_BODY_CLASS_PREFIXES)


# Section heading inside an annex (Annex VIII has "Section A — ..." and
# "Section B — ..."). We capture the single-letter section identifier.
_ANNEX_SECTION_RE = re.compile(r"^Section\s+([A-Z])\b", re.IGNORECASE)


class EurLexParser(HTMLParser):
    """
    Extract chapters, articles and annexes from EUR-Lex HTML using structural ids/classes.

    Expected patterns:
    - Chapter div ids: cpt_<ROMAN_NUMERAL>
    - Article div ids: art_<NUMBER>
    - Annex div ids:  anx_<ROMAN_NUMERAL>

    Paragraph classes seen in EUR-Lex:
    - oj-ti-section-1: chapter number line, e.g. "CHAPTER II"
    - oj-ti-section-2: chapter title
    - oj-ti-art:       article number line, e.g. "Article 5"
    - oj-sti-art:      article title
    - oj-normal:       article/annex body paragraph
    - oj-doc-ti:       annex number / title lines
    - oj-ti-grseq-1:   annex sub-headings
    - oj-ti-grseq-2/3, oj-table-cell*: deeper annex content (Annex VI, etc.)
    """

    def __init__(self):
        super().__init__()
        self.div_stack = []
        self.curr_para_cls = None
        self.curr_para_txt = []
        self.cpts = []
        self.arts = []
        self.annexes = []
        self.curr_chapter = None
        self.curr_article = None
        self.curr_annex = None
        self.pending_list_label = None
        self.container_paragraph_numbers = {}
        # Annex-specific state for content_items extraction
        self.annex_current_section = None
        self.annex_current_paragraph_number = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "div":
            div_id = attrs.get("id", "")
            self.div_stack.append(div_id)
            # match chapter ids
            if re.fullmatch(r"cpt_[A-Z]+", div_id):
                self.curr_chapter = {
                    "id": div_id,
                    "number": "",
                    "title": "",
                }
            elif re.fullmatch(r"anx_[A-Z]+", div_id):
                self.curr_annex = {
                    "id": div_id,
                    "number": "",
                    "title": "",
                    "body_parts": [],
                    "content_items": [],
                }
                self.pending_list_label = None
                self.container_paragraph_numbers = {}
                self.annex_current_section = None
                self.annex_current_paragraph_number = None
            # match article ids
            elif re.fullmatch(r"art_\d+", div_id):
                self.curr_article = {
                    "id": div_id,
                    "number": "",
                    "title": "",
                    "paragraphs": [],
                    "body_parts": [],
                    "content_items": [],
                }
                self.pending_list_label = None
                self.container_paragraph_numbers = {}
        # if element's a paragraph, track text and its class (indicating title/body)
        # means normally we're inside a chapter/article div
        elif tag == "p":
            self.curr_para_cls = attrs.get("class")
            self.curr_para_txt = []

    def handle_endtag(self, tag):
        if tag == "p":
            self._flush_paragraph()
            self.curr_para_cls = None
            self.curr_para_txt = []
            return

        # unncessary tag (neither div nor paragraph) or div stack is empty, skip
        if tag != "div" or not self.div_stack:
            return

        # try and close the latest div
        div_id = self.div_stack.pop()

        # check if div is chapter or an article, then finalise and add to list
        if self.curr_article and div_id == self.curr_article["id"]:
            body_text = clean_extracted_text(" ".join(self.curr_article["body_parts"]))

            if self.curr_article["number"]:
                self.arts.append({
                    "id": self.curr_article["id"],
                    "number": self.curr_article["number"],
                    "article_reference": f"Article {self.curr_article['number']}",
                    "title": self.curr_article["title"],
                    "parent_chapter_id": self.curr_chapter["id"] if self.curr_chapter else None,
                    "parent_chapter_number": self.curr_chapter["number"] if self.curr_chapter else None,
                    "paragraphs": self.curr_article["paragraphs"],
                    "content_items": self.curr_article["content_items"],
                    "text": body_text,
                })
            self.curr_article = None
            self.pending_list_label = None
            self.container_paragraph_numbers = {}
        elif self.curr_annex and div_id == self.curr_annex["id"]:
            body_text = clean_extracted_text(" ".join(self.curr_annex["body_parts"]))

            if self.curr_annex["number"]:
                self.annexes.append({
                    "id": self.curr_annex["id"],
                    "number": self.curr_annex["number"],
                    "annex_reference": f"Annex {self.curr_annex['number']}",
                    "title": self.curr_annex["title"],
                    "text": body_text,
                    "content_items": self.curr_annex["content_items"],
                })
            self.curr_annex = None
            self.pending_list_label = None
            self.container_paragraph_numbers = {}
            self.annex_current_section = None
            self.annex_current_paragraph_number = None
        elif self.curr_chapter and div_id == self.curr_chapter["id"]:
            self.cpts.append({
                "id": self.curr_chapter["id"],
                "number": self.curr_chapter["number"],
                "title": self.curr_chapter["title"],
            })
            self.curr_chapter = None

    def handle_data(self, data):
        # if currently reading a paragraph, collect its text
        if self.curr_para_cls is not None:
            self.curr_para_txt.append(data)

    def _flush_paragraph(self):
        text = clean_extracted_text(" ".join(self.curr_para_txt))
        if not text:
            return

        if self.curr_article is not None:
            self._handle_article_paragraph(text)
            return

        if self.curr_annex is not None:
            self._handle_annex_paragraph(text)
            return

        if self.curr_chapter is not None:
            self._handle_chapter_paragraph(text)

    def _handle_article_paragraph(self, text):
        """Gather text from article paragraphs"""
        if self.curr_para_cls == "oj-ti-art":
            match = re.search(r"(\d+)", text)
            if match:
                self.curr_article["number"] = match.group(1)

        elif self.curr_para_cls == "oj-sti-art":
            self.curr_article["title"] = text

        elif self.curr_para_cls == "oj-normal":
            self.curr_article["paragraphs"].append(text)

            container_id = self._current_content_container_id()
            list_marker_match = re.fullmatch(r"\(([A-Za-z0-9ivxlcdmIVXLCDM]+)\)", text)
            if list_marker_match:
                self.pending_list_label = list_marker_match.group(1)
                return

            paragraph_match = re.match(r"^(\d+)\.\s+(.*)$", text)
            paragraph_number = paragraph_match.group(1) if paragraph_match else None
            if container_id and paragraph_number:
                self.container_paragraph_numbers[container_id] = paragraph_number

            entry_text = text
            list_label = self.pending_list_label
            inherited_paragraph_number = paragraph_number
            if inherited_paragraph_number is None and container_id:
                inherited_paragraph_number = self.container_paragraph_numbers.get(container_id)
            if list_label is not None:
                entry_text = f"({list_label}) {entry_text}"
                self.pending_list_label = None

            self.curr_article["body_parts"].append(entry_text)
            self.curr_article["content_items"].append({
                "container_id": container_id,
                "paragraph_number": inherited_paragraph_number,
                "list_label": list_label,
                "reference": self._build_content_reference(inherited_paragraph_number, list_label),
                "text": entry_text,
            })

    def _handle_chapter_paragraph(self, text):
        """Gather text from chapter paragraphs"""
        if self.curr_para_cls == "oj-ti-section-1" and text.startswith("CHAPTER"):
            self.curr_chapter["number"] = normalize_text(
                text.replace("CHAPTER", "", 1)
            )

        elif self.curr_para_cls == "oj-ti-section-2" and not self.curr_chapter["title"]:
            self.curr_chapter["title"] = text

    def _handle_annex_paragraph(self, text):
        """Gather text and content_items from annex paragraphs."""
        # Title / number line 
        if self.curr_para_cls == "oj-doc-ti":
            annex_match = re.search(r"ANNEX\W*([A-Z]+)", text, flags=re.IGNORECASE)
            if annex_match and not self.curr_annex["number"]:
                self.curr_annex["number"] = annex_match.group(1).upper()
            elif not self.curr_annex["title"]:
                self.curr_annex["title"] = text
            return

        #  Body paragraph (broadened class filter) 
        if not _is_annex_body_class(self.curr_para_cls):
            return

        #  Section heading detection (Annex VIII has Section A / Section B)
        section_match = _ANNEX_SECTION_RE.match(text)
        if section_match:
            self.annex_current_section = section_match.group(1).upper()
            # Reset paragraph numbering when we enter a new section
            self.annex_current_paragraph_number = None
            # Still record the heading text in body_parts so the flat
            # `text` field stays complete.
            self.curr_annex["body_parts"].append(text)
            return

        # Bare list-marker paragraph "(a)" — defer until next paragraph
        list_marker_match = re.fullmatch(r"\(([A-Za-z0-9ivxlcdmIVXLCDM]+)\)", text)
        if list_marker_match:
            self.pending_list_label = list_marker_match.group(1)
            return

        #  Numbered top-level item: "1. ..." at the START of the paragraph.
        # This is the simple/clean case — EUR-Lex emits each numbered item as
        # its own <p> with "N. " at the beginning.
        numbered_match = re.match(r"^(\d+)\.\s+(.*)$", text)
        paragraph_number = numbered_match.group(1) if numbered_match else None

        # FALLBACK: "N. " embedded anywhere in a run-on paragraph.
        # EUR-Lex also frequently fuses the preamble and the first numbered
        # item (and sometimes several items) into a single <p> element. In
        # that case the leading-anchor regex above won't match, but we still
        # need to track that we're now inside numbered item "1." for the
        # purpose of inheriting the number onto subsequent lettered sub-items.
        # We take the LAST numbered marker found, because items that follow
        # the current paragraph belong to the most recent number seen.
        if paragraph_number is None:
            all_numbered = re.findall(r"(?:^|\s)(\d+)\.\s+[A-Z]", text)
            if all_numbered:
                paragraph_number = all_numbered[-1]

        if paragraph_number:
            self.annex_current_paragraph_number = paragraph_number

        # Lettered sub-item embedded in the same paragraph: 
        # Take only the FIRST inline marker (the dominant one).
        inline_letter_match = re.match(r"^\(([a-z])\)\s+", text)

        list_label = self.pending_list_label
        if list_label is None and inline_letter_match:
            list_label = inline_letter_match.group(1)

        # Determine the inherited paragraph number for sub-items
        inherited_paragraph_number = (
            paragraph_number or self.annex_current_paragraph_number
        )

        # If we consumed a deferred marker, clear it now
        if self.pending_list_label is not None:
            self.pending_list_label = None
            # When the marker came from a previous bare paragraph, the text
            # itself doesn't include the "(x)" prefix yet — add it for clarity
            entry_text = f"({list_label}) {text}"
        else:
            entry_text = text

        self.curr_annex["body_parts"].append(entry_text)
        self.curr_annex["content_items"].append({
            "section": self.annex_current_section,
            "paragraph_number": inherited_paragraph_number,
            "list_label": list_label,
            "reference": self._build_annex_content_reference(
                inherited_paragraph_number, list_label
            ),
            "text": entry_text,
        })

    def _current_content_container_id(self):
        for div_id in reversed(self.div_stack):
            if re.fullmatch(r"\d{3}\.\d{3}(?:\.\d{3})*", div_id):
                return div_id
        return None

    def _build_content_reference(self, paragraph_number, list_label):
        if not self.curr_article or not self.curr_article["number"]:
            return None

        reference = f"Article {self.curr_article['number']}"
        if paragraph_number:
            reference += f"({paragraph_number})"
        if list_label:
            reference += f"({list_label})"
        return reference

    def _build_annex_content_reference(self, paragraph_number, list_label):
        """Build a reference string like 'Annex IV(1)(a)' or 'Annex VIII(A)(1)'."""
        if not self.curr_annex or not self.curr_annex["number"]:
            return None
        reference = f"Annex {self.curr_annex['number']}"
        if self.annex_current_section:
            reference += f"({self.annex_current_section})"
        if paragraph_number:
            reference += f"({paragraph_number})"
        if list_label:
            reference += f"({list_label})"
        return reference


def parse_html(html_path):
    """
    Parse the law body using HTML structure.
    """
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    parser = EurLexParser()
    parser.feed(content)
    parser.close()

    return parser.cpts, parser.arts, parser.annexes


def build_output(chapters, articles, annexes):
    """Build a pipeline-friendly JSON payload."""
    pipeline_articles = []
    for article in articles:
        chapter_number = article["parent_chapter_number"]
        pipeline_articles.append({
            "article_number": int(article["number"]),
            "article_reference": article["article_reference"],
            "title": article["title"],
            "text": article["text"],
            "paragraphs": article["paragraphs"],
            "content_items": article["content_items"],
            "source_id": article["id"],
            "source_path": "data/unstructured/eu_ai_act_content.html",
            "chapter_id": article["parent_chapter_id"],
            "chapter_number": chapter_number,
            "chapter_reference": (
                f"Chapter {chapter_number}" if chapter_number else None
            ),
        })

    pipeline_annexes = []
    for annex in annexes:
        pipeline_annexes.append({
            "annex_number": annex["number"],
            "annex_reference": annex["annex_reference"],
            "title": annex["title"],
            "text": annex["text"],
            "content_items": annex.get("content_items", []),
            "source_id": annex["id"],
            "source_path": "data/unstructured/eu_ai_act_content.html",
        })

    return {
        "source": "EUR-Lex",
        "description": "Official EU AI Act full text extracted from saved EUR-Lex HTML",
        "total_articles": len(pipeline_articles),
        "total_annexes": len(pipeline_annexes),
        "errors": [],
        "regulation": {
            "celex": "32024R1689",
            "title": "Regulation (EU) 2024/1689 - Artificial Intelligence Act",
            "date": "2024-06-13",
            "source": "EUR-Lex",
            "source_format": "HTML",
            "document_type": "legal_text",
            "source_path": "data/unstructured/eu_ai_act_content.html",
        },
        "chapters": chapters,
        "articles": pipeline_articles,
        "annexes": pipeline_annexes,
    }


def main():
    html_path = "data/unstructured/html/eu_ai_act_content.html"
    output_path = "data/unstructured/html/eu_ai_act_articles.json"

    print(f"Parsing: {html_path}")
    chapters, articles, annexes = parse_html(html_path)
    print(
        f"Extracted {len(chapters)} chapters, {len(articles)} articles "
        f"and {len(annexes)} annexes"
    )

    output = build_output(chapters, articles, annexes)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False)

    print(f"Output written to: {output_path}")

    print("\nPreview of first 5 articles:")
    for article in articles[:5]:
        print(
            f"  {article['article_reference']}: "
            f"{article['title'][:70]}"
        )

    print("\nAnnex content_items counts:")
    for annex in annexes:
        print(
            f"  Annex {annex['number']:6}  "
            f"{len(annex.get('content_items', [])):>3} items  "
            f"{len(annex.get('text', '')):>5} chars"
        )


if __name__ == "__main__":
    main()