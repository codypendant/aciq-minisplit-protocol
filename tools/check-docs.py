#!/usr/bin/env python3
"""Documentation drift checks for this repo. Standard library only.

    python3 tools/check-docs.py        # from the repo root

Why this exists: every time a claim in this project was disproved, the field
map got corrected and the prose around it did not. A cleanup pass on
2026-08-11 found the frame table still calling the checksum "Unsolved", the
Quick start recommending the exact debugging dead end that cost an evening,
the entity table listing 14 sensors when the config published over 30, and the
roadmap asking for work that was already finished.

None of that needed judgement to catch. It needed a script.

Exit code is non-zero if anything fails, so this can gate a commit.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["README.md", "PROTOCOL.md", "METHOD.md", "CHANGELOG.md", "CLAUDE.md",
        "tools/README.md"]
CONFIG = "esphome/aciq-k18w.yaml"

# Claims that were retracted. If one reappears as a live assertion, it is
# almost certainly prose that was never updated. Add to this list whenever
# something is disproved -- that is the point.
#
# `allow` lists files permitted to contain the phrase because they discuss the
# retraction itself (changelogs, "mistakes" sections, this list).
RETRACTED = [
    (r"\*\*Unsolved\*\*",
     "the check field is CRC-16/XMODEM and solved", []),
    # The climate entity shipped 2026-08-15. This is the "roadmap asking for
    # work already finished" failure the repo was swept for once before, so it
    # is pinned here rather than trusted to stay fixed. CHANGELOG may say it,
    # because that is where superseded statements are supposed to live.
    (r"climate`? entity\.?\*{0,2}\s*Deliberately not built yet|Deliberately not built yet",
     "the climate entity is built, shipping in esphome/components/aciq_k18w",
     ["CHANGELOG.md"]),
    (r"blower RPM `0x5C`|`0x5C`[^\n]{0,25}blower",
     "0x5C is the indoor coil thermistor",
     ["CHANGELOG.md", "CLAUDE.md", "METHOD.md", "PROTOCOL.md"]),
    (r"almost always the shifter rails",
     "the deaf tap was per-frame INFO logging, not the shifter",
     ["README.md", "METHOD.md", "CHANGELOG.md"]),
    (r"Map Sleep\b",
     "Sleep is 0x22 with four named values", []),
    # Deliberately tight: the CORRECT table puts both ids on one row
    # ("| `0x11` **vertical** | | `0x0E` **horizontal** |"), so a wide window
    # matches valid text. Only the adjacent wrong pairing should trip this.
    (r"`0x0E`[^\n]{0,15}\bvertical\b|`0x11`[^\n]{0,15}\bhorizontal\b",
     "the louver axes are 0x11 vertical / 0x0E horizontal",
     ["CHANGELOG.md", "METHOD.md"]),
    (r"static table",
     "the 0x39 capability list changes at runtime",
     ["CHANGELOG.md", "PROTOCOL.md"]),
    (r"0x64[^\n]{0,60}not a function",
     "0x64 does track compressor speed; it is just slow to update", []),
    # Retired 2026-08-13, when the dongle came out and a setpoint command was
    # proven on hardware. Listen-only is still SUPPORTED and still documented --
    # what is retracted is the claim that it is the only possible endpoint, and
    # any blanket statement that GPIO17 is unwired. The takeover config drives
    # it. CHANGELOG keeps the history, and the config comments must be free to
    # explain the hazard.
    (r"listen-only is the final design|deliberately not wired|"
     r"GPIO17 goes nowhere",
     "the takeover is built and proven; listen-only is one of two configurations",
     ["CHANGELOG.md"]),
    # The relative-command bug. Absolute controls exist now; nothing should
    # tell a reader to reach for the stepping buttons first.
    (r"never transmits|without transmitting a single byte",
     "the node transmits in the takeover configuration",
     ["CHANGELOG.md", "METHOD.md"]),
]

fails = []


def fail(msg):
    fails.append(msg)


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
        return fh.read()


def slug(heading):
    """GitHub's anchor rule: strip punctuation, lowercase, spaces -> hyphens.
    Note it does NOT collapse runs of spaces, so 'a — b' yields 'a--b'."""
    h = re.sub(r"[`*~]", "", heading).lower()
    h = re.sub(r"[^\w\s-]", "", h)
    return re.sub(r"\s", "-", h.strip())


def anchors(path):
    return {slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", read(path), re.M)}


def check_links():
    for doc in DOCS:
        body = read(doc)
        base = os.path.dirname(doc)
        for target, frag in re.findall(r"\]\(([^)#]*)#([^)]+)\)", body):
            dest = os.path.join(base, target) if target else doc
            if not os.path.exists(os.path.join(ROOT, dest)):
                fail(f"{doc}: link to missing file {dest}")
            elif frag not in anchors(dest):
                fail(f"{doc}: dead anchor {dest}#{frag}")
        for link in re.findall(r"\]\((?!#)(?!https?:)([^)#]+)\)", body):
            dest = os.path.join(base, link.rstrip("/"))
            if not os.path.exists(os.path.join(ROOT, dest)):
                fail(f"{doc}: link to missing path {link}")


def check_layout():
    """Every path in README's layout block must exist, and vice versa."""
    body = read("README.md")
    m = re.search(r"^## Repository layout\s*\n+```\n(.*?)```", body, re.M | re.S)
    if not m:
        return fail("README.md: no Repository layout block found")
    listed = set()
    for line in m.group(1).splitlines():
        tok = line.split()
        if tok and re.match(r"^[\w./-]+$", tok[0]):
            listed.add(tok[0])
            if not os.path.exists(os.path.join(ROOT, tok[0])):
                fail(f"README.md layout: {tok[0]} does not exist")
    actual = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", ".esphome")]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
            if not rel.startswith("."):
                actual.add(rel)
    for missing in sorted(actual - listed):
        fail(f"README.md layout: {missing} exists but is not listed")


def check_retracted():
    for pattern, why, allow in RETRACTED:
        for doc in DOCS:
            if doc in allow:
                continue
            if re.search(pattern, read(doc), re.I):
                fail(f"{doc}: retracted claim resurfaced ({why})")


def check_entities():
    """Every entity the config publishes should be findable in README's table.

    This is the check that would have caught the biggest drift: the table
    listed 14 entities while the config published more than 30."""
    cfg = read(CONFIG)
    names = set(re.findall(r'^\s*name:\s*"([^"]+)"', cfg, re.M))
    table = read("README.md")
    sec = re.search(r"^## What it gives you(.*?)^## ", table, re.M | re.S)
    if not sec:
        return fail("README.md: no 'What it gives you' section")
    listed = sec.group(1).lower()
    words = set(re.findall(r"[a-z0-9]+", listed))

    def covered(entity):
        # Rows are combined ("Frames Decoded / Rejected / CRC Failures") and
        # some entities are diagnostic twins of a named one, so exact
        # substring matching produces noise. Require every significant word.
        name = re.sub(r"\(raw\)", "", entity).lower()
        return all(w in words for w in re.findall(r"[a-z0-9]+", name))

    # The restart button is a control, not telemetry; it is not table material.
    exempt = {"Restart"}
    missing = sorted(n for n in names if n not in exempt and not covered(n))
    if missing:
        fail("README.md entity table is missing: " + ", ".join(missing))


def check_reference_frames():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import crc
    except ImportError:
        return fail("tools/crc.py will not import")
    path = os.path.join(ROOT, "captures", "reference-frames.txt")
    if not os.path.exists(path):
        return
    n = 0
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            body = line.split("#")[0].strip()
            m = re.match(r"^(?:AC|MOD)\s+((?:[0-9A-Fa-f]{2}\s+)+[0-9A-Fa-f]{2})$",
                         body)
            if not m:
                continue
            n += 1
            frame = bytes(int(x, 16) for x in m.group(1).split())
            if not crc.verify(frame):
                fail(f"captures/reference-frames.txt:{lineno}: CRC fails")
    if n == 0:
        fail("captures/reference-frames.txt: no frames parsed")


def check_secrets():
    """The published config must never carry a literal credential. A plain
    `cp` of the live config silently replaces !secret with the real value."""
    cfg = read(CONFIG)
    for lineno, line in enumerate(cfg.splitlines(), 1):
        if re.match(r"\s*(password|ssid):\s*[\"']", line) and "!secret" not in line:
            if "${" in line:            # a substitution, not a credential
                continue
            fail(f"{CONFIG}:{lineno}: literal credential -- use !secret")


for check in (check_links, check_layout, check_retracted, check_entities,
              check_reference_frames, check_secrets):
    check()

if fails:
    print(f"FAIL ({len(fails)})")
    for f in fails:
        print(f"  - {f}")
    sys.exit(1)
print("OK -- links, layout, retracted claims, entity table, "
      "reference frames, credentials")
