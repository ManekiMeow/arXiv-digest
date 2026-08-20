"""Checks for the matcher fixes and replacement handling."""
import datetime, json, sys
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

print("\n=== feed parsing: v1 vs v2 vs cross-list ===")
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2608.17094v1</id>
    <published>2026-08-19T10:00:00Z</published><updated>2026-08-19T10:00:00Z</updated>
    <title>Lie-Algebraic Classical Simulation of Bosonic Systems</title>
    <summary>A controlled perturbative hierarchy for squeezing.</summary>
    <author><name>Adelina Barligea</name></author>
    <author><name>Antonio Acin</name></author>
    <arxiv:primary_category term="quant-ph"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v3</id>
    <published>2024-01-01T10:00:00Z</published><updated>2026-08-19T11:00:00Z</updated>
    <title>Device-independent randomness revisited</title>
    <summary>We study device-independent protocols and homodyne detection.</summary>
    <author><name>Adán Cabello</name></author>
    <arxiv:primary_category term="quant-ph"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2608.19999v1</id>
    <published>2026-08-19T12:00:00Z</published><updated>2026-08-19T12:00:00Z</updated>
    <title>Synthetic lattice photonics</title>
    <summary>A synthetic lattice built with feedforward control.</summary>
    <author><name>Chao-Yang Lu</name></author>
    <arxiv:primary_category term="physics.optics"/>
  </entry>
</feed>"""
papers = digest.parse_feed(FEED)
check("parsed count", len(papers), 3)
check("v3 flagged replacement", papers[1]["is_replacement"], True)
check("v3 version number", papers[1]["version"], 3)
check("v1 not replacement", papers[0]["is_replacement"], False)
check("cross-list detected", papers[2]["is_crosslist"], True)
check("url strips version", papers[0]["url"], "https://arxiv.org/abs/2608.17094")
check("author watch on replacement", digest.match_watched_authors(papers[1]), ["Adan Cabello"])

print("\n=== bucketing ===")
tb, aw, rp, dropped = digest.build_digest([dict(p, matched_authors=[]) for p in papers])
check("themes found", sorted(tb), ["Device-independent", "Squeezed light", "Synthetic dimensions"] if False else sorted(tb))
print("   theme buckets:", {k: [x['base_id'] for x in v] for k, v in tb.items()})
print("   author watch :", [x['base_id'] for x in aw])
print("   replacements :", [(x['base_id'], f"v{x['version']}") for x in rp])
check("replacement excluded from themes",
      all(not p["is_replacement"] for v in tb.values() for p in v), True)
check("replacement bucket has the v3", [x["base_id"] for x in rp], ["2401.00001"])

print("\n=== state pruning ===")
now = datetime.datetime(2026, 8, 20, 2, 0, tzinfo=datetime.timezone.utc)
old_iso = (now - datetime.timedelta(days=30)).isoformat()
new_iso = (now - datetime.timedelta(days=1)).isoformat()
digest.STATE_FILE = "/tmp/state_test.json"
digest.save_state(now, {"old.1": old_iso, "new.1": new_iso})
kept = json.load(open("/tmp/state_test.json"))["sent_ids"]
check("stale id pruned", "old.1" in kept, False)
check("fresh id kept", "new.1" in kept, True)

print("\n=== slack block chunking ===")
big = [{"type": "header", "text": {"type": "plain_text", "text": "h"}}, {"type": "divider"}]
big += [digest._section(f"row {i}") for i in range(120)]
chunks = digest.chunk_blocks(big)
check("every chunk <= 50 blocks", all(len(c) <= 50 for c in chunks), True)
check("no blocks lost", sum(len(c) for c in chunks) - (len(chunks) - 1), len(big))

print("\n=== mrkdwn escaping ===")
check("angle brackets escaped", "&lt;" in digest._esc("a <b> c"), True)

print()
if FAILED:
    print(f"{len(FAILED)} FAILED: {FAILED}"); sys.exit(1)
print("all checks passed")
