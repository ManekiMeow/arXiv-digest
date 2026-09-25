"""arXiv quant-ph -> Slack digest.

Filters the daily quant-ph announcements by keyword themes and a watched-author
list, then posts a Block Kit digest to a Slack incoming webhook.

Run with --dry-run to print the payload instead of posting.
"""

import re
import sys
import json
import time
import email.utils
import logging
import argparse
import datetime
import unicodedata
import xml.etree.ElementTree as ET

import requests

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# The OAI-PMH envelope and arXiv's raw metadata format live in two different
# namespaces, and ElementTree needs both spelled out.
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "raw": "http://arxiv.org/OAI/arXivRaw/",
}

# arXiv's terms of use ask for no more than one request every three seconds.
OAI_PAGE_DELAY = 3

# Never let a server-supplied Retry-After stall the job for longer than this.
RETRY_AFTER_CAP = 300

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


def missed_weekdays(last_run, now):
    """Count Mon-Fri days between two runs that should have produced a digest.

    A normal weekday gap is 1 day and a Friday->Monday gap is 3, so both come
    out as 0 here; anything above that means a scheduled run never happened.
    """
    day = last_run.date() + datetime.timedelta(days=1)
    missed = 0
    while day < now.date():
        if day.weekday() < 5:
            missed += 1
        day += datetime.timedelta(days=1)
    return missed


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

def fetch_papers(from_date=None):
    """Harvest quant-ph records from arXiv's OAI-PMH endpoint.

    OAI-PMH applies the window server-side via `from`, and pages with a
    resumptionToken. The spec allows the token to travel with *no* other
    parameter, so every page after the first is a fresh two-key query.

    `from` has day granularity (arXiv's Identify reports YYYY-MM-DD), so it can
    only ever be a coarse pre-filter; filter_papers() remains the real gate.
    """
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "arXivRaw",
        "set": config.ARXIV_OAI_SET,
    }
    if from_date is not None:
        params["from"] = from_date.isoformat()
    # No `until`: arXiv advises against it for incremental harvesting, and an
    # open-ended window cannot silently clip the newest announcements.

    papers = []
    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
            }
        )
        for page in range(1, config.ARXIV_OAI_MAX_PAGES + 1):
            xml_text = _oai_request(session, params)
            if xml_text is None:
                # Half a harvest is worse than none: returning it would advance
                # the state past papers we never saw. Fail and let the next run
                # cover the window again.
                logger.error(
                    "OAI-PMH harvest failed on page %d; discarding %d records already read",
                    page, len(papers),
                )
                return []

            batch, token = parse_oai_response(xml_text)
            papers.extend(batch)
            logger.info("OAI-PMH page %d: %d records (%d total)", page, len(batch), len(papers))

            if not token:
                return papers
            # A resumptionToken is only valid until the next UTC midnight, so it
            # is used inside this loop and never persisted.
            params = {"verb": "ListRecords", "resumptionToken": token}
            time.sleep(OAI_PAGE_DELAY)

        logger.warning(
            "Stopped after ARXIV_OAI_MAX_PAGES=%d pages with a resumptionToken still "
            "pending: the harvest is incomplete. Raise ARXIV_OAI_MAX_PAGES.",
            config.ARXIV_OAI_MAX_PAGES,
        )
    return papers


def _retry_after(response, default):
    """Seconds to wait per the response's Retry-After header, else `default`."""
    try:
        seconds = int(response.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return default
    return max(1, min(seconds, RETRY_AFTER_CAP))


def _oai_request(session, params):
    """Perform one OAI-PMH request. Returns the response body, or None."""
    for attempt in range(1, config.ARXIV_RETRIES + 1):
        delay = 5 * attempt
        try:
            response = session.get(
                config.ARXIV_OAI_URL, params=params, timeout=config.ARXIV_TIMEOUT
            )
            if response.status_code == 503:
                # OAI-PMH signals flow control, not failure, with 503 +
                # Retry-After. Wait exactly as long as we are told to.
                delay = _retry_after(response, delay)
                logger.info("OAI-PMH flow control (503): waiting %ds", delay)
            else:
                response.raise_for_status()
                return response.text
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            logger.warning("OAI-PMH request failed (attempt %d) with HTTP %s: %s",
                           attempt, status, exc)
            logger.warning("OAI-PMH response headers: %s",
                           dict(getattr(exc.response, "headers", {}) or {}))
            logger.warning("OAI-PMH response body (first 500 chars): %s",
                           (getattr(exc.response, "text", "") or "")[:500])
            if status == 429:
                delay = _retry_after(exc.response, delay)
            elif status is not None and 400 <= status < 500:
                # Not transient: a rejected or malformed request stays rejected.
                logger.error("arXiv rejected the request with HTTP %s; not retrying", status)
                return None
        except requests.RequestException as exc:
            logger.warning("OAI-PMH request failed (attempt %d): %s", attempt, exc)

        if attempt < config.ARXIV_RETRIES:
            time.sleep(delay)
        else:
            logger.error("Giving up on the OAI-PMH request after %d attempts",
                         config.ARXIV_RETRIES)
    return None


def parse_oai_response(xml_text):
    """Parse a ListRecords response into (papers, resumption_token)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("Failed to parse the OAI-PMH response: %s", exc)
        return [], None

    error = root.find("oai:error", NS)
    if error is not None:
        code = error.get("code", "")
        if code == "noRecordsMatch":
            # An empty window is a legitimate answer, not a failure.
            logger.info("OAI-PMH reports no records in the requested window")
        else:
            logger.error("OAI-PMH error %s: %s", code, (error.text or "").strip())
        return [], None

    list_records = root.find("oai:ListRecords", NS)
    if list_records is None:
        logger.error("OAI-PMH response contains no ListRecords element")
        return [], None

    papers = []
    for record in list_records.findall("oai:record", NS):
        paper = _parse_record(record)
        if paper is not None:
            papers.append(paper)

    token_el = list_records.find("oai:resumptionToken", NS)
    token = token_el.text.strip() if token_el is not None and token_el.text else None
    return papers, token


def _text(element):
    return element.text.strip() if element is not None and element.text else ""


def _norm(text):
    """Collapse the newlines and padding arXiv wraps its text fields in."""
    return " ".join(text.split())


def _strip_parens(text):
    """Drop parenthesised author affiliations, innermost group first."""
    for _ in range(5):
        stripped = re.sub(r"\([^()]*\)", " ", text)
        if stripped == text:
            break
        text = stripped
    return text


def _split_top_level(text):
    """Split on commas and ' and ' that are not inside parentheses."""
    parts, buf, depth, i = [], [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            if ch == ",":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
            if text[i:i + 5] == " and " or (i == 0 and text[i:i + 4] == "and "):
                parts.append("".join(buf))
                buf = []
                i += 5 if text[i:i + 5] == " and " else 4
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def parse_authors(text):
    """Split arXivRaw's single authors string into 'Given Family' names.

    arXivRaw gives one flat line - "Sakil Khan, Dipankar Home and Sachin Jain" -
    where the Atom feed gave structured <author> elements, so the names have to
    be recovered here. Affiliation markers and the trailing affiliation legend
    are dropped, because _author_name_matches() keys off the *last* tokens being
    the family name.
    """
    names = []
    for part in _split_top_level(_norm(text)):
        name = _norm(_strip_parens(part)).strip(" ,;")
        # A pure affiliation legend, e.g. "((1) MIT, (2) Caltech)", strips empty.
        if name and name.lower() not in ("et al.", "et al"):
            names.append(name)
    return names


def _parse_versions(meta):
    """Return (version, submitted, updated) from the <version> elements.

    arXivRaw repeats <version version="vN"> with an RFC-822 <date> at second
    resolution - the same semantics the Atom feed's published/updated carried.
    The number of versions, not any date comparison, is what makes a paper a
    replacement: submission and announcement routinely fall on different days,
    so created != updated says nothing about revisions.
    """
    versions = []
    for version_el in meta.findall("raw:version", NS):
        match = re.fullmatch(r"v(\d+)", (version_el.get("version") or "").strip())
        date_text = _text(version_el.find("raw:date", NS))
        if not match or not date_text:
            continue
        try:
            stamp = email.utils.parsedate_to_datetime(date_text)
        except (TypeError, ValueError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.timezone.utc)
        versions.append((int(match.group(1)), stamp))

    if not versions:
        return None, None, None
    versions.sort()
    return versions[-1][0], versions[0][1], versions[-1][1]


def _parse_record(record):
    """Turn one OAI-PMH <record> into the pipeline's paper dict, or None."""
    meta = record.find("oai:metadata/raw:arXivRaw", NS)
    if meta is None:
        # Withdrawn papers arrive as <header status="deleted"> with no metadata.
        header = record.find("oai:header", NS)
        identifier = _text(header.find("oai:identifier", NS)) if header is not None else "?"
        logger.info("Skipping record without arXivRaw metadata: %s", identifier)
        return None

    base_id = _text(meta.find("raw:id", NS))
    title = _text(meta.find("raw:title", NS))
    version, submitted, updated = _parse_versions(meta)
    if not base_id or not title or version is None:
        logger.warning("Skipping malformed record (id=%r, versions=%r)", base_id, version)
        return None

    categories = _text(meta.find("raw:categories", NS)).split()
    primary_cat = categories[0] if categories else ""

    return {
        "id": f"{base_id}v{version}",
        "base_id": base_id,
        "version": version,
        "title": _norm(title),
        "abstract": _norm(_text(meta.find("raw:abstract", NS))),
        "authors": parse_authors(_text(meta.find("raw:authors", NS))),
        "categories": categories,
        "submitted": submitted,
        "updated": updated,
        "is_replacement": version > 1,
        "is_crosslist": primary_cat != "quant-ph",
        "primary_category": primary_cat,
        "url": f"https://arxiv.org/abs/{base_id}",
    }


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


def build_blocks(theme_buckets, author_matched, replacements, date, total, num_themes):
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
            theme_buckets.setdefault(theme, []).append(paper)

    for paper in recent:
        if paper["is_replacement"] or not paper["matched_authors"]:
            continue
        if paper["base_id"] in seen_author_ids:
            continue
        author_watch.append(paper)
        seen_author_ids.add(paper["base_id"])

    if config.INCLUDE_REPLACEMENTS:
        for paper in recent:
            if not paper["is_replacement"]:
                continue
            if not (paper["matched_authors"] or score_paper(paper)):
                continue
            replacements.append(paper)

    return theme_buckets, author_watch, replacements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print the Slack payload instead of posting")
    parser.add_argument("--from-file",
                        help="parse a saved OAI-PMH ListRecords response instead of fetching")
    args = parser.parse_args()

    last_run, sent = load_state()
    cutoff, now = get_cutoff(last_run)
    # OAI-PMH `from` is day-granular, so it is floored to the window's UTC date
    # and pulled back one more day: a coarse server-side pre-filter that can only
    # ever over-fetch. The exact window is still enforced by filter_papers(), and
    # papers re-offered from an earlier run are dropped by their versioned id
    # (state.json keeps 8 days of ids, longer than the 7-day maximum window).
    harvest_from = cutoff.date() - datetime.timedelta(days=1)
    logger.info("Window: entries updated since %s (harvesting from %s)",
                cutoff.isoformat(), harvest_from.isoformat())

    if last_run is not None:
        missed = missed_weekdays(last_run, now)
        if missed:
            logger.warning(
                "No digest ran on %d scheduled weekday(s) since %s - the "
                "schedule was skipped or never fired. This run covers the gap.",
                missed, last_run.isoformat(),
            )

    if args.from_file:
        with open(args.from_file) as f:
            papers, _ = parse_oai_response(f.read())
    else:
        papers = fetch_papers(harvest_from)

    if not papers:
        logger.error("No papers retrieved from arXiv.")
        sys.exit(1)

    recent = [p for p in filter_papers(papers, cutoff) if p["id"] not in sent]
    logger.info("Entries in window after dedup: %d of %d fetched", len(recent), len(papers))

    theme_buckets, author_watch, replacements = build_digest(recent)

    if not theme_buckets and not author_watch and not replacements:
        logger.info("No matching papers found.")
        if args.dry_run:
            print("(no matching papers)")
            sys.exit(0)
        save_state(now, sent)
        sys.exit(0 if send_no_papers_message(now.date()) else 1)

    total = sum(len(v) for v in theme_buckets.values())
    blocks = build_blocks(theme_buckets, author_watch, replacements,
                          now.date(), total, len(theme_buckets))
    fallback = (f"arXiv quant-ph Digest - {now.date()}: {total} theme papers, "
                f"{len(author_watch)} author watch, {len(replacements)} replacements")

    logger.info("Digest: %d theme papers / %d themes, %d author watch, %d replacements",
                total, len(theme_buckets), len(author_watch), len(replacements))

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
