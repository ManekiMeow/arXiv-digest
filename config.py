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

# Include v2+ papers (replacements) in the digest.
INCLUDE_REPLACEMENTS = os.environ.get("INCLUDE_REPLACEMENTS", "1") not in ("0", "false", "")

# Upper bound, in seconds, on the exponential backoff used when arXiv throttles
# us (406/429/503). A throttle window can outlast a few linear retries, so the
# delay grows 60s, 120s, 240s... until it hits this cap.
ARXIV_THROTTLE_BACKOFF_CAP = int(os.environ.get("ARXIV_THROTTLE_BACKOFF_CAP", "300"))

# Network politeness / resilience.
ARXIV_TIMEOUT = 60
ARXIV_RETRIES = 5
# arXiv's API terms of use ask for a descriptive User-Agent carrying a project
# URL and a contact address so they can reach the operator instead of blocking.
USER_AGENT = "arxiv-quant-ph-digest/1.0 (+https://github.com/ManekiMeow/arXiv-digest; mailto:ericaphysx@gmail.com)"
