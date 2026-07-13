# arXiv quant-ph Daily Digest

Fetches the latest quant-ph submissions from arXiv, scores them against five research themes, and sends a formatted daily digest to Slack using Block Kit.

## What it does

Each run:
1. Queries the arXiv API for recent `quant-ph` papers (last 24 hours; 72 hours on Mondays to cover the weekend gap).
2. Scores each paper by matching title and abstract against five themes using keyword lists.
3. Posts a structured Slack message with matched papers grouped by theme, including a linked title, authors, and abstract snippet.

## Themes monitored

- **Squeezed light experiment** — squeezed light, squeezing, homodyne, heterodyne, optical parametric oscillators, nonclassical light, photon statistics, quadrature noise.
- **Quantum computing experiment** — quantum processors, qubits, gate fidelity, superconducting circuits, trapped ions, quantum error correction, fault tolerance, surface codes, logical qubits.
- **Quantum learning** — quantum state/process tomography, shadow tomography, classical shadows, learning quantum channels. Excludes quantum machine learning, QML, and variational quantum approaches.
- **Quantum contextuality** — contextuality, Kochen–Specker, Bell inequalities, CHSH.
- **Proposals to realize quantum advantage** — quantum advantage, quantum supremacy, quantum speedup, near-term quantum, NISQ, quantum protocol proposals.

## Setup

### Requirements

- Python 3.11+
- A Slack incoming webhook URL

### Install dependencies

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_WEBHOOK_URL` | Yes | Slack incoming webhook URL for your target channel |

Set it before running:

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

## Running manually

```bash
python digest.py
```

## Scheduling with cron

Run daily at 4:00 AM UTC (5:00 AM CET / 6:00 AM CEST in summer):

```cron
0 4 * * * cd /path/to/arXiv-digest && SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..." python digest.py >> /var/log/arxiv-digest.log 2>&1
```

Adjust the hour to your preferred local time. arXiv typically makes new submissions available between 00:00–02:00 UTC, so 04:00 UTC is a safe window.

## Configuration

Edit `config.py` to adjust:

- `MAX_PAPERS_PER_THEME` — maximum papers shown per theme (default: 5)
- `ARXIV_MAX_RESULTS` — how many papers to fetch from arXiv per run (default: 300)
