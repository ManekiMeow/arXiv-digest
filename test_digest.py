"""Checks for the matcher fixes and replacement handling."""
import datetime, json, sys
import config
import digest

FAILED = []

def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILED.append(label)

print("=== author matcher ===")
M = digest._author_name_matches
# real author strings taken from today's quant-ph listing
check("Chao-Yang Lu exact",            M("Chao-Yang Lu", "Chao-Yang", "Lu"), True)
check("C.-F. Li initials",             M("C.-F. Li", "Chuan-Feng", "Li"), True)
check("Zi-Feng Li != Chuan-Feng Li",   M("Zi-Feng Li", "Chuan-Feng", "Li"), False)
check("accent: Adan Cabello",          M("Adán Cabello", "Adan", "Cabello"), True)
check("A. I. Lvovsky",                 M("A. I. Lvovsky", "A.I.", "Lvovsky"), True)
check("Alexander Lvovsky vs A.I.",     M("Alexander Lvovsky", "A.I.", "Lvovsky"), True)
check("middle name: Jonatan B. Brask", M("Jonatan Bohr Brask", "Jonatan", "Brask"), True)
check("hyphen family Neergaard",       M("Jonas S. Neergaard-Nielsen", "Jonas", "Neergaard-Nielsen"), True)
check("Jiaqi Jiang != Liang Jiang",    M("Jiaqi Jiang", "Liang", "Jiang"), False)
check("Yuhao Meng != Yu Meng",         M("Yuhao Meng", "Yu", "Meng"), False)
check("Yu Meng exact",                 M("Yu Meng", "Yu", "Meng"), True)
check("family-only is not a match",    M("Meng", "Yu", "Meng"), False)

print("\n=== old substring matcher, same inputs ===")
def old(pa, given, family):
    import re as _re
    pa = pa.lower()
    if family.lower() not in pa: return False
    g = given.lower()
    if _re.match(r"^[a-z]\.", g): return len(pa) > 0 and pa[0] == g[0]
    return g in pa
for lbl, args, want in [("Yuhao Meng", ("Yuhao Meng","Yu","Meng"), False),
                        ("Adan Cabello accent", ("Adán Cabello","Adan","Cabello"), True)]:
    got = old(*args)
    print(f"{'(old ok)  ' if got==want else '(old BUG) '} {lbl}: old={got} new={M(*args)} correct={want}")

print("\n=== theme scorer on real abstracts ===")
p1 = {"title": "Lie-Algebraic Classical Simulation of Bosonic Systems Beyond Gaussian Dynamics",
      "abstract": "We further derive a controlled perturbative hierarchy for squeezing beyond exact sector confinement and confirm the predicted error orders numerically."}
p2 = {"title": "Gaussian Optimality of Energy-Constrained One-Shot Communication through Single-Mode Bosonic Gaussian Channels",
      "abstract": "We prove Gaussian optimality ... for a channel that modulates only one quadrature of the field."}
check("2608.17094 -> Squeezed light", "Squeezed light" in digest.score_paper(p1), True)
check("2608.17239 -> Squeezed light", "Squeezed light" in digest.score_paper(p2), True)

print("\n=== OAI-PMH record parsing ===")
import os
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()

# Final page of a harvest: three live records, one deleted record, no token.
RECORDS = fixture("oai_listrecords.xml")
# First page of a harvest: one record plus a resumptionToken.
PAGE1 = fixture("oai_listrecords_page1.xml")

papers, token = digest.parse_oai_response(RECORDS)
check("live records parsed",            len(papers), 3)
check("deleted record skipped",         [p["base_id"] for p in papers],
      ["2608.17094", "2401.00001", "2608.19999"])
check("no token on the last page",      token, None)

new, repl, cross = papers

check("id carries the version",         new["id"], "2608.17094v1")
check("base_id is unversioned",         new["base_id"], "2608.17094")
check("version number",                 new["version"], 1)
check("title newlines collapsed",       new["title"],
      "Lie-Algebraic Classical Simulation of Bosonic Systems Beyond Gaussian Dynamics")
check("abstract normalised + entities", new["abstract"],
      "We derive a controlled perturbative hierarchy for squeezing beyond exact sector "
      "confinement, valid for < 10 modes, and confirm the predicted error orders & "
      "scalings numerically.")
check("authors split on ', ' / ' and '", new["authors"],
      ["Adelina Barligea", "Antonio Acin", "Mikhail Lukin"])
check("submitted keeps seconds",        new["submitted"].isoformat(), "2026-08-19T09:41:03+00:00")
check("updated == submitted for a v1",  new["updated"], new["submitted"])
check("single version is not a replacement", new["is_replacement"], False)
check("primary category",               new["primary_category"], "quant-ph")
check("quant-ph primary is no cross-list", new["is_crosslist"], False)
check("url drops the version",          new["url"], "https://arxiv.org/abs/2608.17094")

print("\n=== new vs replacement comes from the version count ===")
check("v3 id",                          repl["id"], "2401.00001v3")
check("v3 version number",              repl["version"], 3)
check("v3 is a replacement",            repl["is_replacement"], True)
check("submitted is v1's date",         repl["submitted"].isoformat(), "2024-01-01T10:12:45+00:00")
check("updated is the newest version's date", repl["updated"].isoformat(),
      "2026-08-19T11:27:18+00:00")
# created != updated on essentially every record, brand-new ones included, so
# only the version count can tell a replacement from a first announcement.
check("v1 date != v3 date but v1 stays new",
      (new["submitted"] != new["updated"], new["is_replacement"]), (False, False))

print("\n=== categories and authors ===")
check("categories split on whitespace", cross["categories"],
      ["physics.optics", "quant-ph", "cond-mat.mes-hall"])
check("primary is the first category",  cross["primary_category"], "physics.optics")
check("cross-list detected",            cross["is_crosslist"], True)
check("mononym author kept",            cross["authors"],
      ["Chatterjee", "Chao-Yang Lu", "Yu Meng"])
check("affiliation legend dropped",     any("USTC" in a for a in cross["authors"]), False)

# The flat authors string is the one real regression risk of arXivRaw: the watch
# list matches on "Given Family", so the split has to reproduce that shape.
check("watch matches a split name",     digest.match_watched_authors(cross),
      ["Chao-Yang Lu", "Yu Meng"])
check("watch matches an accented name", digest.match_watched_authors(repl),
      ["Adan Cabello", "Renato Renner"])
check("accent survives parsing",        "Adán Cabello" in repl["authors"], True)

PA = digest.parse_authors
check("comma-separated list",           PA("A. Einstein, B. Podolsky, N. Rosen"),
      ["A. Einstein", "B. Podolsky", "N. Rosen"])
check("trailing ' and '",               PA("Sakil Khan, Dipankar Home and Sachin Jain"),
      ["Sakil Khan", "Dipankar Home", "Sachin Jain"])
check("affiliation markers dropped",    PA("J. Doe (1), R. Roe (2) ((1) MIT, (2) Caltech)"),
      ["J. Doe", "R. Roe"])
check("comma inside parens is no split", PA("Xiang Cheng (Inst A, Inst B)"), ["Xiang Cheng"])
check("'and' inside a name is kept",    PA("Anders Sandberg and Nicole Yunger Halpern"),
      ["Anders Sandberg", "Nicole Yunger Halpern"])
check("empty authors string",           PA(""), [])

print("\n=== LaTeX decoding (arXivRaw serves TeX, the Atom feed served Unicode) ===")
D = digest._decode_latex
# Every string below is verbatim output from a live dry run against arXivRaw.
check("umlaut + dotless i + cedilla",
      D(r'\"Ozlem Erk{\i}l{\i}\c{c}, Aritra Das, S. Nibedita Swain'),
      "Özlem Erkılıç, Aritra Das, S. Nibedita Swain")
check("umlaut + dotless i + breve",
      D(r'Asghar Ullah, \"Ozg\"ur E. M\"ustecapl{\i}o\u{g}lu'),
      "Asghar Ullah, Özgür E. Müstecaplıoğlu")
check("umlaut mid-word",
      D(r'Andre Youssefi, Erc\"ument Kaya, Minh Chung'),
      "Andre Youssefi, Ercüment Kaya, Minh Chung")
check("acute on a hyphenated family name",
      D(r"Asghar Ullah, Giovanni Scala, Luis L. S\'anchez-Soto"),
      "Asghar Ullah, Giovanni Scala, Luis L. Sánchez-Soto")
check("umlaut, three-name list",
      D(r'Alejandro R. Ramos Ramos, Maximilian Fr\"ohlich, Aaron Sander'),
      "Alejandro R. Ramos Ramos, Maximilian Fröhlich, Aaron Sander")
check("acute at the end of a name",
      D(r"Matija Medvidovi\'c, Angel Rubio, Juan Carrasquilla"),
      "Matija Medvidović, Angel Rubio, Juan Carrasquilla")
check("umlaut before a hyphen",
      D(r'Guillem M\"uller-Rigat, Albert Aloy, Maciej Lewenstein'),
      "Guillem Müller-Rigat, Albert Aloy, Maciej Lewenstein")
check("title: accent decoded, math left alone",
      D(r"Bridge of $\Psi$'s: Quantum Circuit Optimization with Schr\"odinger Bridges"),
      "Bridge of $\\Psi$'s: Quantum Circuit Optimization with Schrödinger Bridges")

# Accents arrive braced and unbraced and brace-wrapped, all three interchangeably.
check("braced, unbraced, wrapped",      D(r'\"o \"{o} {\"o}'), "ö ö ö")
check("dotless i, all three forms",     D(r'{\i} \i{} \i '), "ı ı ı")
check("standalone letters",             D(r'\l{} \L{} \o{} \O{} \aa{} \AA{} \ae{} \AE{} \ss{}'),
      "ł Ł ø Ø å Å æ Æ ß")
check("a space terminates the macro",   D(r'S\o ren M{\o}ller'), "Søren Møller")
check("the full accent table",
      D(r'\c{c} \u{g} \v{s} \.z \=a \H{o} \r{a} \k{a} \~n \`a \^o'),
      "ç ğ š ż ā ő å ą ñ à ô")
check("stray braces around plain words", D(r'{Bell} inequalit{y}'), "Bell inequality")
check("precomposed NFC, not combining", [hex(ord(c)) for c in D(r'M\"uller')],
      ["0x4d", "0xfc", "0x6c", "0x6c", "0x65", "0x72"])

# Real math must survive: the decoder runs in math_mode="verbatim", so anything
# between $...$ is passed through byte for byte rather than half-rendered.
check("inline math untouched",          D(r'We use $\alpha$ and $\mathcal{O}(n \log n)$ here'),
      "We use $\\alpha$ and $\\mathcal{O}(n \\log n)$ here")
check("math outside $...$ untouched",   D(r'O(n^2) and T_c with \"o'), "O(n^2) and T_c with ö")
check("bare % is data, not a comment",  D(r'95% fidelity for Fr\"ohlich'),
      "95% fidelity for Fröhlich")
check("bare & is not a table separator", D(r'Alice & Bob, Schr\"odinger'),
      "Alice & Bob, Schrödinger")
check("escaped metacharacters",         D(r'100\% \& \#1 with M\"uller'), "100% & #1 with Müller")

# Decoding text that is already Unicode must change nothing, or a second pass
# anywhere in the pipeline would corrupt it.
CLEAN = "Özlem Erkılıç, Schrödinger, $\\alpha$, 95% of runs, Alice & Bob"
check("clean Unicode is a no-op",       D(CLEAN), CLEAN)
check("decoding is idempotent",
      all(D(D(s)) == D(s) for s in [
          r'\"Ozlem Erk{\i}l{\i}\c{c}',
          r"Luis L. S\'anchez-Soto",
          r"Bridge of $\Psi$'s with Schr\"odinger Bridges",
          r'95% and \& and $\mathcal{O}(n^2)$',
      ]), True)

print("\n=== the matcher only sees decoded names ===")
# This is the correctness bug, not a formatting one: _fold() strips diacritics,
# so an unaccented watch-list entry matches "Sánchez-Soto" - but a literal
# backslash-quote-a is not a diacritic, and the match failed silently.
check("undecoded escape does NOT match (the bug)",
      M(r"Luis L. S\'anchez-Soto", "Luis", "Sanchez-Soto"), False)
check("decoded name matches an unaccented watch entry",
      M(D(r"Luis L. S\'anchez-Soto"), "Luis", "Sanchez-Soto"), True)
check("parse_authors feeds the matcher decoded names",
      [a for a in PA(r"Asghar Ullah, Giovanni Scala, Luis L. S\'anchez-Soto")
       if M(a, "Luis", "Sanchez-Soto")],
      ["Luis L. Sánchez-Soto"])
check("umlaut and breve fold away",
      M(D(r'\"Ozg\"ur E. M\"ustecaplo\u{g}lu'), "Ozgur", "Mustecaploglu"), True)
# Dotless i is a letter in its own right, not an accented i: NFKD leaves U+0131
# alone, so _fold() cannot reduce it to "i". A watch entry for this name has to
# be spelled with the dotless letter. Pre-existing _fold() behaviour, asserted
# here so it stays a known limit rather than a surprise.
check("dotless i does not fold to i",
      M(D(r'\"Ozg\"ur E. M\"ustecapl{\i}o\u{g}lu'), "Ozgur", "Mustecaplioglu"), False)
check("dotless i matches a dotless watch entry",
      M(D(r'\"Ozg\"ur E. M\"ustecapl{\i}o\u{g}lu'), "Ozgur", "Müstecaplıoğlu"), True)

print("\n=== authors are decoded before the split ===")
check("brace groups do not confuse the splitter",
      PA(r'\"Ozlem Erk{\i}l{\i}\c{c}, Aritra Das, S. Nibedita Swain'),
      ["Özlem Erkılıç", "Aritra Das", "S. Nibedita Swain"])
check("' and ' still splits after decoding",
      PA(r'Maximilian Fr\"ohlich and Matija Medvidovi\'c'),
      ["Maximilian Fröhlich", "Matija Medvidović"])
check("affiliations still stripped after decoding",
      PA(r'M\"uller (1), S\'anchez-Soto (2) ((1) FUB, (2) UCM)'),
      ["Müller", "Sánchez-Soto"])

print("\n=== LaTeX-laden records end to end ===")
LATEX_RECORDS = fixture("oai_listrecords_latex.xml")
tex_papers, tex_token = digest.parse_oai_response(LATEX_RECORDS)
tex, plain = tex_papers
check("title decoded, math preserved",  tex["title"],
      "Bridge of $\\Psi$'s: Quantum Circuit Optimization with Schrödinger Bridges")
check("authors decoded",                tex["authors"],
      ["Asghar Ullah", "Giovanni Scala", "Luis L. Sánchez-Soto"])
check("abstract keeps its formulae",    tex["abstract"],
      "We optimise the quadrature squeezing of $|\\psi\\rangle$ with a cost that "
      "scales as $\\mathcal{O}(n^2)$, reaching 95% fidelity for N < 10 modes.")
check("decoded abstract still scores",  digest.score_paper(tex), ["Squeezed light"])
check("already-Unicode record untouched", plain["authors"],
      ["Matija Medvidović", "Ángel Rubio", "Juan Carrasquilla"])
check("already-Unicode title untouched", plain["title"], "Contextuality without diacritics")

print("\n=== namespace handling ===")
# The envelope and the metadata sit in two different namespaces; a lookup that
# ignored either would still find the tags by local name.
WRONG_META_NS = RECORDS.replace("http://arxiv.org/OAI/arXivRaw/", "http://arxiv.org/OAI/arXiv/")
check("metadata namespace is enforced", digest.parse_oai_response(WRONG_META_NS), ([], None))
NO_ENVELOPE_NS = RECORDS.replace(' xmlns="http://www.openarchives.org/OAI/2.0/"', "", 1)
check("envelope namespace is enforced", digest.parse_oai_response(NO_ENVELOPE_NS), ([], None))

print("\n=== OAI-PMH errors ===")
def _envelope(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            '<responseDate>2026-08-20T03:07:11Z</responseDate>'
            '<request verb="ListRecords">https://oaipmh.arxiv.org/oai</request>'
            f'{body}</OAI-PMH>')

NO_RECORDS = _envelope('<error code="noRecordsMatch">no matching records</error>')
check("noRecordsMatch is empty, not an error",
      digest.parse_oai_response(NO_RECORDS), ([], None))
BAD_ARGUMENT = _envelope('<error code="badArgument">unknown set</error>')
check("other error codes also parse empty",
      digest.parse_oai_response(BAD_ARGUMENT), ([], None))
check("malformed XML parses empty",     digest.parse_oai_response("<OAI-PMH"), ([], None))

print("\n=== bucketing ===")
tb, aw, rp = digest.build_digest([dict(p) for p in papers])
print("   theme buckets:", {k: [x['base_id'] for x in v] for k, v in tb.items()})
print("   author watch :", [x['base_id'] for x in aw])
print("   replacements :", [x['id'] for x in rp])
check("replacement excluded from themes",
      all(not p["is_replacement"] for v in tb.values() for p in v), True)
check("replacement bucket has the v3",  [x["id"] for x in rp], ["2401.00001v3"])
check("author watch picks up the cross-list", [x["base_id"] for x in aw], ["2608.19999"])

print("\n=== state pruning ===")
now = datetime.datetime(2026, 8, 20, 2, 0, tzinfo=datetime.timezone.utc)
old_iso = (now - datetime.timedelta(days=30)).isoformat()
new_iso = (now - datetime.timedelta(days=1)).isoformat()
digest.STATE_FILE = "/tmp/state_test.json"
digest.save_state(now, {"old.1v1": old_iso, "new.1v1": new_iso})
kept = json.load(open("/tmp/state_test.json"))["sent_ids"]
check("stale id pruned", "old.1v1" in kept, False)
check("fresh id kept", "new.1v1" in kept, True)
# The harvest window reaches at most 7 days back, so the retained ids must
# outlive it or a day-granular re-harvest could repost a paper.
check("state outlives the widest window", digest.STATE_MAX_AGE_DAYS > 7, True)

print("\n=== missed run detection ===")
def at(y, m, d, h=2, mi=17):
    return datetime.datetime(y, m, d, h, mi, tzinfo=datetime.timezone.utc)
MW = digest.missed_weekdays
# 2026-08-24 is a Monday, 2026-08-28 a Friday.
check("consecutive weekdays",     MW(at(2026, 8, 25), at(2026, 8, 26)), 0)
check("Fri -> Mon is not a gap",  MW(at(2026, 8, 21), at(2026, 8, 24)), 0)
check("Fri -> Tue misses Monday", MW(at(2026, 8, 21), at(2026, 8, 25)), 1)
# The outage that stopped this digest: last delivery Wed 26th, next run Fri 28th.
check("Wed -> Fri misses Thu",    MW(at(2026, 8, 26), at(2026, 8, 28)), 1)
check("Mon -> Mon misses Tue-Fri", MW(at(2026, 8, 17), at(2026, 8, 24)), 4)

print("\n=== window filtering is still the real gate ===")
# `from` is day-granular, so the harvest legitimately returns records from
# before the cutoff (metadata-only edits keep their old version date).
cutoff = datetime.datetime(2026, 8, 19, 3, 7, tzinfo=datetime.timezone.utc)
check("older version date filtered out",
      [p["id"] for p in digest.filter_papers(papers, cutoff)],
      ["2608.17094v1", "2401.00001v3", "2608.19999v1"])
check("a stale re-announcement is dropped",
      digest.filter_papers(papers, datetime.datetime(2026, 8, 19, 11, 30,
                                                     tzinfo=datetime.timezone.utc)),
      [papers[2]])
check("already-sent versioned ids dedup",
      [p["id"] for p in papers if p["id"] not in {"2608.17094v1"}],
      ["2401.00001v3", "2608.19999v1"])

print("\n=== slack block chunking ===")
big = [{"type": "header", "text": {"type": "plain_text", "text": "h"}}, {"type": "divider"}]
big += [digest._section(f"row {i}") for i in range(120)]
chunks = digest.chunk_blocks(big)
check("every chunk <= 50 blocks", all(len(c) <= 50 for c in chunks), True)
check("no blocks lost", sum(len(c) for c in chunks) - (len(chunks) - 1), len(big))

print("\n=== mrkdwn escaping ===")
check("angle brackets escaped", "&lt;" in digest._esc("a <b> c"), True)

print("\n=== fetch_papers over OAI-PMH ===")
import logging, requests
from unittest import mock

FROM = datetime.date(2026, 8, 19)

def _response(status, body, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode()
    r.url = config.ARXIV_OAI_URL
    r.headers.update(headers or {})
    return r

class _FakeSession:
    """Stand-in for requests.Session that replays queued responses."""
    def __init__(self, *responses):
        self._responses = responses
        self.requests = []
        self.headers = {}
    def get(self, url, **kwargs):
        self.requests.append((url, kwargs.get("params")))
        item = self._responses[min(len(self.requests), len(self._responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item
    @property
    def calls(self):
        return len(self.requests)
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False

class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []
    def emit(self, record):
        self.messages.append(record.getMessage())

def _run_fetch(*responses, from_date=FROM):
    """Call fetch_papers() against canned responses; no network, no waiting."""
    session = _FakeSession(*responses)
    capture = _LogCapture()
    digest.logger.addHandler(capture)
    slept = []
    try:
        with mock.patch.object(digest.requests, "Session", return_value=session), \
             mock.patch.object(digest.time, "sleep", slept.append):
            papers = digest.fetch_papers(from_date)
    finally:
        digest.logger.removeHandler(capture)
    return papers, session, slept, "\n".join(capture.messages)

# Happy path: one page, one request, exact query.
papers, session, slept, log = _run_fetch(_response(200, RECORDS))
check("single page parses",           len(papers), 3)
check("requested exactly once",       session.calls, 1)
check("never sleeps",                 slept, [])
check("query params", session.requests[0][1],
      {"verb": "ListRecords", "metadataPrefix": "arXivRaw",
       "set": config.ARXIV_OAI_SET, "from": "2026-08-19"})
check("no until param",               "until" in (session.requests[0][1] or {}), False)
check("endpoint",                     session.requests[0][0], config.ARXIV_OAI_URL)
check("sets User-Agent header",       session.headers.get("User-Agent"), config.USER_AGENT)
check("sets Accept header",           session.headers.get("Accept"),
      "application/xml,text/xml;q=0.9,*/*;q=0.8")

# Pagination: the token, and nothing else, goes back on the second request.
papers, session, slept, log = _run_fetch(_response(200, PAGE1), _response(200, RECORDS))
check("both pages collected",         [p["base_id"] for p in papers],
      ["2608.11111", "2608.17094", "2401.00001", "2608.19999"])
check("two requests",                 session.calls, 2)
check("page 2 sends the token alone", session.requests[1][1],
      {"verb": "ListRecords", "resumptionToken": "3721516|2501"})
check("3s between pages (arXiv ToU)", slept, [digest.OAI_PAGE_DELAY])

# Runaway token loop is capped, loudly.
with mock.patch.object(config, "ARXIV_OAI_MAX_PAGES", 2):
    papers, session, slept, log = _run_fetch(_response(200, PAGE1))
check("page cap enforced",            session.calls, 2)
check("page cap logged",              "harvest is incomplete" in log, True)

# noRecordsMatch: an empty window, not a failure - no retries.
papers, session, slept, log = _run_fetch(_response(200, NO_RECORDS))
check("noRecordsMatch returns empty", papers, [])
check("noRecordsMatch not retried",   session.calls, 1)
check("noRecordsMatch not slept on",  slept, [])

# 503 + Retry-After is OAI-PMH flow control, not an error.
papers, session, slept, log = _run_fetch(
    _response(503, "", {"Retry-After": "12"}), _response(200, RECORDS))
check("Retry-After honoured",         slept, [12])
check("flow control recovers",        len(papers), 3)
papers, session, slept, log = _run_fetch(_response(503, ""), _response(200, RECORDS))
check("503 without Retry-After",      slept, [5])
papers, session, slept, log = _run_fetch(
    _response(503, "", {"Retry-After": "99999"}), _response(200, RECORDS))
check("Retry-After capped",           slept, [digest.RETRY_AFTER_CAP])

# A genuine network error gets a few modest retries.
papers, session, slept, log = _run_fetch(
    requests.ConnectionError("connection reset"), _response(200, RECORDS))
check("network error retried",         len(papers), 3)
check("modest backoff",                slept, [5])

# 4xx is not transient: fail fast and say exactly what came back.
papers, session, slept, log = _run_fetch(_response(400, "badArgument: unknown set",
                                                   {"X-Edge": "fastly"}))
check("400 gives up",                 papers, [])
check("400 requested exactly once",   session.calls, 1)
check("400 never sleeps",             slept, [])
check("400 body logged",              "badArgument: unknown set" in log, True)
check("400 headers logged",           "X-Edge" in log, True)

# A failure mid-harvest discards the partial result rather than half-reporting.
papers, session, slept, log = _run_fetch(_response(200, PAGE1), _response(400, "gone"))
check("partial harvest discarded",    papers, [])
check("partial harvest logged",       "discarding 1 records" in log, True)

# Exhausted retries on a transient error.
papers, session, slept, log = _run_fetch(_response(500, "boom"))
check("500 retried to exhaustion",    session.calls, config.ARXIV_RETRIES)
check("500 returns empty",            papers, [])

print()
if FAILED:
    print(f"{len(FAILED)} FAILED: {FAILED}"); sys.exit(1)
print("all checks passed")
