#!/usr/bin/env python3
"""Discover publication candidates for the personal website.

The script is intentionally conservative: it writes candidate markdown files to
_publication_candidates/ instead of publishing directly to _publications/.
Review and move confirmed files into _publications/ before they go live.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import textwrap
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path


AUTHOR_NAME = "Shaoyuan Huang"
AUTHOR_NORMALIZED = "shaoyuan huang"

COAUTHOR_HINTS = {
    "xiaofei wang",
    "cheng zhang",
    "heng zhang",
    "wenyu wang",
    "zheng wang",
    "yuting li",
    "tiancheng zhang",
    "yunfeng zhao",
    "yulin chen",
    "xiangqi liu",
    "tengwen zhang",
    "zhongtian zhang",
    "chao qiu",
    "shuren liu",
    "nan xue",
    "yedong ning",
    "yansha deng",
    "yan gao",
    "yonghui ye",
    "jie fu",
    "minglai shao",
    "huaming wu",
}

AREA_KEYWORDS = {
    "AI Systems": [
        "large language model",
        "llm",
        "retrieval-augmented",
        "rag",
        "inference",
        "serving",
        "fine-tuning",
        "deep learning",
        "transformer",
        "speculative",
        "model parallel",
        "expert routing",
        "memory-aware",
        "lmaas",
        "llm-as-a-service",
    ],
    "Workload Forecasting": [
        "workload",
        "forecast",
        "forecasting",
        "prediction",
        "time series",
        "load forecasting",
        "runtime prediction",
        "hot spot",
        "hotspot",
        "meta-pattern",
    ],
    "Cloud-Edge Systems": [
        "cloud-edge",
        "edge cloud",
        "edge computing",
        "distributed",
        "scheduling",
        "resource",
        "latency",
        "qos",
        "crowdsourced",
        "content placement",
        "live streaming",
        "server",
        "gateway",
    ],
    "Spatio-Temporal Analytics": [
        "spatio-temporal",
        "spatial-temporal",
        "spatial",
        "temporal",
        "social",
        "propagation",
        "measurement",
        "matrix imputation",
        "graph attention",
        "network latency",
        "network traffic",
    ],
}

VENUE_QUALITY = {
    "sigkdd": "CCF-A",
    "kdd": "CCF-A",
    "infocom": "CCF-A",
    "icml": "CCF-A",
    "aaai": "CCF-A",
    "transactions on knowledge and data engineering": "CCF-A",
    "transactions on mobile computing": "JCR Q1",
    "transactions on parallel and distributed systems": "JCR Q1",
}


@dataclass
class Candidate:
    title: str
    authors: list[str]
    date: str
    year: int
    venue: str
    url: str
    doi: str
    category: str
    areas: list[str]
    quality: str
    confidence: int
    source: str
    source_url: str
    abstract: str


def request_json(url: str, retries: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "ShaoyuanHuang publication discovery (GitHub Actions)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - command-line tool reports final error.
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def normalize_author(author: str) -> str:
    return re.sub(r"\s+", " ", author.lower()).strip()


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "-".join(slug.split("-")[:8]) or "publication"


def yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_existing_titles(publications_dir: Path) -> set[str]:
    titles: set[str] = set()
    for path in publications_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        match = re.search(r"(?m)^title:\s*[\"']?(.*?)[\"']?\s*$", text)
        if match:
            titles.add(normalize_title(match.group(1)))
    return titles


def abstract_from_openalex(work: dict) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        for index in indexes:
            positions.append((index, word))
    return " ".join(word for _, word in sorted(positions))


def get_source(work: dict) -> dict:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    if source:
        return source
    for location in work.get("locations") or []:
        source = (location or {}).get("source") or {}
        if source:
            return source
    return {}


def infer_category(work: dict, venue: str) -> str:
    venue_l = venue.lower()
    work_type = (work.get("type_crossref") or work.get("type") or "").lower()
    source = get_source(work)
    source_type = (source.get("type") or "").lower()
    if "journal" in work_type or source_type == "journal":
        return "journals"
    if "proceedings" in work_type or "conference" in venue_l:
        return "conferences"
    if "arxiv" in venue_l or "preprint" in venue_l:
        return "manuscripts"
    return "conferences"


def infer_areas(title: str, abstract: str) -> list[str]:
    text = f"{title} {abstract}".lower()
    areas = [
        area
        for area, keywords in AREA_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    return areas or ["Cloud-Edge Systems"]


def infer_quality(venue: str) -> str:
    venue_l = venue.lower()
    for key, quality in VENUE_QUALITY.items():
        if key in venue_l:
            return quality
    return ""


def coauthor_hint_count(authors: list[str]) -> int:
    return sum(1 for author in authors if normalize_author(author) in COAUTHOR_HINTS)


def has_area_keyword(text: str) -> bool:
    text_l = text.lower()
    return any(keyword in text_l for keywords in AREA_KEYWORDS.values() for keyword in keywords)


def confidence_score(title: str, authors: list[str], abstract: str) -> int:
    authors_l = [normalize_author(author) for author in authors]
    if AUTHOR_NORMALIZED not in authors_l:
        return 0
    score = 4
    score += min(3, coauthor_hint_count(authors))
    text = f"{title} {abstract}"
    if has_area_keyword(text):
        score += 1
    if "tianjin university" in text.lower() or "edge" in text.lower():
        score += 1
    return score


def extract_openalex_candidate(work: dict) -> Candidate | None:
    title = html.unescape(work.get("display_name") or "").strip()
    if not title:
        return None

    authors = [
        ((authorship or {}).get("author") or {}).get("display_name", "").strip()
        for authorship in work.get("authorships") or []
    ]
    authors = [author for author in authors if author]

    abstract = abstract_from_openalex(work)
    confidence = confidence_score(title, authors, abstract)
    if confidence < 5:
        return None

    source = get_source(work)
    host_venue = work.get("host_venue") or {}
    venue = (source.get("display_name") or host_venue.get("display_name") or "Publication").strip()
    date = work.get("publication_date") or f"{work.get('publication_year') or 1900}-01-01"
    year = int(str(date)[:4])
    doi = (work.get("doi") or "").strip()
    url = doi or ((work.get("primary_location") or {}).get("landing_page_url") or work.get("id") or "").strip()

    return Candidate(
        title=title,
        authors=authors,
        date=date,
        year=year,
        venue=venue,
        url=url,
        doi=doi,
        category=infer_category(work, venue),
        areas=infer_areas(title, abstract),
        quality=infer_quality(venue),
        confidence=confidence,
        source="OpenAlex",
        source_url=(work.get("id") or "").strip(),
        abstract=abstract,
    )


def discover_openalex(since_year: int, until_date: str, per_page: int) -> list[Candidate]:
    params = {
        "search": AUTHOR_NAME,
        "filter": f"from_publication_date:{since_year}-01-01,to_publication_date:{until_date}",
        "per-page": str(per_page),
        "sort": "publication_date:desc",
        "mailto": "hsy_23@tju.edu.cn",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = request_json(url)
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for work in data.get("results") or []:
        candidate = extract_openalex_candidate(work)
        if not candidate:
            continue
        key = normalize_title(candidate.title)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def crossref_date(item: dict) -> str:
    date_parts = (
        item.get("published-print", {})
        or item.get("published-online", {})
        or item.get("published", {})
        or item.get("created", {})
    ).get("date-parts") or [[1900, 1, 1]]
    parts = list(date_parts[0])
    while len(parts) < 3:
        parts.append(1)
    return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def crossref_authors(item: dict) -> list[str]:
    authors: list[str] = []
    for author in item.get("author") or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        name = " ".join(part for part in [given, family] if part).strip()
        if name:
            authors.append(name)
    return authors


def extract_crossref_candidate(item: dict) -> Candidate | None:
    title = html.unescape((item.get("title") or [""])[0]).strip()
    if not title:
        return None

    authors = crossref_authors(item)
    authors_l = {normalize_author(author) for author in authors}
    if AUTHOR_NORMALIZED not in authors_l:
        return None

    abstract = re.sub(r"<[^>]+>", "", item.get("abstract") or "")
    if coauthor_hint_count(authors) == 0 and not has_area_keyword(title):
        return None

    confidence = confidence_score(title, authors, abstract)
    if confidence < 5:
        return None

    date_text = crossref_date(item)
    year = int(date_text[:4])
    venue = html.unescape((item.get("container-title") or ["Publication"])[0] or "Publication").strip()
    doi = (item.get("DOI") or "").strip()
    url = f"https://doi.org/{doi}" if doi else (item.get("URL") or "").strip()

    return Candidate(
        title=title,
        authors=authors,
        date=date_text,
        year=year,
        venue=venue,
        url=url,
        doi=doi,
        category=infer_category({"type_crossref": item.get("type")}, venue),
        areas=infer_areas(title, abstract),
        quality=infer_quality(venue),
        confidence=confidence,
        source="Crossref",
        source_url=(item.get("URL") or url).strip(),
        abstract=abstract,
    )


def discover_crossref(since_year: int, until_date: str, per_page: int) -> list[Candidate]:
    query_terms = [
        f"{AUTHOR_NAME} Xiaofei Wang",
        f"{AUTHOR_NAME} Cheng Zhang",
        f"{AUTHOR_NAME} Wenyu Wang",
        f"{AUTHOR_NAME} Heng Zhang",
        f"{AUTHOR_NAME} Yuting Li",
        f"{AUTHOR_NAME} Tiancheng Zhang",
        f"{AUTHOR_NAME} Yunfeng Zhao",
        f"{AUTHOR_NAME} edge cloud",
        f"{AUTHOR_NAME} workload",
        f"{AUTHOR_NAME} LLM",
    ]

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for query in query_terms:
        params = {
            "query": query,
            "filter": f"from-pub-date:{since_year}-01-01,until-pub-date:{until_date}",
            "rows": str(per_page),
            "sort": "score",
            "mailto": "hsy_23@tju.edu.cn",
        }
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        data = request_json(url)
        for item in (data.get("message") or {}).get("items") or []:
            candidate = extract_crossref_candidate(item)
            if not candidate:
                continue
            key = normalize_title(candidate.title)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    return candidates


def google_search_report() -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return "Google Custom Search skipped: set GOOGLE_API_KEY and GOOGLE_CSE_ID repository secrets to enable it.\n"

    queries = [
        '"Shaoyuan Huang" publication',
        '"Shaoyuan Huang" "Xiaofei Wang"',
        '"Shaoyuan Huang" "large language models"',
        '"Shaoyuan Huang" "edge cloud"',
    ]
    lines = ["# Google Custom Search Evidence", ""]
    for query in queries:
        params = {"key": api_key, "cx": cse_id, "q": query, "num": "5"}
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        data = request_json(url)
        lines.append(f"## {query}")
        for item in data.get("items") or []:
            title = item.get("title", "").strip()
            link = item.get("link", "").strip()
            snippet = item.get("snippet", "").strip().replace("\n", " ")
            lines.append(f"- [{title}]({link})")
            if snippet:
                lines.append(f"  {snippet}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def citation_for(candidate: Candidate) -> str:
    authors = [
        f"<b>{author}</b>" if author.lower() == AUTHOR_NORMALIZED else author
        for author in candidate.authors
    ]
    author_text = ", ".join(authors)
    return (
        f"{author_text}. ({candidate.year}). &quot;{html.escape(candidate.title)}.&quot; "
        f"<i>{html.escape(candidate.venue)}</i>."
    )


def write_candidate(path: Path, candidate: Candidate) -> None:
    permalink = "/publication/" + str(candidate.year) + "-" + slugify(candidate.title)
    lines = [
        "---",
        f"title: {yaml_quote(candidate.title)}",
        "collection: publications",
        f"category: {candidate.category}",
        f"permalink: {permalink}",
        f"date: {candidate.date}",
        f"venue: {yaml_quote(candidate.venue)}",
        f"paperurl: {yaml_quote(candidate.url)}",
    ]
    if candidate.quality:
        lines.extend(["highlight: true", f"quality: {yaml_quote(candidate.quality)}"])
    lines.append("research_areas:")
    for area in candidate.areas:
        lines.append(f"  - {area}")
    lines.extend(
        [
            f"source: {yaml_quote(candidate.source)}",
            f"source_url: {yaml_quote(candidate.source_url)}",
            f"confidence: {candidate.confidence}",
            f"citation: {yaml_quote(citation_for(candidate))}",
            "---",
            "",
            "<!-- Review this candidate before moving it into _publications/. -->",
        ]
    )
    if candidate.abstract:
        abstract = textwrap.shorten(candidate.abstract, width=900, placeholder="...")
        lines.extend(["", "## Abstract", "", abstract])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clean_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("*.md"):
        path.unlink()


def write_report(output_dir: Path, candidates: list[Candidate], google_report: str) -> None:
    lines = [
        "# Publication Discovery Candidates",
        "",
        "These files are generated by `scripts/discover_publications.py`.",
        "Review each candidate and move confirmed entries into `_publications/`.",
        "",
        f"Candidate count: {len(candidates)}",
        "",
    ]
    for candidate in candidates:
        lines.append(
            f"- {candidate.year}: {candidate.title} "
            f"(confidence {candidate.confidence}, areas: {', '.join(candidate.areas)})"
        )
    lines.extend(["", google_report.strip(), ""])
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publications-dir", default="_publications")
    parser.add_argument("--output-dir", default="_publication_candidates")
    parser.add_argument("--since-year", type=int, default=2024)
    parser.add_argument("--until-date", default=date.today().isoformat())
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--min-confidence", type=int, default=5)
    parser.add_argument("--use-google", action="store_true")
    args = parser.parse_args()

    publications_dir = Path(args.publications_dir)
    output_dir = Path(args.output_dir)
    existing_titles = read_existing_titles(publications_dir)

    discovered = discover_openalex(args.since_year, args.until_date, args.per_page)
    discovered.extend(discover_crossref(args.since_year, args.until_date, args.per_page))

    candidates: list[Candidate] = []
    seen_titles: set[str] = set()
    for candidate in discovered:
        key = normalize_title(candidate.title)
        if (
            key in existing_titles
            or key in seen_titles
            or candidate.confidence < args.min_confidence
        ):
            continue
        seen_titles.add(key)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.date, item.confidence), reverse=True)

    clean_output_dir(output_dir)
    if not candidates:
        readme = output_dir / "README.md"
        if readme.exists():
            readme.unlink()
        print(f"No new publication candidates found in {output_dir}")
        return 0

    for candidate in candidates:
        filename = f"{candidate.date}-{slugify(candidate.title)}.md"
        write_candidate(output_dir / filename, candidate)

    google_report = google_search_report() if args.use_google else "Google Custom Search not requested.\n"
    write_report(output_dir, candidates, google_report)
    print(f"Wrote {len(candidates)} publication candidates to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
