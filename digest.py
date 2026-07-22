import re
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
        "name": "Squeezed light",
        "include": [
            "squeezed light",
            "squeezing",
            "homodyne",
            "heterodyne",
            "optical parametric",
            "nonclassical light",
            "quadrature",
            "photon number resolving",
        ],
        "exclude": [],
    },
    {
        "name": "Quantum computing",
        "include": [
            "quantum processor",
            "gate fidelity",
            "superconducting",
            "trapped ion",
            "neutral atom",
            "error correction",
            "fault tolerant",
            "logical qubit",
        ],
        "exclude": [],
    },
    {
        "name": "Quantum learning",
        "include": [
            "quantum learning",
            "learning quantum",
            "learning physical",
            "sample complexity",
            "shadow tomography",
            "classical shadows",
        ],
        "exclude": [
            "quantum machine learning",
            "qml",
            "variational quantum",
        ],
    },
    {
        "name": "Contextuality",
        "include": [
            "contextuality",
            "kochen-specker",
            "contextual",
            "non-contextual",
            "noncontextual",
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
        ],
        "exclude": [],
    },
    {
        "name": "Network nonlocality",
        "include": [
            "network nonlocality",
            "network bell",
            "bilocal",
            "multilocal",
            "triangle network",
            "star network",
            "chain network",
            "inflation technique",
            "independent sources",
        ],
        "exclude": [
            "bell nonlocality",
        ],
    },
    {
        "name": "Device-independent",
        "include": [
            "device-independent",
            "device independent",
            "semi-device-independent",
            "semi-device independent",
            "di-qkd",
        ],
        "exclude": [],
    },
    {
        "name": "Synthetic dimensions",
        "include": [
            "feedforward",
            "synthetic dimension",
            "synthetic lattice",
            "synthetic gauge field",
            "synthetic magnetic field",
            "frequency dimension",
            "synthetic space",
            "photonic synthetic",
        ],
        "exclude": [],
    },
]


WATCHED_AUTHORS = [
    {"display": "Shihao Ru",               "given": "Shihao",    "family": "Ru"},
    {"display": "Victor V. Albert",         "given": "Victor",    "family": "Albert"},
    {"display": "Changhun Oh",              "given": "Changhun",  "family": "Oh"},
    {"display": "Chuan-Feng Li",            "given": "Chuan-Feng","family": "Li"},
    {"display": "Penghao Zhu",              "given": "Penghao",   "family": "Zhu"},
    {"display": "Jonatan Bohr Brask",       "given": "Jonatan",   "family": "Brask"},
    {"display": "Qin-Qin Wang",             "given": "Qin-Qin",   "family": "Wang"},
    {"display": "Xiang Cheng",              "given": "Xiang",     "family": "Cheng"},
    {"display": "Ulrik Lund Andersen",      "given": "Ulrik",     "family": "Andersen"},
    {"display": "Kishor Bharti",            "given": "Kishor",    "family": "Bharti"},
    {"display": "Anton Zeilinger",          "given": "Anton",     "family": "Zeilinger"},
    {"display": "A.I. Lvovsky",             "given": "A.I.",      "family": "Lvovsky"},
    {"display": "Damian Markham",           "given": "Damian",    "family": "Markham"},
    {"display": "Armin Tavakoli",           "given": "Armin",     "family": "Tavakoli"},
    {"display": "Taylor L. Hughes",         "given": "Taylor",    "family": "Hughes"},
    {"display": "Adan Cabello",             "given": "Adan",      "family": "Cabello"},
    {"display": "Man-Hong Yung",            "given": "Man-Hong",  "family": "Yung"},
    {"display": "Renato Renner",            "given": "Renato",    "family": "Renner"},
    {"display": "Xiaosong Ma",              "given": "Xiaosong",  "family": "Ma"},
    {"display": "Chao-Yang Lu",             "given": "Chao-Yang", "family": "Lu"},
    {"display": "Jonas S. Neergaard-Nielsen","given": "Jonas",    "family": "Neergaard-Nielsen"},
    {"display": "Johannes Borregaard",      "given": "Johannes",  "family": "Borregaard"},
    {"display": "Liang Jiang",              "given": "Liang",     "family": "Jiang"},
    {"display": "Peng Xue",                 "given": "Peng",      "family": "Xue"},
    {"display": "Hsin-Yuan Huang",          "given": "Hsin-Yuan", "family": "Huang"},
    {"display": "Dong-Ling Deng",           "given": "Dong-Ling", "family": "Deng"},
    {"display": "Shang Yu",                 "given": "Shang",     "family": "Yu"},
    {"display": "Yu Meng",                  "given": "Yu",        "family": "Meng"},
    {"display": "Junfeng Wang",             "given": "Junfeng",   "family": "Wang"},
    {"display": "Akira Furusawa",           "given": "Akira",     "family": "Furusawa"},
    {"display": "Jens Eisert",              "given": "Jens",      "family": "Eisert"},
    {"display": "Rafael Chaves",            "given": "Rafael",    "family": "Chaves"},
    {"display": "Jiaqi Jiang",              "given": "Jiaqi",     "family": "Jiang"},
    {"display": "Jiannis Pachos",           "given": "Jiannis",   "family": "Pachos"},
    {"display": "Quntao Zhuang",            "given": "Quntao",    "family": "Zhuang"},
]


STATE_FILE = "state.json"
STATE_MAX_AGE_DAYS = 8


def load_state() -> tuple[datetime.datetime | None, set[str]]:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        last_run = datetime.datetime.fromisoformat(data["last_run"])
        sent_ids = set(data.get("sent_ids", []))
        return last_run, sent_ids
    except (FileNotFoundError, KeyError, ValueError):
        return None, set()


def save_state(last_run: datetime.datetime, sent_ids: set[str]) -> None:
    cutoff = last_run - datetime.timedelta(days=STATE_MAX_AGE_DAYS)
    # Prune IDs we no longer need (we don't store submission dates per ID, so
    # we keep the full set and rely on MAX_AGE being longer than the lookback)
    data = {"last_run": last_run.isoformat(), "sent_ids": list(sent_ids)}
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def get_cutoff(last_run: datetime.datetime | None) -> tuple[datetime.datetime, datetime.datetime]:
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_run is not None:
        # Use last successful run as cutoff, with a 7-day hard cap
        cutoff = max(last_run, now - datetime.timedelta(days=7))
    elif now.weekday() == 0:
        cutoff = now - datetime.timedelta(days=3)
    else:
        cutoff = now - datetime.timedelta(days=1)
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


def _author_name_matches(paper_author: str, given: str, family: str) -> bool:
    pa = paper_author.lower()
    if family.lower() not in pa:
        return False
    given_l = given.lower()
    # Initials like "A.I." — match on first letter only
    if re.match(r"^[a-z]\.", given_l):
        return len(pa) > 0 and pa[0] == given_l[0]
    return given_l in pa


def match_watched_authors(paper: dict) -> list[str]:
    matched = []
    for wa in WATCHED_AUTHORS:
        if any(_author_name_matches(a, wa["given"], wa["family"]) for a in paper["authors"]):
            matched.append(wa["display"])
    return matched


def filter_papers(papers: list[dict], cutoff: datetime.datetime) -> list[dict]:
    return [p for p in papers if p["submitted"] >= cutoff]


def _paper_entry_block(paper: dict, highlight_authors: list[str] | None = None) -> dict:
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " et al."

    snippet = paper["abstract"][:200].rstrip()
    if len(paper["abstract"]) > 200:
        snippet += "..."

    watch_line = ""
    if highlight_authors:
        watch_line = f"\n:bust_in_silhouette: {', '.join(highlight_authors)}"

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*<{paper['url']}|{paper['title']}>*\n"
                f"{authors_str}{watch_line}\n"
                f"_{snippet}_"
            ),
        },
    }


def build_blocks(
    matched: dict[str, list[dict]],
    author_matched: list[dict],
    date: datetime.date,
    total: int,
    num_themes: int,
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
            blocks.append(_paper_entry_block(paper))
        blocks.append({"type": "divider"})

    if author_matched:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Author Watch* ({len(author_matched)} paper{'s' if len(author_matched) != 1 else ''})",
                },
            }
        )
        for paper in author_matched:
            blocks.append(_paper_entry_block(paper, highlight_authors=paper.get("matched_authors")))
        blocks.append({"type": "divider"})

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    author_note = f", {len(author_matched)} from author watch" if author_matched else ""
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{total} paper{'s' if total != 1 else ''} matched across "
                        f"{num_themes} theme{'s' if num_themes != 1 else ''}"
                        f"{author_note} | {timestamp}"
                    ),
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
    last_run, sent_ids = load_state()
    cutoff, now = get_cutoff(last_run)
    logger.info("Fetching quant-ph papers submitted since %s", cutoff.isoformat())

    papers = fetch_papers()
    if not papers:
        logger.error("No papers retrieved from arXiv.")
        sys.exit(1)

    recent = [p for p in filter_papers(papers, cutoff) if p["id"] not in sent_ids]
    logger.info("New papers in window (after dedup): %d", len(recent))

    theme_buckets: dict[str, list[dict]] = {}
    for paper in recent:
        themes = score_paper(paper)
        for theme in themes:
            theme_buckets.setdefault(theme, [])
            if len(theme_buckets[theme]) < config.MAX_PAPERS_PER_THEME:
                theme_buckets[theme].append(paper)

    author_watch: list[dict] = []
    author_watch_ids: set[str] = set()
    for paper in recent:
        if paper["id"] in author_watch_ids:
            continue
        matched_authors = match_watched_authors(paper)
        if matched_authors:
            paper = dict(paper, matched_authors=matched_authors)
            author_watch.append(paper)
            author_watch_ids.add(paper["id"])
            if len(author_watch) >= config.MAX_PAPERS_AUTHOR_WATCH:
                break

    if not theme_buckets and not author_watch:
        logger.info("No matching papers found.")
        save_state(now, sent_ids)
        success = send_no_papers_message(now.date())
        sys.exit(0 if success else 1)

    total_papers = sum(len(v) for v in theme_buckets.values())
    num_themes = len(theme_buckets)

    blocks = build_blocks(theme_buckets, author_watch, now.date(), total_papers, num_themes)
    fallback = (
        f"arXiv quant-ph Digest — {now.date()}: {total_papers} theme papers"
        + (f", {len(author_watch)} author watch papers." if author_watch else ".")
    )

    logger.info(
        "Sending Slack digest: %d theme papers across %d themes, %d author watch papers",
        total_papers, num_themes, len(author_watch),
    )
    success = send_slack_message(blocks, fallback)
    if success:
        new_ids = {p["id"] for p in recent}
        save_state(now, sent_ids | new_ids)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
