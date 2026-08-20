# arXiv quant-ph → Slack digest

Posts a filtered digest of the daily arXiv quant-ph announcements to a Slack
channel at **04:00 Europe/Berlin, Monday–Friday**, filtered by keyword themes
and a watched-author list.

## Setup (about five minutes)

1. **Create a repo** and drop these files in at the top level:

   ```
   digest.py
   config.py
   test_digest.py
   requirements.txt
   .github/workflows/digest.yml
   ```

   A private repo is fine — Actions minutes are free for both public and
   private personal repos.

2. **Add the webhook as a secret.** In the repo: *Settings → Secrets and
   variables → Actions → New repository secret*.

   - Name: `SLACK_WEBHOOK_URL`
   - Value: your `https://hooks.slack.com/services/...` URL

   Do not put it in `config.py` — `config.py` reads it from the environment
   precisely so it never lands in git history.

3. **Test before scheduling.** Go to *Actions → arXiv quant-ph digest → Run
   workflow*. Leave **dry_run** checked: it prints the Block Kit payload to the
   job log without posting to Slack. Uncheck it once the output looks right and
   the message lands in the channel.

That's it. The schedule takes over the next weekday morning.

## How the 04:00 schedule survives DST

GitHub cron is UTC-only and ignores daylight saving. So two crons are
registered — `0 2 * * 1-5` and `0 3 * * 1-5` — and the first step in the job
checks `TZ=Europe/Berlin date +%H` and exits unless the local hour is `04`.
Exactly one fires per day, year-round, with no edit needed in March or October.

One caveat that is GitHub's, not this script's: scheduled workflows are
queued on a best-effort basis and can be delayed by 5–30 minutes when the
Actions fleet is busy. If the digest must land at exactly 04:00, this is the
wrong scheduler.

## State and de-duplication

`state.json` holds the last run timestamp and the ids already posted, and is
carried between runs by `actions/cache`. Entries older than
`STATE_MAX_AGE_DAYS` (8) are pruned on every save.

If the cache is ever evicted — GitHub drops caches untouched for 7 days, which
daily runs will not hit — the script falls back to a 1-day lookback (3 days on
Mondays). Worst case you see one repeated digest, never a silent gap.

## What changed from the original script

- **Replacements now appear.** The query sorts by `lastUpdatedDate` instead of
  `submittedDate`, and the window is applied to `updated` rather than
  `published`. As written before, a v2 could never surface: it has an old
  `published` date and was filtered out before it was ever scored. Replacements
  get their own section and are excluded from the theme buckets so they do not
  crowd out new work.
- **`save_state` actually prunes.** It computed a `cutoff` and then never used
  it, so `sent_ids` grew without bound.
- **Author matching is token-aware and accent-folding.** The old substring test
  had errors in both directions:

  | author on paper | watch entry | old | new |
  |---|---|---|---|
  | `Yuhao Meng` | Yu Meng | matched (wrong) | no match |
  | `Adán Cabello` | Adan Cabello | no match (wrong) | matched |

  The accent case matters — arXiv renders the name as `Adán Cabello`, so that
  watch entry never fired. Initials still work in both directions: `C.-F. Li`
  matches `Chuan-Feng Li`, and `Zi-Feng Li` correctly does not.
- **Slack's 50-block limit is respected.** A busy day could previously build a
  payload Slack rejects outright; `chunk_blocks` now splits it across messages.
- **Truncation is visible.** If the API response is capped and its oldest entry
  is still inside the window, you get a warning instead of a silently short
  digest. Papers dropped by the per-section caps are counted in the footer.
- **Retries and a User-Agent.** The arXiv API intermittently returns an empty
  but well-formed feed; the script retries with backoff rather than exiting 1.
- **Cross-lists are labelled** with their primary category.
- **`--dry-run`** prints the payload; **`--from-file`** parses a saved API
  response, so you can iterate on filters without hitting the network.

## Two filter notes worth a look

Both are judgement calls in your original config, not bugs — flagging them
because they showed up in testing:

- **`feedforward` in the Synthetic dimensions theme is broad.** In the sample
  render it pulled in *"Fast Nondestructive Readout for High-Clock-Rate Atom
  Array Quantum Processor"* — a neutral-atom hardware paper with no synthetic
  dimension in it. Mid-circuit feedforward is common phrasing in hardware
  papers.
- **`learning` in the Quantum learning theme is very broad**, and the excludes
  (`quantum machine learning`, `qml`, `variational quantum`) only catch some of
  the overflow. Expect general ML-flavoured papers in that bucket.
- Minor: the Squeezed light includes have `squeezing` but not `squeezed` on its
  own, so *"arbitrarily squeezed thermal noise"* only matched via `quadrature`.
  Adding `squeezed` would widen it.

## Running locally

```bash
pip install -r requirements.txt
python test_digest.py                              # matcher + parser checks
python digest.py --dry-run --from-file feed.xml    # render without posting
SLACK_WEBHOOK_URL=https://hooks.slack.com/... python digest.py
```

## Tunables

All read from the environment, with the defaults in `config.py`:
`ARXIV_MAX_RESULTS` (800), `MAX_PAPERS_PER_THEME` (8),
`MAX_PAPERS_AUTHOR_WATCH` (15), `MAX_PAPERS_PER_THEME_REPLACEMENTS` (5),
`INCLUDE_REPLACEMENTS` (on).

Themes and the watched-author list live at the top of `digest.py`.
