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

# Include v2+ papers (replacements) in the digest.
INCLUDE_REPLACEMENTS = os.environ.get("INCLUDE_REPLACEMENTS", "1") not in ("0", "false", "")

# Network politeness / resilience.
ARXIV_TIMEOUT = 60

# Modest linear retries (5s, 10s, 15s) for genuine network errors. OAI-PMH flow
# control arrives as 503 + Retry-After and is honoured separately; there is no
# long throttle backoff any more, so a broken harvest fails fast and loudly.
ARXIV_RETRIES = 4
USER_AGENT = "arxiv-quant-ph-digest/1.0 (personal research digest; contact via GitHub)"
