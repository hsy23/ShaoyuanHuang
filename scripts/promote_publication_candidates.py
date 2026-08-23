#!/usr/bin/env python3
"""Promote reviewed publication candidates into the live publications collection.

The script is designed for GitHub Actions workflow_dispatch runs. It moves
eligible markdown files from _publication_candidates/ into _publications/ while
leaving a concise report for the pull request body.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


AUTHOR_PATTERNS = ("shaoyuan huang", "huang shaoyuan")
REVIEW_COMMENT = "<!-- Review this candidate before moving it into _publications/. -->"
TRUSTED_URL_DOMAINS = {
    "doi.org",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "computer.org",
    "openreview.net",
    "arxiv.org",
    "ojs.aaai.org",
    "journalofcloudcomputing.springeropen.com",
}


@dataclass
class Candidate:
    path: Path
    front_matter: str
    body: str
    data: dict[str, str | list[str]]


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def unquote_yaml_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace("''", "'").strip()


def split_front_matter(text: str) -> tuple[str, str]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.DOTALL)
    if not match:
        raise ValueError("missing YAML front matter")
    return match.group(1), match.group(2)


def parse_front_matter(front_matter: str) -> dict[str, str | list[str]]:
    data: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for raw_line in front_matter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        item_match = re.match(r"^\s+-\s+(.*)$", line)
        if item_match and current_list_key:
            items = data.setdefault(current_list_key, [])
            if isinstance(items, list):
                items.append(unquote_yaml_value(item_match.group(1)))
            continue

        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                data[key] = unquote_yaml_value(value)
                current_list_key = None
            else:
                data[key] = []
                current_list_key = key

    return data


def read_candidate(path: Path) -> Candidate:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    front_matter, body = split_front_matter(text)
    return Candidate(path=path, front_matter=front_matter, body=body, data=parse_front_matter(front_matter))


def read_existing_titles(publications_dir: Path) -> set[str]:
    titles: set[str] = set()
    for path in publications_dir.glob("*.md"):
        try:
            candidate = read_candidate(path)
        except ValueError:
            continue
        title = str(candidate.data.get("title") or "")
        if title:
            titles.add(normalize_title(title))
    return titles


def trusted_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    return any(host == domain or host.endswith("." + domain) for domain in TRUSTED_URL_DOMAINS)


def candidate_has_author(candidate: Candidate) -> bool:
    text = f"{candidate.data.get('citation', '')} {candidate.front_matter} {candidate.body}".lower()
    return any(pattern in text for pattern in AUTHOR_PATTERNS)


def confidence(candidate: Candidate) -> int:
    raw = candidate.data.get("confidence") or "0"
    try:
        return int(str(raw))
    except ValueError:
        return 0


def title_matches(candidate: Candidate, filters: list[str]) -> bool:
    if not filters:
        return True
    title = str(candidate.data.get("title") or "").lower()
    return any(item.lower() in title for item in filters)


def reliable_link(candidate: Candidate) -> str:
    paperurl = str(candidate.data.get("paperurl") or "")
    source_url = str(candidate.data.get("source_url") or "")
    if trusted_url(paperurl):
        return paperurl
    if trusted_url(source_url):
        return source_url
    return ""


def updated_front_matter(candidate: Candidate, paperurl: str) -> str:
    promoted_lines: list[str] = []
    paperurl_written = False
    skip_keys = {"source", "source_url", "confidence"}

    for raw_line in candidate.front_matter.splitlines():
        key = raw_line.split(":", 1)[0].strip() if ":" in raw_line and not raw_line.startswith(" ") else ""
        if key in skip_keys:
            continue
        if key == "paperurl":
            promoted_lines.append(f"paperurl: '{paperurl}'")
            paperurl_written = True
            continue
        promoted_lines.append(raw_line.rstrip())

    if paperurl and not paperurl_written:
        promoted_lines.append(f"paperurl: '{paperurl}'")

    return "\n".join(promoted_lines).strip()


def write_candidate_readme(candidates_dir: Path) -> None:
    candidate_paths = sorted(path for path in candidates_dir.glob("*.md") if path.name.lower() != "readme.md")
    readme = candidates_dir / "README.md"
    if not candidate_paths:
        if readme.exists():
            readme.unlink()
        return

    lines = [
        "# Publication Discovery Candidates",
        "",
        "These files are generated by `scripts/discover_publications.py`.",
        "Review each candidate and move confirmed entries into `_publications/`.",
        "",
        f"Candidate count: {len(candidate_paths)}",
        "",
    ]
    for path in candidate_paths:
        try:
            candidate = read_candidate(path)
        except ValueError:
            continue
        title = str(candidate.data.get("title") or path.stem)
        year = str(candidate.data.get("date") or "0000")[:4]
        areas = candidate.data.get("research_areas") or []
        if not isinstance(areas, list):
            areas = [str(areas)]
        lines.append(f"- {year}: {title} (confidence {confidence(candidate)}, areas: {', '.join(areas)})")
    lines.append("")
    readme.write_text("\n".join(lines), encoding="utf-8")


def promote_candidate(candidate: Candidate, publications_dir: Path, paperurl: str) -> None:
    front_matter = updated_front_matter(candidate, paperurl)
    body = candidate.body.replace(REVIEW_COMMENT, "").strip()
    output = f"---\n{front_matter}\n---\n"
    if body:
        output += f"\n{body}\n"

    target = publications_dir / candidate.path.name
    target.write_text(output, encoding="utf-8")
    candidate.path.unlink()


def parse_title_filters(raw_filters: list[str]) -> list[str]:
    filters: list[str] = []
    for raw in raw_filters:
        filters.extend(item.strip() for item in re.split(r"[;\n]", raw) if item.strip())
    return filters


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-dir", default="_publication_candidates")
    parser.add_argument("--publications-dir", default="_publications")
    parser.add_argument("--min-confidence", type=int, default=8)
    parser.add_argument(
        "--title-filter",
        action="append",
        default=[],
        help="Optional semicolon-separated title fragments. Empty means all eligible candidates.",
    )
    args = parser.parse_args()

    candidates_dir = Path(args.candidates_dir)
    publications_dir = Path(args.publications_dir)
    filters = parse_title_filters(args.title_filter)

    print("# Promote Publication Candidates")
    print("")
    print(f"Minimum confidence: {args.min_confidence}")
    if filters:
        print(f"Title filters: {', '.join(filters)}")
    print("")

    if not candidates_dir.exists():
        print("No `_publication_candidates/` directory found.")
        return 0

    publications_dir.mkdir(parents=True, exist_ok=True)
    existing_titles = read_existing_titles(publications_dir)
    promoted: list[str] = []
    skipped: list[str] = []

    for path in sorted(candidates_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue

        try:
            candidate = read_candidate(path)
        except ValueError as exc:
            skipped.append(f"{path.name}: {exc}")
            continue

        title = str(candidate.data.get("title") or "")
        if not title:
            skipped.append(f"{path.name}: missing title")
            continue
        if normalize_title(title) in existing_titles:
            skipped.append(f"{title}: already exists in `_publications/`")
            continue
        if not title_matches(candidate, filters):
            skipped.append(f"{title}: did not match title filter")
            continue
        if confidence(candidate) < args.min_confidence:
            skipped.append(f"{title}: confidence {confidence(candidate)} below threshold")
            continue
        if not candidate_has_author(candidate):
            skipped.append(f"{title}: Shaoyuan Huang not found in candidate metadata")
            continue

        paperurl = reliable_link(candidate)
        if not paperurl:
            skipped.append(f"{title}: no trusted `paperurl` or `source_url`")
            continue

        promote_candidate(candidate, publications_dir, paperurl)
        existing_titles.add(normalize_title(title))
        promoted.append(title)

    write_candidate_readme(candidates_dir)

    if promoted:
        print("Promoted:")
        for title in promoted:
            print(f"- {title}")
    else:
        print("No candidates promoted.")

    if skipped:
        print("")
        print("Skipped:")
        for reason in skipped:
            print(f"- {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
