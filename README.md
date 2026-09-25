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

- **Papers are harvested over OAI-PMH.** `export.arxiv.org/api/query` is
  answered with an empty-bodied HTTP 406 by arXiv's edge for every command-line
  client, so the digest reads `oaipmh.arxiv.org/oai` instead — arXiv's supported
  bulk interface. It takes the window as a `from=YYYY-MM-DD` date and pages with
  a `resumptionToken` rather than truncating at a fixed result count. The
  `arXivRaw` metadata format is the one that carries per-version dates at second
  resolution, so the window filter stays exact; `from` is only a coarse
  pre-filter and is deliberately widened by a day.
- **LaTeX escapes are decoded.** `arXivRaw` hands back the submitted TeX source
  where the Atom API handed back rendered Unicode, so names reached Slack as
  `Schr\"odinger` and `S\'anchez-Soto`. Titles, abstracts and authors are run
  through `pylatexenc` on the way in. This is not cosmetic: the author matcher
  below folds diacritics before comparing, and a backslash escape is not a
  diacritic, so accented watch-list names had stopped matching *silently*.
  Mathematics is decoded in `math_mode="verbatim"` — everything between `$...$`
  is passed through exactly as submitted, because a half-rendered formula reads
  worse than the TeX it came from. Bare `&`, `%` and `#`, which submitters leave
  unescaped in prose, are protected first; unguarded, TeX reads `&` as a table
  separator and `%` as a comment that swallows the rest of the line.
- **Replacements now appear.** A paper counts as a replacement when its highest
  `<version>` is above v1, and the window is applied to the newest version's
  date rather than v1's. As written before, a v2 could never surface: it has an
  old `published` date and was filtered out before it was ever scored. Replacements
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

  The accent case matters — the name reaches the matcher as `Adán Cabello`
  (`Ad\'an Cabello` before decoding), so that watch entry never fired. Initials still work in both directions: `C.-F. Li`
  matches `Chuan-Feng Li`, and `Zi-Feng Li` correctly does not.
- **Slack's 50-block limit is respected.** A busy day could previously build a
  payload Slack rejects outright; `chunk_blocks` now splits it across messages.
- **A partial harvest is never delivered.** If a later page of the harvest
  fails, the run exits without advancing `state.json`, so the next run covers
  the same window again instead of skipping what it never read.
- **Retries and a User-Agent.** OAI-PMH flow control (HTTP 503 +
  `Retry-After`) is honoured, genuine network errors get a few short retries,
  and anything else fails immediately with its status, headers and body logged.
- **Cross-lists are labelled** with their primary category.
- **`--dry-run`** prints the payload; **`--from-file`** parses a saved OAI-PMH
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
python digest.py --dry-run \
    --from-file fixtures/oai_listrecords.xml       # render without posting
SLACK_WEBHOOK_URL=https://hooks.slack.com/... python digest.py
```

## Tunables

All read from the environment, with the defaults in `config.py`:
`ARXIV_OAI_URL` (`https://oaipmh.arxiv.org/oai`), `ARXIV_OAI_SET`
(`physics:quant-ph`), `ARXIV_OAI_MAX_PAGES` (20), `INCLUDE_REPLACEMENTS` (on).

Themes and the watched-author list live at the top of `digest.py`.
