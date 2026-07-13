import sys
import json
import logging
import datetime
import xml.etree.ElementTree as ET
from typing import Optional

import requests

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"

THEMES = [
    {
        "name": "Squeezed light experiment",
        "include": [
            "squeezed light",
            "squeezing",
            "homodyne",
            "heterodyne",
            "optical parametric",
            "nonclassical light",
            "photon statistics",
            "quadrature noise",
        ],
        "exclude": [],
    },
    {
        "name": "Quantum computing experiment",
        "include": [
            "quantum processor",
            "qubit",
            "gate fidelity",
            "superconducting",
            "trapped ion",
            "quantum error correction",
            "fault tolerant",
            "surface code",
            "logical qubit",
        ],
        "exclude": [],
    },
    {
        "name": "Quantum learning",
        "include": [
            "quantum learning",
            "learning quantum",
            "quantum state tomography",
            "quantum process tomography",
            "shadow tomography",
            "classical shadows",
            "learning quantum channels",
        ],
        "exclude": [
            "quantum machine learning",
            "qml",
            "variational quantum",
        ],
    },
    {
        "name": "Quantum contextuality",
        "include": [
            "contextuality",
            "kochen-specker",
            "contextual",
            "non-contextual",
            "noncontextual",
            "bell inequality",
            "chsh",
        ],
        "exclude": [],
    },
    {
        "name": "Proposals to realize quantum advantage",
        "include": [
            "quantum advantage",
            "quantum supremacy",
            "quantum speedup",
            "near-term quantum",
            "nisq",
            "quantum protocol proposal",
        ],
        "exclude": [],
    },
]


def get_date_window() -> tuple[datetime.datetime, datetime.datetime]:
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.weekday() == 0:
        days_back = 3
    else:
        days_back = 1
    cutoff = now - datetime.timedelta(days=days_back)
    return cutoff, now


def fetch_papers() -> list[dict]:
    params = {
        "search_query": "cat:quant-ph",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": config.ARXIV_MAX_RESULTS,
    }
    try:
        response = requests.get(ARXIV_API_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch arXiv data: %s", exc)
        return []

    return parse_feed(response.text)


def parse_feed(xml_text: str) -> list[dict]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("Failed to parse arXiv XML: %s", exc)
        return []

    papers = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        abstract_el = entry.find("atom:summary", ns)
        published_el = entry.find("atom:published", ns)
        updated_el = entry.find("atom:updated", ns)
        id_el = entry.find("atom:id", ns)

        if any(el is None for el in [title_el, abstract_el, published_el, id_el]):
            continue

        authors = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        arxiv_id = id_el.text.strip().split("/abs/")[-1]
        published_str = published_el.text.strip()

        try:
            submitted = datetime.datetime.fromisoformat(
                published_str.replace("Z", "+00:00")
            )
        except ValueError:
            continue

        papers.append(
            {
                "id": arxiv_id,
                "title": " ".join(title_el.text.split()),
                "abstract": " ".join(abstract_el.text.split()),
                "authors": authors,
                "submitted": submitted,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )

    return papers


def score_paper(paper: dict) -> list[str]:
    text = (paper["title"] + " " + paper["abstract"]).lower()
    matched_themes = []

    for theme in THEMES:
        excluded = any(kw in text for kw in theme["exclude"])
        if excluded:
            continue
        included = any(kw in text for kw in theme["include"])
        if included:
            matched_themes.append(theme["name"])

    return matched_themes


def filter_papers(papers: list[dict], cutoff: datetime.datetime) -> list[dict]:
    return [p for p in papers if p["submitted"] >= cutoff]


def build_blocks(
    matched: dict[str, list[dict]], date: datetime.date, total: int, num_themes: int
) -> list[dict]:
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"arXiv quant-ph Digest — {date.strftime('%Y-%m-%d')}",
                "emoji": False,
            },
        },
        {"type": "divider"},
    ]

    for theme_name, papers in matched.items():
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{theme_name}* ({len(papers)} paper{'s' if len(papers) != 1 else ''})",
                },
            }
        )

        for paper in papers:
            authors_str = ", ".join(paper["authors"][:3])
            if len(paper["authors"]) > 3:
                authors_str += " et al."

            snippet = paper["abstract"][:200].rstrip()
            if len(paper["abstract"]) > 200:
                snippet += "..."

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*<{paper['url']}|{paper['title']}>*\n"
                            f"{authors_str}\n"
                            f"_{snippet}_"
                        ),
                    },
                }
            )

        blocks.append({"type": "divider"})

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{total} paper{'s' if total != 1 else ''} matched across {num_themes} theme{'s' if num_themes != 1 else ''} | {timestamp}",
                }
            ],
        }
    )

    return blocks


def send_slack_message(blocks: list[dict], fallback_text: str) -> bool:
    if not config.SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not set.")
        return False

    payload = {"text": fallback_text, "blocks": blocks}
    try:
        response = requests.post(
            config.SLACK_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to send Slack message: %s", exc)
        return False

    return True


def send_no_papers_message(date: datetime.date) -> bool:
    if not config.SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not set.")
        return False

    text = f"arXiv quant-ph Digest — {date.strftime('%Y-%m-%d')}: No matching papers today."
    payload = {"text": text}
    try:
        response = requests.post(
            config.SLACK_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to send Slack message: %s", exc)
        return False

    return True


def main() -> None:
    cutoff, now = get_date_window()
    logger.info("Fetching quant-ph papers submitted since %s", cutoff.isoformat())

    papers = fetch_papers()
    if not papers:
        logger.error("No papers retrieved from arXiv.")
        sys.exit(1)

    recent = filter_papers(papers, cutoff)
    logger.info("Papers in time window: %d", len(recent))

    theme_buckets: dict[str, list[dict]] = {}
    for paper in recent:
        themes = score_paper(paper)
        for theme in themes:
            theme_buckets.setdefault(theme, [])
            if len(theme_buckets[theme]) < config.MAX_PAPERS_PER_THEME:
                theme_buckets[theme].append(paper)

    if not theme_buckets:
        logger.info("No matching papers found.")
        success = send_no_papers_message(now.date())
        sys.exit(0 if success else 1)

    total_papers = sum(len(v) for v in theme_buckets.values())
    num_themes = len(theme_buckets)

    blocks = build_blocks(theme_buckets, now.date(), total_papers, num_themes)
    fallback = f"arXiv quant-ph Digest — {now.date()}: {total_papers} papers matched."

    logger.info("Sending Slack digest: %d papers across %d themes", total_papers, num_themes)
    success = send_slack_message(blocks, fallback)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
