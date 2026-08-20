"""arXiv quant-ph -> Slack digest.

Filters the daily quant-ph announcements by keyword themes and a watched-author
list, then posts a Block Kit digest to a Slack incoming webhook.

Run with --dry-run to print the payload instead of posting.
"""

import re
import sys
import json
import time
import logging
import argparse
import datetime
import unicodedata
import xml.etree.ElementTree as ET

import requests

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"

# Slack rejects a message with more than 50 blocks.
SLACK_MAX_BLOCKS = 50
BLOCKS_PER_MESSAGE = 45

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
        "name": "Quantum learning",
        "include": [
            "learning",
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
    {"display": "Shihao Ru",                 "given": "Shihao",    "family": "Ru"},
    {"display": "Victor V. Albert",          "given": "Victor",    "family": "Albert"},
    {"display": "Changhun Oh",               "given": "Changhun",  "family": "Oh"},
    {"display": "Chuan-Feng Li",             "given": "Chuan-Feng","family": "Li"},
    {"display": "Penghao Zhu",               "given": "Penghao",   "family": "Zhu"},
    {"display": "Jonatan Bohr Brask",        "given": "Jonatan",   "family": "Brask"},
    {"display": "Xiang Cheng",               "given": "Xiang",     "family": "Cheng"},
    {"display": "Ulrik Lund Andersen",       "given": "Ulrik",     "family": "Andersen"},
    {"display": "Kishor Bharti",             "given": "Kishor",    "family": "Bharti"},
    {"display": "Anton Zeilinger",           "given": "Anton",     "family": "Zeilinger"},
    {"display": "A.I. Lvovsky",              "given": "A.I.",      "family": "Lvovsky"},
    {"display": "Damian Markham",            "given": "Damian",    "family": "Markham"},
    {"display": "Armin Tavakoli",            "given": "Armin",     "family": "Tavakoli"},
    {"display": "Taylor L. Hughes",          "given": "Taylor",    "family": "Hughes"},
    {"display": "Adan Cabello",              "given": "Adan",      "family": "Cabello"},
    {"display": "Man-Hong Yung",             "given": "Man-Hong",  "family": "Yung"},
    {"display": "Renato Renner",             "given": "Renato",    "family": "Renner"},
    {"display": "Xiaosong Ma",               "given": "Xiaosong",  "family": "Ma"},
    {"display": "Chao-Yang Lu",              "given": "Chao-Yang", "family": "Lu"},
    {"display": "Jonas S. Neergaard-Nielsen","given": "Jonas",     "family": "Neergaard-Nielsen"},
    {"display": "Johannes Borregaard",       "given": "Johannes",  "family": "Borregaard"},
    {"display": "Liang Jiang",               "given": "Liang",     "family": "Jiang"},
    {"display": "Peng Xue",                  "given": "Peng",      "family": "Xue"},
    {"display": "Hsin-Yuan Huang",           "given": "Hsin-Yuan", "family": "Huang"},
    {"display": "Dong-Ling Deng",            "given": "Dong-Ling", "family": "Deng"},
    {"display": "Shang Yu",                  "given": "Shang",     "family": "Yu"},
    {"display": "Yu Meng",                   "given": "Yu",        "family": "Meng"},
    {"display": "Akira Furusawa",            "given": "Akira",     "family": "Furusawa"},
    {"display": "Jens Eisert",               "given": "Jens",      "family": "Eisert"},
    {"display": "Rafael Chaves",             "given": "Rafael",    "family": "Chaves"},
    {"display": "Jiaqi Jiang",               "given": "Jiaqi",     "family": "Jiang"},
    {"display": "Jiannis Pachos",            "given": "Jiannis",   "family": "Pachos"},
    {"display": "Quntao Zhuang",             "given": "Quntao",    "family": "Zhuang"},
    {"display": "Leonardo Banchi",           "given": "Leonardo",  "family": "Banchi"},
    {"display": "Jordan Cotler",             "given": "Jordan",    "family": "Cotler"},
]

STATE_FILE = "state.json"
STATE_MAX_AGE_DAYS = 8


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def load_state():
    """Return (last_run, sent) where sent maps arXiv id -> ISO date seen."""
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        last_run = datetime.datetime.fromisoformat(data["last_run"])
        raw = data.get("sent_ids", {})
        if isinstance(raw, list):
            # Migrate the old list format; assume everything was seen at last_run.
            sent = {pid: last_run.isoformat() for pid in raw}
        else:
            sent = dict(raw)
        return last_run, sent
    except (FileNotFoundError, KeyError, ValueError, TypeError):
        return None, {}


def save_state(last_run, sent):
    """Persist state, dropping ids older than STATE_MAX_AGE_DAYS."""
    cutoff = last_run - datetime.timedelta(days=STATE_MAX_AGE_DAYS)
    pruned = {}
    for pid, seen_iso in sent.items():
        try:
            seen = datetime.datetime.fromisoformat(seen_iso)
        except (ValueError, TypeError):
            continue
        if seen >= cutoff:
            pruned[pid] = seen_iso
    dropped = len(sent) - len(pruned)
    if dropped:
        logger.info("Pruned %d state entries older than %d days", dropped, STATE_MAX_AGE_DAYS)
    with open(STATE_FILE, "w") as f:
        json.dump({"last_run": last_run.isoformat(), "sent_ids": pruned}, f, indent=1)


def get_cutoff(last_run):
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_run is not None:
        cutoff = max(last_run, now - datetime.timedelta(days=7))
    elif now.weekday() == 0:
        cutoff = now - datetime.timedelta(days=3)
    else:
        cutoff = now - datetime.timedelta(days=1)
    return cutoff, now


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def fetch_papers():
    """Fetch recent quant-ph entries, newest update first.

    Sorting by lastUpdatedDate (rather than submittedDate) is what makes
    replacements visible: a v2 posted today has an old `published` but a
    fresh `updated`.
    """
    params = {
        "search_query": "cat:quant-ph",
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
        "max_results": config.ARXIV_MAX_RESULTS,
    }
    headers = {"User-Agent": config.USER_AGENT}

    last_exc = None
    for attempt in range(1, config.ARXIV_RETRIES + 1):
        try:
            response = requests.get(
                ARXIV_API_URL, params=params, headers=headers, timeout=config.ARXIV_TIMEOUT
            )
            response.raise_for_status()
            papers = parse_feed(response.text)
            if papers:
                return papers
            # The arXiv API intermittently returns an empty but valid feed.
            logger.warning("arXiv returned an empty feed (attempt %d)", attempt)
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("arXiv fetch failed (attempt %d): %s", attempt, exc)
        if attempt < config.ARXIV_RETRIES:
            time.sleep(5 * attempt)

    if last_exc:
        logger.error("Giving up on arXiv fetch: %s", last_exc)
    return []


def parse_feed(xml_text):
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

        if any(el is None for el in (title_el, abstract_el, published_el, updated_el, id_el)):
            continue

        authors = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        versioned_id = id_el.text.strip().split("/abs/")[-1]
        base_id = re.sub(r"v\d+$", "", versioned_id)
        version_match = re.search(r"v(\d+)$", versioned_id)
        version = int(version_match.group(1)) if version_match else 1

        try:
            submitted = _parse_ts(published_el.text)
            updated = _parse_ts(updated_el.text)
        except ValueError:
            continue

        primary = entry.find("arxiv:primary_category", ns)
        primary_cat = primary.get("term") if primary is not None else ""

        papers.append(
            {
                "id": versioned_id,
                "base_id": base_id,
                "version": version,
                "title": " ".join(title_el.text.split()),
                "abstract": " ".join(abstract_el.text.split()),
                "authors": authors,
                "submitted": submitted,
                "updated": updated,
                "is_replacement": version > 1,
                "is_crosslist": primary_cat != "quant-ph",
                "primary_category": primary_cat,
                "url": f"https://arxiv.org/abs/{base_id}",
            }
        )

    return papers


def _parse_ts(text):
    return datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def score_paper(paper):
    text = (paper["title"] + " " + paper["abstract"]).lower()
    matched = []
    for theme in THEMES:
        if any(kw in text for kw in theme["exclude"]):
            continue
        if any(kw in text for kw in theme["include"]):
            matched.append(theme["name"])
    return matched


def _fold(s):
    """Lowercase and strip diacritics, so 'Adán' matches a watchlist 'Adan'."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _name_parts(s):
    """Split a name into comparable parts across spaces, dots and hyphens."""
    return [p for p in re.split(r"[\s.\-]+", _fold(s)) if p]


def _part_matches(a, b):
    """Two name parts match if equal, or if one is the other's initial."""
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return a == b


def _author_name_matches(paper_author, given, family):
    """Token-aware match against 'Given Family' as arXiv renders it.

    Requires the trailing tokens to be the family name and the leading tokens
    to be consistent with the watched given name, so 'Yuhao Meng' no longer
    matches a watch entry for 'Yu Meng'.
    """
    author_parts = _name_parts(paper_author)
    family_parts = _name_parts(family)
    given_parts = _name_parts(given)

    if not author_parts or not family_parts or not given_parts:
        return False

    n = len(family_parts)
    if len(author_parts) <= n:
        return False
    if author_parts[-n:] != family_parts:
        return False

    author_given = author_parts[:-n]
    compare = min(len(author_given), len(given_parts))
    if compare == 0:
        return False
    return all(_part_matches(author_given[i], given_parts[i]) for i in range(compare))


def match_watched_authors(paper):
    matched = []
    for wa in WATCHED_AUTHORS:
        if any(_author_name_matches(a, wa["given"], wa["family"]) for a in paper["authors"]):
            matched.append(wa["display"])
    return matched


def filter_papers(papers, cutoff):
    """Keep entries whose *announcement* moment falls in the window."""
    return [p for p in papers if p["updated"] >= cutoff]


# --------------------------------------------------------------------------
# Slack rendering
# --------------------------------------------------------------------------

def _paper_entry_block(paper, highlight_authors=None):
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " et al."

    snippet = paper["abstract"][:200].rstrip()
    if len(paper["abstract"]) > 200:
        snippet += "..."

    tags = []
    if paper["is_replacement"]:
        tags.append(f"v{paper['version']}")
    if paper["is_crosslist"]:
        tags.append(f"cross-list from {paper['primary_category']}")
    tag_str = f"  `{' · '.join(tags)}`" if tags else ""

    watch_line = ""
    if highlight_authors:
        watch_line = f"\n:bust_in_silhouette: {', '.join(highlight_authors)}"

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*<{paper['url']}|{_esc(paper['title'])}>*{tag_str}\n"
                f"{_esc(authors_str)}{watch_line}\n"
                f"_{_esc(snippet)}_"
            ),
        },
    }


def _esc(text):
    """Slack mrkdwn requires these three escaped."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def build_blocks(theme_buckets, author_matched, replacements, date, total, num_themes, dropped):
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"arXiv quant-ph Digest - {date.strftime('%Y-%m-%d')}",
                "emoji": False,
            },
        },
        {"type": "divider"},
    ]

    for theme_name, papers in theme_buckets.items():
        blocks.append(_section(f"*{theme_name}* ({_plural(len(papers), 'paper')})"))
        for paper in papers:
            blocks.append(_paper_entry_block(paper))
        blocks.append({"type": "divider"})

    if author_matched:
        blocks.append(_section(f"*Author Watch* ({_plural(len(author_matched), 'paper')})"))
        for paper in author_matched:
            blocks.append(_paper_entry_block(paper, highlight_authors=paper.get("matched_authors")))
        blocks.append({"type": "divider"})

    if replacements:
        blocks.append(_section(f"*Replacements* ({_plural(len(replacements), 'paper')})"))
        for paper in replacements:
            blocks.append(_paper_entry_block(paper, highlight_authors=paper.get("matched_authors")))
        blocks.append({"type": "divider"})

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes = [f"{_plural(total, 'paper')} matched across {_plural(num_themes, 'theme')}"]
    if author_matched:
        notes.append(f"{len(author_matched)} from author watch")
    if replacements:
        notes.append(f"{len(replacements)} replacements")
    if dropped:
        notes.append(f":warning: {dropped} further matches hidden by per-section caps")

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " | ".join(notes) + f" | {timestamp}"}],
        }
    )
    return blocks


def chunk_blocks(blocks):
    """Split into Slack-legal messages, keeping the header on the first."""
    if len(blocks) <= SLACK_MAX_BLOCKS:
        return [blocks]
    chunks = []
    head, rest = blocks[:2], blocks[2:]
    first = True
    while rest:
        take = BLOCKS_PER_MESSAGE - (len(head) if first else 1)
        piece = rest[:take]
        rest = rest[take:]
        if first:
            chunks.append(head + piece)
            first = False
        else:
            chunks.append([_section("_...continued_")] + piece)
    return chunks


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

def _post(payload):
    response = requests.post(
        config.SLACK_WEBHOOK_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=15,
    )
    response.raise_for_status()


def send_slack_message(blocks, fallback_text):
    if not config.SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not set.")
        return False
    try:
        for i, chunk in enumerate(chunk_blocks(blocks)):
            _post({"text": fallback_text, "blocks": chunk})
            if i:
                time.sleep(1)
    except requests.RequestException as exc:
        logger.error("Failed to send Slack message: %s", exc)
        return False
    return True


def send_no_papers_message(date):
    if not config.SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not set.")
        return False
    text = f"arXiv quant-ph Digest - {date.strftime('%Y-%m-%d')}: No matching papers today."
    try:
        _post({"text": text})
    except requests.RequestException as exc:
        logger.error("Failed to send Slack message: %s", exc)
        return False
    return True


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build_digest(recent):
    """Bucket papers into themes, author watch and replacements."""
    dropped = 0
    theme_buckets = {}
    author_watch = []
    replacements = []
    seen_author_ids = set()

    for paper in recent:
        paper["matched_authors"] = match_watched_authors(paper)

    for paper in recent:
        if paper["is_replacement"]:
            continue
        for theme in score_paper(paper):
            bucket = theme_buckets.setdefault(theme, [])
            if len(bucket) < config.MAX_PAPERS_PER_THEME:
                bucket.append(paper)
            else:
                dropped += 1

    for paper in recent:
        if paper["is_replacement"] or not paper["matched_authors"]:
            continue
        if paper["base_id"] in seen_author_ids:
            continue
        if len(author_watch) >= config.MAX_PAPERS_AUTHOR_WATCH:
            dropped += 1
            continue
        author_watch.append(paper)
        seen_author_ids.add(paper["base_id"])

    if config.INCLUDE_REPLACEMENTS:
        for paper in recent:
            if not paper["is_replacement"]:
                continue
            if not (paper["matched_authors"] or score_paper(paper)):
                continue
            if len(replacements) >= config.MAX_PAPERS_PER_THEME_REPLACEMENTS:
                dropped += 1
                continue
            replacements.append(paper)

    return theme_buckets, author_watch, replacements, dropped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print the Slack payload instead of posting")
    parser.add_argument("--from-file", help="parse a saved arXiv API response instead of fetching")
    args = parser.parse_args()

    last_run, sent = load_state()
    cutoff, now = get_cutoff(last_run)
    logger.info("Window: entries updated since %s", cutoff.isoformat())

    if args.from_file:
        with open(args.from_file) as f:
            papers = parse_feed(f.read())
    else:
        papers = fetch_papers()

    if not papers:
        logger.error("No papers retrieved from arXiv.")
        sys.exit(1)

    # If we filled the request quota *and* the oldest entry is still inside the
    # window, the response was truncated and matches were silently lost.
    oldest = min(p["updated"] for p in papers)
    if len(papers) >= config.ARXIV_MAX_RESULTS and oldest >= cutoff:
        logger.warning(
            "ARXIV_MAX_RESULTS=%d is too low: the response was capped and its oldest "
            "entry (%s) is still inside the window, so older matches were cut off. "
            "Raise ARXIV_MAX_RESULTS.",
            config.ARXIV_MAX_RESULTS, oldest.isoformat(),
        )

    recent = [p for p in filter_papers(papers, cutoff) if p["id"] not in sent]
    logger.info("Entries in window after dedup: %d of %d fetched", len(recent), len(papers))

    theme_buckets, author_watch, replacements, dropped = build_digest(recent)

    if not theme_buckets and not author_watch and not replacements:
        logger.info("No matching papers found.")
        if args.dry_run:
            print("(no matching papers)")
            sys.exit(0)
        save_state(now, sent)
        sys.exit(0 if send_no_papers_message(now.date()) else 1)

    total = sum(len(v) for v in theme_buckets.values())
    blocks = build_blocks(theme_buckets, author_watch, replacements,
                          now.date(), total, len(theme_buckets), dropped)
    fallback = (f"arXiv quant-ph Digest - {now.date()}: {total} theme papers, "
                f"{len(author_watch)} author watch, {len(replacements)} replacements")

    logger.info("Digest: %d theme papers / %d themes, %d author watch, %d replacements, %d dropped",
                total, len(theme_buckets), len(author_watch), len(replacements), dropped)

    if args.dry_run:
        for i, chunk in enumerate(chunk_blocks(blocks), 1):
            print(f"===== message {i} ({len(chunk)} blocks) =====")
            print(json.dumps({"text": fallback, "blocks": chunk}, indent=2, ensure_ascii=False))
        sys.exit(0)

    if send_slack_message(blocks, fallback):
        for p in recent:
            sent[p["id"]] = now.isoformat()
        save_state(now, sent)
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
