"""Configuration for the arXiv quant-ph Slack digest.

The webhook is read from the environment so it never lives in the repo.
In GitHub Actions it is injected from the SLACK_WEBHOOK_URL repository secret.
"""

import os

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# How many entries to pull from the arXiv API in one request.
# quant-ph runs roughly 150-250 announcements/day including cross-lists;
# sorting by lastUpdatedDate also surfaces replacements, which pushes the
# count higher. 800 gives comfortable headroom for a 3-day Monday window.
# The API hard-caps a single request at 2000.
ARXIV_MAX_RESULTS = int(os.environ.get("ARXIV_MAX_RESULTS", "800"))

# Per-section caps so a noisy day cannot produce an unreadable wall of text.
MAX_PAPERS_PER_THEME = int(os.environ.get("MAX_PAPERS_PER_THEME", "8"))
MAX_PAPERS_AUTHOR_WATCH = int(os.environ.get("MAX_PAPERS_AUTHOR_WATCH", "15"))
MAX_PAPERS_PER_THEME_REPLACEMENTS = int(
    os.environ.get("MAX_PAPERS_PER_THEME_REPLACEMENTS", "5")
)

# Include v2+ papers (replacements) in the digest.
INCLUDE_REPLACEMENTS = os.environ.get("INCLUDE_REPLACEMENTS", "1") not in ("0", "false", "")

# Network politeness / resilience.
ARXIV_TIMEOUT = 60
ARXIV_RETRIES = 4
USER_AGENT = "arxiv-quant-ph-digest/1.0 (personal research digest; contact via GitHub)"
