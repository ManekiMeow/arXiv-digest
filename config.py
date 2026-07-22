import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
MAX_PAPERS_PER_THEME = 5
MAX_PAPERS_AUTHOR_WATCH = 20
ARXIV_MAX_RESULTS = 300
