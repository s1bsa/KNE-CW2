"""
Scrapes plain-language summaries for all 113 articles and 13 annexes of
the EU AI Act from artificialintelligenceact.eu.

Extracts the CLaiRK-rendered summary section from each page, normalises
the text (Unicode fix-ups, scrape-artefact removal), and writes a single
JSON file containing both article and annex summaries with their source
URLs.

Output: data/unstructured/summaries/ai_act_summaries.json
"""

import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE_URL = "https://artificialintelligenceact.eu"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
DELAY = 0.1
TOTAL_ARTICLES = 113

# Annexes I–XIII of the EU AI Act
ANNEX_NUMBERS = list(range(1, 14))

OUTPUT_DIR = "data/unstructured/summaries"
JSON_OUTPUT = os.path.join(OUTPUT_DIR, "ai_act_summaries.json")


def fetch_page(url: str) -> str | None:
    """Fetch a page, retrying up to 3 times on failure."""
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            tqdm.write(f"  retry {attempt + 1}: {e}")
            time.sleep(DELAY * (attempt + 1))
    return None


def filter_summary(text: str) -> str:
    """Remove known scrape artifacts and normalise summary text."""
    if not text:
        return ""

    out = text.strip()

    replacements = {
        "â‚¬": "€",
        "â€¦": "...",
        "\u00a0": " ",
    }
    for bad, good in replacements.items():
        out = out.replace(bad, good)

    out = re.sub(
        r"\s*Generated\s+by\s*CLaiRK\s*,?\s*edited\s+by\s+us\.\s*$",
        "", out, flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\s*Generated\s+by\s*CLaiRK.*$",
        "", out, flags=re.IGNORECASE,
    )

    out = re.sub(r"\s+", " ", out).strip()
    return out


def extract_summary(html: str) -> str:
    """Extract a plain-language summary from a CLaiRK-rendered page."""
    soup = BeautifulSoup(html, "html.parser")

    summary_div = soup.find("div", class_="aia-clairk-summary-content-section")
    if summary_div:
        return filter_summary(summary_div.get_text(strip=True))

    # Fallback: some annex pages may not have a CLaiRK summary section.
    # Use the first <p> in the article body as a best-effort.
    article = soup.find("article")
    if article:
        first_p = article.find("p")
        if first_p:
            return filter_summary(first_p.get_text(strip=True))

    return ""


def to_roman(n: int) -> str:
    table = [
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = ""
    for value, sym in table:
        while n >= value:
            out += sym
            n -= value
    return out


def scrape_articles() -> tuple[list[dict], list[int]]:
    """Scrape plain-language summaries for all 113 articles."""
    print(f"\nScraping {TOTAL_ARTICLES} article summaries...")
    results, errors = [], []
    pbar = tqdm(range(1, TOTAL_ARTICLES + 1))
    for num in pbar:
        pbar.set_description(f"Article {num}")
        url = f"{BASE_URL}/article/{num}/"
        html = fetch_page(url)
        if not html:
            errors.append(num)
            continue
        summary = extract_summary(html)
        results.append({
            "article_number": num,
            "summary": summary,
            "source_url": url,
        })
        time.sleep(DELAY)
    return results, errors


def scrape_annexes() -> tuple[list[dict], list[int]]:
    """Scrape plain-language summaries for all 13 annexes."""
    print(f"\nScraping {len(ANNEX_NUMBERS)} annex summaries...")
    results, errors = [], []
    pbar = tqdm(ANNEX_NUMBERS)
    for num in pbar:
        roman = to_roman(num)
        pbar.set_description(f"Annex {roman}")
        # The site URL pattern uses arabic numerals
        url = f"{BASE_URL}/annex/{num}/"
        html = fetch_page(url)
        if not html:
            errors.append(num)
            continue
        summary = extract_summary(html)
        results.append({
            "annex_number": roman,
            "annex_arabic": num,
            "summary": summary,
            "source_url": url,
        })
        time.sleep(DELAY)
    return results, errors


def main() -> None:
    article_results, article_errors = scrape_articles()
    annex_results, annex_errors = scrape_annexes()

    output = {
        "source": "artificialintelligenceact.eu",
        "description": "Plain-language summaries of EU AI Act articles and annexes",
        "total_articles": len(article_results),
        "total_annexes": len(annex_results),
        "errors": {
            "articles": article_errors,
            "annexes": annex_errors,
        },
        "articles": article_results,
        "annexes": annex_results,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print(f"Articles: {len(article_results)}/{TOTAL_ARTICLES}  errors={article_errors}")
    print(f"Annexes:  {len(annex_results)}/{len(ANNEX_NUMBERS)}  errors={annex_errors}")
    print(f"Output:   {JSON_OUTPUT}")


if __name__ == "__main__":
    main()
