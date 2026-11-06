"""Configuration for the arXiv quant-ph Slack digest.

The webhook is read from the environment so it never lives in the repo.
In GitHub Actions it is injected from the SLACK_WEBHOOK_URL repository secret.
"""

import os

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# arXiv's OAI-PMH endpoint. This is the interface arXiv sanctions for bulk
# harvesting; the old Atom API at export.arxiv.org/api/query is answered with an
# empty-bodied HTTP 406 by arXiv's edge for every command-line client.
# (export.arxiv.org/oai2 redirects here.)
ARXIV_OAI_URL = os.environ.get("ARXIV_OAI_URL", "https://oaipmh.arxiv.org/oai")

# The OAI set to harvest. arXiv names quant-ph 'physics:quant-ph'.
ARXIV_OAI_SET = os.environ.get("ARXIV_OAI_SET", "physics:quant-ph")

# Safety valve on the resumptionToken loop. arXiv serves 2500 records per page
# and quant-ph runs ~350/day, so even a 7-day catch-up window fits in one or two
# pages; 20 only ever stops a runaway loop.
ARXIV_OAI_MAX_PAGES = int(os.environ.get("ARXIV_OAI_MAX_PAGES", "20"))

# Fallback when the OAI-PMH harvest fails: the RSS feed of the latest daily
# announcement. It is served separately from oaipmh.arxiv.org and stayed up
# through the OAI outages of 2026-11-02/03/05/06. It only ever holds one day, so
# days missed while OAI is down are backfilled by the next successful harvest.
ARXIV_RSS_URL = os.environ.get("ARXIV_RSS_URL", "https://rss.arxiv.org/rss/quant-ph")

# Include v2+ papers (replacements) in the digest.
INCLUDE_REPLACEMENTS = os.environ.get("INCLUDE_REPLACEMENTS", "1") not in ("0", "false", "")

# Network politeness / resilience.
# (connect, read) seconds. A healthy ListRecords page - 2-3 MB for a week of
# quant-ph - arrives in about 3 s, so the read timeout only ever trips when the
# server has stopped answering altogether.
ARXIV_TIMEOUT = (15, 90)

# Retries for network errors, timeouts and 5xx, with exponential backoff
# (20s, 40s, 80s, 160s, 300s). oaipmh.arxiv.org has been seen to stop answering
# entirely for several minutes - every request on 2026-11-02 and 2026-11-03 hit
# the read timeout - and the old 4 x 60 s schedule gave up after ~5 minutes and
# lost the day. This one rides out roughly 20 minutes before failing; the
# workflow's catch-up cron then tries again a couple of hours later. OAI-PMH flow
# control (503 + Retry-After) is honoured separately.
ARXIV_RETRIES = 6
ARXIV_BACKOFF_BASE = 20
ARXIV_BACKOFF_CAP = 300

# Calendar used for "has today's digest already gone out?" (--once-per-day).
DIGEST_TZ = "Europe/Berlin"
USER_AGENT = "arxiv-quant-ph-digest/1.0 (personal research digest; contact via GitHub)"
