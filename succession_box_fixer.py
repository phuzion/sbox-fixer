#!/usr/bin/env python3
"""Fix succession-box template misuse on English Wikipedia.

Works through the subcategories of
[[Category:Succession box misuse tracking]] and rewrites the misused
cells into the dedicated templates that the tracking categories ask for:

=====================================  ===================================
Misuse                                 Replacement
=====================================  ===================================
after = Incumbent                      {{s-inc}}
after = Vacant / Post vacant           {{s-vac}}
after = Vacant, next held by [[X]]     {{s-vac|next=[[X]]}}
after = Unknown                        {{s-vac|unknown}}
after = Unknown, then [[X]]            {{s-vac|unknown|unknnext=[[X]]}}
after = Suspended                      {{s-vac|suspended}}
after = Sede vacante / See vacant      {{s-vac|sedevacante}}
after = Office abolished / dissolved   {{s-non|reason=Office abolished}}
        / Title extinct
before = New office / Office created   {{s-new|office}}
before = Newly created / Created       {{s-new}}
before = Position recreated            {{s-vac|recreated}}
before = Vacant, last held by [[X]]    {{s-vac|last=[[X]]}}
before = Unknown / Vacant              {{s-vac|unknown}} / {{s-vac}}
title = Foo<br />with Bar  (s-ttl)     title=Foo |with=Bar
=====================================  ===================================

``{{Succession box}}`` calls are split into ``{{s-bef}}``/``{{s-ttl}}``/
``{{s-aft}}`` (or their replacements) because it has no way to express
"incumbent", "vacant", etc.

The rules are deliberately conservative: a value is only rewritten when the
*whole* value matches a known pattern. Anything else (values that name a
real successor, carry references, templates, comments, footnotes, ...) is
left alone and written to the report file for manual review.

``{{s-vac}}`` and ``{{s-non}}`` do not emit table-row markup the way
``{{s-bef}}``/``{{s-aft}}`` do, so the bot adds a ``|-`` line next to them
when the neighbouring template would not already start/end the row.

Usage examples::

    # Preview everything, ask before each save (default behaviour)
    python succession_box_fixer.py

    # Report only: read every page, publish the report wikitable to
    # User:PhuzBot/Succession box report, edit no articles
    python succession_box_fixer.py -reportonly

    # Same, but save the report somewhere else
    python succession_box_fixer.py -reportonly -reportpage:"User:Example/Report"

    # Report only, nothing saved on the wiki at all (no login needed)
    python succession_box_fixer.py -reportonly -noreportpage

    # Specific pages / any pywikibot page generator
    python succession_box_fixer.py -page:"Some article" -always

    # Offline: run the fixer on a local wikitext file and print the diff
    python succession_box_fixer.py -testfile:sample.wiki

Options:

-only:<text>      Only process subcategories whose name contains <text>
                  (case-insensitive), e.g. -only:incumbent, -only:"'before'".
-reportonly      Never edit articles (no prompts): only read the pages and
                  build the report.
-reportpage:<t>   Wiki page the report is saved to as a wikitable (default
                  "User:PhuzBot/Succession box report"). Long sections go on
                  numbered subpages (<t>/Manual fixes/1, <t>/Bot fixes/1...).
                  It is only published when the run finishes; an interrupted
                  run saves it to succession_box_report.wiki instead.
-noreportpage     Don't publish the report; save its wikitext to
                  succession_box_report.wiki (no login needed with
                  -reportonly).
-report:<file>    Also write a local TSV with one row per misused value
                  (default name: succession_box_report.tsv).
-allowlinks       Also convert "abolished"/"dissolved"/"extinct" values that
                  contain wikilinks into {{s-non|reason=...}}.
-summary:<text>   Override the edit summary.
-always           Save without asking for confirmation.
-testfile:<file>  Offline mode: fix a local file and print a diff.

Standard pywikibot global options (-simulate, -lang, -family, -user,
-pt:<seconds> ...) and page generator options (-cat:, -page:, -file:,
-limit:, ...) also work. Without a generator option the pages of every
subcategory of the tracking category are processed.

Running this unattended on English Wikipedia requires an approved bot
request (WP:BRFA) and a bot account.
"""
from __future__ import annotations

import csv
import difflib
import itertools
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import mwparserfromhell as mwp
from mwparserfromhell.nodes import Comment, Template, Text

TRACKING_CAT = 'Succession box misuse tracking'

# ---------------------------------------------------------------------------
# Template names
# ---------------------------------------------------------------------------

# Canonical names we need to recognise (redirects are added at runtime).
# Succession-box header templates; each one starts with a "|-" row.
HEADERS = (
    's-reg', 's-off', 's-mil', 's-ppo', 's-gov', 's-dip', 's-aca',
    's-sports', 's-rel', 's-hon', 's-par', 's-hou', 's-pre', 's-other',
    's-media', 's-bus', 's-legal', 's-ach', 's-court', 's-culture',
    's-edu', 's-civ', 's-npo',
)

# Canonical names we need to recognise (redirects are added at runtime).
CANONICAL = (
    's-aft', 's-bef', 's-ttl', 'succession box',
    's-inc', 's-new', 's-vac', 's-non',
    's-start', 's-end', 's-break', 'end',
) + HEADERS

# Templates whose output ends with a "|-" row separator (or opens a table),
# so a following cell that does not start its own row is still fine.
ROW_ENDERS = {'s-aft', 's-inc', 's-break', 's-start', 'succession box'}

# Templates whose output starts a new row (or closes the table).
ROW_STARTERS = {
    's-bef', 's-new', 's-end', 'end', 's-break', 's-start', 'succession box',
} | set(HEADERS)


def norm_name(name: str) -> str:
    """Normalise a template name for lookup."""
    name = str(name)
    name = re.sub(r'<!--.*?-->', '', name, flags=re.S)
    name = name.replace('_', ' ').strip()
    name = re.sub(r'^(?:template|msg)\s*:\s*', '', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name)
    return name.lower()


# ---------------------------------------------------------------------------
# Tracking-category detection (mirrors the /check sub-templates)
# ---------------------------------------------------------------------------

AFTER_TRACKED = re.compile(
    r'[vV]acant|[iI]ncumbent|[aA]bolished|[sS]uspended|[dD]issolved'
    r'|[uU]nknown|[eE]xtinct')
BEFORE_TRACKED = re.compile(
    r'^\s*[nN][eE][wW]|[cC]reated|[vV]acant|[sS]uspended|[uU]nknown')
TITLE_WITH = re.compile(r'<br ?/?>\s*with\s')


def tracked_after(value: str) -> bool:
    return bool(value) and bool(AFTER_TRACKED.search(value))


def tracked_before(value: str) -> bool:
    return bool(value) and bool(BEFORE_TRACKED.search(value))


# ---------------------------------------------------------------------------
# Value classification
# ---------------------------------------------------------------------------

UNSAFE = re.compile(
    r'<!--|\{\{|\}\}|<ref|<sup|\{\||\[https?:|\[//|<math|<nowiki|<gallery',
    re.I)


def flatten(value: str) -> tuple[str, int] | None:
    """Strip presentational markup.

    Returns (single-line text with wikilinks kept, number of lines), or
    None when the value contains markup we do not want to touch.
    """
    if UNSAFE.search(value):
        return None
    t = re.sub(r"'{2,}", '', value)
    t = re.sub(r'</?(?:small|big|span|b|i|em|strong|center|div|font)\b[^>]*>',
               '', t, flags=re.I)
    t = re.sub(r'<br\s*/?\s*>', '\n', t, flags=re.I)
    t = t.replace('&nbsp;', ' ')
    if '<' in t or '>' in t:
        return None
    lines = [re.sub(r'\s+', ' ', ln).strip() for ln in t.split('\n')]
    lines = [ln for ln in lines if ln]
    return ' '.join(lines), len(lines)


def unlink(text: str) -> str:
    return re.sub(r'\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]', r'\1', text)


def core(text: str) -> str:
    """Lower-cased, unlinked text without wrapping brackets/punctuation."""
    t = unlink(text)
    t = re.sub(r'[←-↓]', '', t).strip()
    while True:
        old = t
        t = t.strip().rstrip('.,;:').strip()
        if len(t) >= 2 and ((t[0], t[-1]) in (('(', ')'), ('[', ']'))):
            t = t[1:-1]
        if t == old:
            break
    return re.sub(r'\s+', ' ', t).lower()


# Words that may precede "vacant"/"suspended".
_SEAT = r'post|position|office|seat|title|throne|chair|see|bishopric|stool'
VAC_ONLY = re.compile(
    rf'(?:(?:n/?a|none)\s*[,;:]?\s*)?\(?(?:(?:{_SEAT})\s+)?vacant'
    rf'(?:\s+(?:{_SEAT}))?\)?')
SEDE_ONLY = re.compile(r'\(?(?:sede\s+vacante|see\s+vacant)\)?')
UNK_ONLY = re.compile(
    r'\(?(?:(?:name|holder|successor|predecessor|incumbent)\s+)?unknown\)?')
SUSP_ONLY = re.compile(
    rf'\(?(?:(?:{_SEAT}|league|competition|tournament|championship|award'
    rf'|event|series)\s+)?(?:temporarily\s+)?suspended\)?')
INC_ONLY = re.compile(
    r'(?:(?:n/?a|none)\s*[,;:]?\s*)?[(\[]?\s*(?:the\s+)?(?:current\s+)?'
    r'incumbent\s*[)\]]?')

# A single person: one wikilink or a short run of capitalised words,
# optionally with an honorific and a regnal number.
_HON = (r'(?:(?:Sir|Dame|Lord|Lady|Prince|Princess|King|Queen|Saint|St\.'
        r'|Pope|Bishop|Archbishop|Cardinal|Rev\.|Dr\.)\s+)?')
_LINK = r'\[\[[^\[\]|]+(?:\|[^\[\]|]+)?\]\]'
_UC = r'[A-ZÀ-ÞĀ-ɏ]'
_NAME = (rf"{_UC}[\w.'’\-]*(?:\s+(?:{_UC}[\w.'’\-]*"
         r'|de|du|des|von|van|der|den|of|la|le|da|di|y|al|bin|ibn)){0,6}')
_PERSON = rf'(?P<who>{_HON}(?:{_LINK}|{_NAME})(?:\s+[IVXL]+)?)'

_VAC_WORD = rf'(?i:(?:(?P<seat>{_SEAT})\s+)?vacant)'
_SEP = r'\s*[,;:\-–]?\s*'
VAC_NEXT = re.compile(
    rf'\(?{_VAC_WORD}\)?{_SEP}\(?\s*(?i:(?:title\s+)?(?:next\s+held\s+by'
    rf'|next\s+incumbent|next\s+holder|then|later|followed\s+by))'
    rf'\s*:?\s*{_PERSON}\s*\)?\.?')
VAC_LAST = re.compile(
    rf'\(?{_VAC_WORD}\)?{_SEP}\(?\s*(?i:(?:title\s+)?(?:last\s+held\s+by'
    rf'|previously\s+held\s+by|last\s+preceded\s+by|previously(?:\s+by)?-?'
    rf'|last\s+holder|formerly\s+held\s+by))\s*:?\s*{_PERSON}\s*\)?\.?')
UNK_NEXT = re.compile(
    rf'\(?(?i:unknown)\)?{_SEP}(?i:then|later|next\s+known(?:\s+holder)?'
    rf'|followed\s+by)\s*:?\s*{_PERSON}\.?')
UNK_LAST = re.compile(
    rf'\(?(?i:unknown)\)?{_SEP}(?i:last\s+known(?:\s+holder)?|previously'
    rf'|earlier|preceded\s+by)\s*:?\s*{_PERSON}\.?')

# Map of nouns used with "New ..." / "... created" to {{s-new}} codes.
# '' means the template default ("New title").
NEW_NOUNS = {
    'office': 'office', 'post': 'post', 'position': 'post',
    'seat': 'seat', 'district': 'district', 'electoral district': 'district',
    'constituency': 'constituency', 'riding': 'riding',
    'division': 'division', 'diocese': 'diocese', 'archdiocese': 'diocese',
    'eparchy': 'diocese', 'see': 'diocese', 'bishopric': 'diocese',
    'award': 'award', 'prize': 'award',
    'championship': 'championship', 'chart': 'chart', 'command': 'command',
    'convention': 'convention', 'creation': 'creation', 'title': '',
    'department': 'department', 'dicastery': 'dicastery',
    'institution': 'institution', 'university': 'university',
    'regiment': 'regiment', 'unit': 'unit', 'programme': 'programme',
    'program': 'programme', 'parliament': 'parliament',
    'assembly': 'assembly', 'forum': 'forum', 'party': 'party',
    'political party': 'party', 'ministerial post': 'minister',
    'show': 'show', 'television show': 'tv', 'tv show': 'tv',
    'sporting event': 'sports',
}
_NOUN = '|'.join(sorted(map(re.escape, NEW_NOUNS), key=len, reverse=True))
_MADE_WORDS = 'created|established|formed|founded|instituted|constituted'
_MADE = rf'(?:{_MADE_WORDS})'
NEW_A = re.compile(
    rf'(?:none[,;:]?\s+)?(?:new|newly\s+(?:{_MADE_WORDS}|activated))'
    rf'(?:\s+(?P<noun>{_NOUN}))?')
NEW_B = re.compile(
    rf'(?:none[,;:]?\s+)?(?:(?:new|newly)\s+)?(?:(?P<noun>{_NOUN})\s+)?'
    rf'(?:newly\s+)?{_MADE}')
RECREATED = re.compile(rf'(?:(?:{_NOUN})\s+)?re-?created')

NON_KEYWORDS = re.compile(r'abolished|dissolved|extinct', re.I)
OTHER_KEYWORDS = re.compile(r'vacant|incumbent|unknown|suspended|new', re.I)


@dataclass
class Replacement:
    kind: str                      # 's-inc', 's-vac', 's-non', 's-new'
    params: list = field(default_factory=list)  # [(name or None, value)]

    @property
    def starts_row(self) -> bool:
        return self.kind in ('s-new',)

    @property
    def ends_row(self) -> bool:
        return self.kind in ('s-inc',)

    def supports(self, param: str) -> bool:
        return param == 'rows' or (param == 'as' and self.kind == 's-vac')


def _person_params(m: re.Match, key: str) -> list:
    return [(key, m.group('who').strip())]


def _vac_code(seat: str | None) -> list:
    if seat and seat.lower() == 'see':
        return [(None, 'sedevacante')]
    return []


def classify(value: str, side: str, allow_links: bool = False
             ) -> tuple[Replacement | None, str]:
    """Return (replacement, reason-if-none) for a before/after value."""
    flat = flatten(value)
    if flat is None:
        return None, 'contains templates/refs/comments/HTML'
    text, nlines = flat
    c = core(text)
    if not c:
        return None, 'empty after cleanup'

    if SEDE_ONLY.fullmatch(c):
        return Replacement('s-vac', [(None, 'sedevacante')]), ''
    if VAC_ONLY.fullmatch(c):
        return Replacement('s-vac'), ''
    if UNK_ONLY.fullmatch(c):
        return Replacement('s-vac', [(None, 'unknown')]), ''
    if SUSP_ONLY.fullmatch(c):
        return Replacement('s-vac', [(None, 'suspended')]), ''

    if side == 'after':
        if INC_ONLY.fullmatch(c):
            return Replacement('s-inc'), ''
        m = VAC_NEXT.fullmatch(text)
        if m:
            return Replacement('s-vac', _vac_code(m.group('seat'))
                               + _person_params(m, 'next')), ''
        m = UNK_NEXT.fullmatch(text)
        if m:
            return Replacement('s-vac', [(None, 'unknown')]
                               + _person_params(m, 'unknnext')), ''
        if NON_KEYWORDS.search(c):
            return _classify_non(text, c, nlines, allow_links)
        return None, 'no safe pattern matched'

    # side == 'before'
    m = VAC_LAST.fullmatch(text)
    if m:
        return Replacement('s-vac', _vac_code(m.group('seat'))
                           + _person_params(m, 'last')), ''
    m = UNK_LAST.fullmatch(text)
    if m:
        return Replacement('s-vac', [(None, 'unknown')]
                           + _person_params(m, 'unknlast')), ''
    if RECREATED.fullmatch(c):
        return Replacement('s-vac', [(None, 'recreated')]), ''
    m = NEW_A.fullmatch(c) or NEW_B.fullmatch(c)
    if m:
        code = NEW_NOUNS.get(m.group('noun') or '', '')
        return Replacement('s-new', [(None, code)] if code else []), ''
    return None, 'no safe pattern matched'


def _classify_non(text, c, nlines, allow_links):
    if nlines > 1:
        return None, 'abolished/dissolved/extinct value spans several lines'
    if '[[' in text and not allow_links:
        return None, 'abolished/dissolved/extinct value contains links'
    if OTHER_KEYWORDS.search(unlink(text)):
        return None, 'mixed keywords'
    if len(text) > 120:
        return None, 'value too long'
    reason = re.sub(r'^(?i:none|n/a|nobody)\s*[,;:\-–]?\s*', '', text)
    reason = reason.strip().rstrip('.').strip()
    while reason.startswith('(') and reason.endswith(')'):
        reason = reason[1:-1].strip()
    if not reason:
        return None, 'empty reason'
    if reason[0].isalpha():
        reason = reason[0].upper() + reason[1:]
    if '=' in reason or '|' in unlink(reason):
        return None, 'reason contains = or |'
    return Replacement('s-non', [('reason', reason)]), ''


# ---------------------------------------------------------------------------
# Wikitext rewriting
# ---------------------------------------------------------------------------

@dataclass
class Result:
    text: str
    changes: Counter
    unfixed: list   # [(template, param, value, why)]
    fixed: list = field(default_factory=list)
    # fixed: [(template, param, old value, replacement wikitext)]


def _params(tpl: Template) -> dict:
    return {str(p.name).strip(): str(p.value).strip() for p in tpl.params}


def _build(kind: str, params: list, cap: bool) -> Template:
    name = kind[0].upper() + kind[1:] if cap else kind
    parts = []
    for key, value in params:
        parts.append(f'|{key}={value}' if key else f'|{value}')
    return mwp.parse('{{' + name + ''.join(parts) + '}}').nodes[0]


def _is_blank(node) -> bool:
    return isinstance(node, Comment) or (
        isinstance(node, Text) and not str(node).strip())


class Fixer:
    """Pure wikitext fixer (no network access)."""

    def __init__(self, aliases: dict | None = None,
                 allow_links: bool = False):
        self.aliases = {n: n for n in CANONICAL}
        if aliases:
            self.aliases.update(aliases)
        self.allow_links = allow_links

    def canon(self, node) -> str | None:
        if not isinstance(node, Template):
            return None
        return self.aliases.get(norm_name(node.name))

    # -- public -------------------------------------------------------------

    def fix(self, text: str) -> Result:
        code = mwp.parse(text)
        self._changes = Counter()
        self._unfixed = []
        self._fixed = []
        self._need_start = {}   # id -> node (s-vac in "before" position)
        self._need_end = {}     # id -> node (s-vac/s-non in "after" position)

        wikicodes = list(self._walk(code))
        for wc in reversed(wikicodes):      # innermost first
            self._fix_nodes(wc)
        for wc in self._walk(code):
            self._fix_rows(wc)
        new = str(code)
        self._find_leftovers(new)
        return Result(new, self._changes, self._unfixed, self._fixed)

    # -- traversal ----------------------------------------------------------

    def _walk(self, wc):
        yield wc
        for node in wc.nodes:
            if isinstance(node, Template):
                for p in node.params:
                    yield from self._walk(p.value)
            elif getattr(node, 'contents', None) is not None and hasattr(
                    node.contents, 'nodes'):
                yield from self._walk(node.contents)

    def _fix_nodes(self, wc):
        i = 0
        while i < len(wc.nodes):
            node = wc.nodes[i]
            new_nodes = None
            canon = self.canon(node)
            if canon == 's-aft':
                new_nodes = self._fix_cell(node, 'after')
            elif canon == 's-bef':
                new_nodes = self._fix_cell(node, 'before')
            elif canon == 's-ttl':
                self._fix_title(node, 's-ttl')
            elif canon == 'succession box':
                new_nodes = self._fix_sbox(node)
            if new_nodes:
                wc.nodes[i:i + 1] = new_nodes
                i += len(new_nodes)
            else:
                i += 1

    # -- s-bef / s-aft ------------------------------------------------------

    def _fix_cell(self, node: Template, side: str):
        tname = 's-aft' if side == 'after' else 's-bef'
        params = _params(node)
        value = params.get(side, '')
        if not (tracked_after(value) if side == 'after'
                else tracked_before(value)):
            return None
        allowed = {side, 'rows', 'as'} | {f'{side}{n}' for n in range(2, 11)}
        extra = {k for k in set(params) - allowed if params[k]}
        if extra:
            return self._skip(tname, side, value,
                              f'unexpected parameters: {sorted(extra)}')
        if any(params.get(f'{side}{n}') for n in range(2, 11)):
            return self._skip(tname, side, value,
                              f'has {side}2+ parameters')
        rep = self._classify(tname, side, value)
        if rep is None:
            return None
        if not self._carry(rep, params, tname, side, value):
            return None
        cap = str(node.name).strip()[:1].isupper()
        new = _build(rep.kind, rep.params, cap)
        self._mark(new, rep, side)
        self._changes[f'{tname}→{rep.kind}'] += 1
        self._fixed.append((tname, side, value, str(new)))
        return [new]

    def _classify(self, tname, side, value):
        rep, why = classify(value, side, self.allow_links)
        if rep is None:
            self._skip(tname, side, value, why)
        return rep

    def _carry(self, rep: Replacement, params: dict, tname, side, value):
        for key in ('as', 'rows'):
            v = params.get(key, '')
            if not v:
                continue
            if not rep.supports(key):
                self._skip(tname, side, value,
                           f'|{key}= not supported by {{{{{rep.kind}}}}}')
                return False
            rep.params.append((key, v))
        return True

    def _mark(self, node, rep: Replacement, side: str):
        if side == 'before' and not rep.starts_row:
            self._need_start[id(node)] = node
        if side == 'after' and not rep.ends_row:
            self._need_end[id(node)] = node

    def _skip(self, tname, param, value, why):
        self._unfixed.append((tname, param, value, why))
        return None

    # -- s-ttl --------------------------------------------------------------

    def _fix_title(self, node: Template, tname: str) -> bool:
        if not node.has('title'):
            return False
        title = str(node.get('title').value)
        if not TITLE_WITH.search(title):
            return False
        if node.has('with') and str(node.get('with').value).strip():
            self._skip(tname, 'title', title.strip(), '|with= already set')
            return False
        m = re.fullmatch(
            r"(?P<lead>\s*)(?P<t>.*?)\s*<br\s*/?\s*>\s*(?P<q>'*)\s*with\s+"
            r"(?P<w>.+?)\s*(?P=q)(?P<trail>\s*)", title, flags=re.S | re.I)
        if not m or re.search(r'<br', m.group('w'), re.I):
            self._skip(tname, 'title', title.strip(),
                       'could not split title/with')
            return False
        node.add('title', m.group('t'))     # mwparserfromhell keeps spacing
        node.add('with', m.group('w').strip())
        self._changes[f'{tname}: title<br>with→|with='] += 1
        self._fixed.append((tname, 'title', title.strip(),
                            f'title={m.group("t").strip()} '
                            f'|with={m.group("w").strip()}'))
        return True

    # -- {{Succession box}} ---------------------------------------------------

    SBOX_PARAMS = ({'before', 'after', 'title', 'years', 'alongside', 'with',
                    'rows'}
                   | {f'before{n}' for n in range(2, 6)}
                   | {f'after{n}' for n in range(2, 6)}
                   | {f'with{n}' for n in range(2, 26)})

    def _fix_sbox(self, node: Template):
        tname = 'succession box'
        params = _params(node)
        before, after = params.get('before', ''), params.get('after', '')
        b_bad, a_bad = tracked_before(before), tracked_after(after)
        if not (b_bad or a_bad):
            self._fix_title(node, tname)
            return None
        extra = {k for k in set(params) - self.SBOX_PARAMS if params[k]}
        if extra:
            for side, value, bad in (('before', before, b_bad),
                                     ('after', after, a_bad)):
                if bad:
                    self._skip(tname, side, value,
                               f'unexpected parameters: {sorted(extra)}')
            return None

        b_rep = a_rep = None
        if b_bad:
            if any(params.get(f'before{n}') for n in range(2, 6)):
                self._skip(tname, 'before', before, 'has before2+ parameters')
            else:
                b_rep = self._classify(tname, 'before', before)
        if a_bad:
            if any(params.get(f'after{n}') for n in range(2, 6)):
                self._skip(tname, 'after', after, 'has after2+ parameters')
            else:
                a_rep = self._classify(tname, 'after', after)
        if b_rep is None and a_rep is None:
            self._fix_title(node, tname)
            return None

        rows = params.get('rows', '')
        if b_rep:
            if rows:
                b_rep.params.append(('rows', rows))
            bef = _build(b_rep.kind, b_rep.params, False)
            self._mark(bef, b_rep, 'before')
        else:
            bef = _build('s-bef', self._side_params(params, 'before', 5, rows),
                         False)
        if a_rep:
            if rows:
                a_rep.params.append(('rows', rows))
            aft = _build(a_rep.kind, a_rep.params, False)
            self._mark(aft, a_rep, 'after')
        else:
            aft = _build('s-aft', self._side_params(params, 'after', 5, rows),
                         False)

        ttl_params = [('title', params.get('title', ''))]
        for key in ['years', 'alongside', 'with'] + [
                f'with{n}' for n in range(2, 26)]:
            if params.get(key):
                ttl_params.append((key, params[key]))
        if rows:
            ttl_params.append(('rows', rows))
        ttl = _build('s-ttl', ttl_params, False)
        self._fix_title(ttl, tname)

        parts = []
        if b_rep:
            parts.append(f'before→{b_rep.kind}')
            self._fixed.append((tname, 'before', before, str(bef)))
        if a_rep:
            parts.append(f'after→{a_rep.kind}')
            self._fixed.append((tname, 'after', after, str(aft)))
        self._changes[f'succession box split ({", ".join(parts)})'] += 1
        return [bef, Text('\n'), ttl, Text('\n'), aft]

    @staticmethod
    def _side_params(params, side, maxn, rows):
        out = []
        if side in params:
            out.append((side, params[side]))
        for n in range(2, maxn + 1):
            if params.get(f'{side}{n}'):
                out.append((f'{side}{n}', params[f'{side}{n}']))
        if rows:
            out.append(('rows', rows))
        return out

    # -- table rows ---------------------------------------------------------

    def _fix_rows(self, wc):
        i = 0
        while i < len(wc.nodes):
            node = wc.nodes[i]
            if id(node) in self._need_start and self._need_start[
                    id(node)] is node:
                if not self._prev_ends_row(wc.nodes, i):
                    wc.nodes.insert(i, Text('|-\n'))
                    i += 1
            if id(node) in self._need_end and self._need_end[
                    id(node)] is node:
                if not self._next_starts_row(wc.nodes, i):
                    wc.nodes.insert(i + 1, Text('\n|-'))
                    i += 1
            i += 1

    def _prev_ends_row(self, nodes, i) -> bool:
        j = i - 1
        while j >= 0 and _is_blank(nodes[j]):
            j -= 1
        if j < 0:
            return False
        node = nodes[j]
        if isinstance(node, Text):
            last = str(node).rstrip().splitlines()[-1].strip()
            return last.startswith('|-') or last.startswith('{|')
        return self.canon(node) in ROW_ENDERS

    def _next_starts_row(self, nodes, i) -> bool:
        j = i + 1
        while j < len(nodes) and _is_blank(nodes[j]):
            j += 1
        if j >= len(nodes):
            return False
        node = nodes[j]
        if isinstance(node, Text):
            first = str(node).lstrip().splitlines()[0].strip()
            return first.startswith('|-') or first.startswith('|}')
        return self.canon(node) in ROW_STARTERS

    # -- reporting ----------------------------------------------------------

    def _find_leftovers(self, text: str):
        """Report tracked values that remain, but were not already logged."""
        logged = {(p, v) for _, p, v, _ in self._unfixed}
        for tpl in mwp.parse(text).filter_templates():
            canon = self.canon(tpl)
            if canon not in ('s-aft', 's-bef', 'succession box'):
                continue
            params = _params(tpl)
            for side, check in (('after', tracked_after),
                                ('before', tracked_before)):
                if canon == 's-aft' and side == 'before':
                    continue
                if canon == 's-bef' and side == 'after':
                    continue
                v = params.get(side, '')
                if check(v) and (side, v) not in logged:
                    self._unfixed.append((canon, side, v, 'not handled'))


def make_summary(changes: Counter) -> str:
    items = ', '.join(f'{label} ×{n}' if n > 1 else label
                      for label, n in changes.most_common())
    return (f'Fix succession box misuse ([[:Category:{TRACKING_CAT}]]): '
            f'{items}')


# ---------------------------------------------------------------------------
# pywikibot bot
# ---------------------------------------------------------------------------

DEFAULT_REPORT = 'succession_box_report.tsv'
REPORT_HEADER = ('page', 'status', 'template', 'param', 'current value',
                 'replacement / reason')

# On-wiki report. Change the location with -reportpage:<title>.
DEFAULT_REPORT_PAGE = 'User:PhuzBot/Succession box report'
# A section with more rows than this is split onto numbered subpages
# (<report page>/Manual fixes/1, /2, ...) to stay well under the 2 MB page
# limit and keep the tables quick to render.
REPORT_ROWS_PER_PAGE = 2000
# Where the report wikitext goes when it is not (or cannot be) published.
LOCAL_WIKI_REPORT = 'succession_box_report.wiki'
REPO_URL = 'https://github.com/phuzion/sbox-fixer'


# ---------------------------------------------------------------------------
# On-wiki report
# ---------------------------------------------------------------------------

@dataclass
class ReportData:
    reportonly: bool
    scope: str
    stats: Counter
    fixed: list = field(default_factory=list)
    # fixed: [(page, template, param, value, replacement, status)]
    unfixed: list = field(default_factory=list)
    # unfixed: [(page, template, param, value, why)]


def _code(value, limit: int = 300) -> str:
    """Show wikitext literally inside a table cell."""
    v = re.sub(r'\s+', ' ', str(value)).strip()
    if len(v) > limit:
        v = v[:limit].rstrip() + '…'
    if not v:
        return ''
    v = re.sub(r'(?i)</nowiki', '&lt;/nowiki', v)
    return f'<code><nowiki>{v}</nowiki></code>'


def _plain(value) -> str:
    v = re.sub(r'\s+', ' ', str(value)).strip()
    v = re.sub(r'(?i)</nowiki', '&lt;/nowiki', v)
    return f'<nowiki>{v}</nowiki>' if v else ''


def _table(headers, rows) -> str:
    out = ['{| class="wikitable sortable" style="font-size:90%"',
           '! ' + ' !! '.join(headers)]
    for row in rows:
        out.append('|-')
        out.append('| ' + ' || '.join(row))
    out.append('|}')
    return '\n'.join(out)


def build_report(root: str, data: ReportData,
                 rows_per_page: int = REPORT_ROWS_PER_PAGE
                 ) -> list[tuple[str, str]]:
    """Return [(page title, wikitext), ...]; the first entry is *root*."""
    s = data.stats
    fixed_heading = ('Would be fixed by the bot' if data.reportonly
                     else 'Fixed by the bot')

    manual_rows = [
        (f'[[:{page}]]', _plain(tname), _plain(param), _code(value),
         _plain(why))
        for page, tname, param, value, why in sorted(
            data.unfixed, key=lambda r: r[0])]
    fixed_headers = ['Page', 'Template', 'Parameter', 'Current value',
                     'Replacement']
    if not data.reportonly:
        fixed_headers.append('Status')
    fixed_rows = []
    for page, tname, param, value, new, status in sorted(
            data.fixed, key=lambda r: r[0]):
        row = [f'[[:{page}]]', _plain(tname), _plain(param), _code(value),
               _code(new)]
        if not data.reportonly:
            row.append(_plain(status))
        fixed_rows.append(tuple(row))

    sections = [
        ('Needs a manual fix', 'Manual fixes',
         ['Page', 'Template', 'Parameter', 'Current value', 'Reason'],
         manual_rows),
        (fixed_heading, 'Bot fixes', fixed_headers, fixed_rows),
    ]

    if data.reportonly:
        run_type = "report only (no articles were edited)"
        fixed_line = (f"* Pages the bot would edit: "
                      f"{s['pages the bot would edit']:,}\n"
                      f"* Values the bot would fix: "
                      f"{s['values the bot would fix']:,}")
    else:
        run_type = 'editing run'
        fixed_line = (f"* Edits submitted: {s['edits submitted']:,}\n"
                      f"* Values fixed: {s['values fixed']:,}")

    main = [
        "''This page is generated by "
        f"[{REPO_URL} sbox-fixer] and is overwritten on every run, so "
        "changes made here will be lost. It lists misused succession box "
        "values found in [[:Category:" + TRACKING_CAT + "]].''",
        '',
        "* '''Last updated:''' ~~~~~",
        f"* '''Run type:''' {run_type}",
        f"* '''Scope:''' {data.scope}",
        f"* Pages checked: {s['pages checked']:,}",
        fixed_line,
        f"* Values needing a manual fix: "
        f"{s['values that need a manual fix']:,} on "
        f"{s['pages with values needing a manual fix']:,} pages",
    ]

    reasons = Counter(r[4] for r in data.unfixed)
    if reasons:
        main += ['', '== Why values need a manual fix ==',
                 _table(['Reason', 'Values'],
                        [(_plain(why), f'{n:,}')
                         for why, n in reasons.most_common()])]

    pages = []
    for heading, subname, headers, rows in sections:
        main += ['', f'== {heading} ==']
        if not rows:
            main.append("''None.''")
            continue
        if len(rows) <= rows_per_page:
            main.append(_table(headers, rows))
            continue
        chunks = [rows[i:i + rows_per_page]
                  for i in range(0, len(rows), rows_per_page)]
        main.append(f'{len(rows):,} rows, split over {len(chunks)} pages:')
        for n, chunk in enumerate(chunks, 1):
            title = f'{root}/{subname}/{n}'
            first, last = _link_text(chunk[0][0]), _link_text(chunk[-1][0])
            main.append(f'* [[{title}|Part {n}]] ({first} – {last})')
            pages.append((title, '\n'.join([
                f"''Part {n} of {len(chunks)} of the "
                f"[[{root}#{heading}|{heading.lower()}]] list in "
                f"[[{root}]]. Generated by [{REPO_URL} sbox-fixer]; "
                "changes made here will be lost. Last updated: ~~~~~''",
                '',
                _table(headers, chunk),
            ])))
    return [(root, '\n'.join(main) + '\n')] + pages


def save_local_report(pages, why: str, path: str = LOCAL_WIKI_REPORT):
    """Write the report wikitext to a local file instead of the wiki."""
    import pywikibot
    with open(path, 'w', encoding='utf-8') as fh:
        for title, text in pages:
            fh.write(f'<!-- ===== {title} ===== -->\n{text}\n')
    pywikibot.warning(f'Report not published because {why}; its wikitext '
                      f'({len(pages)} page(s)) was saved to {path}')


def _link_text(link: str) -> str:
    """'[[:Foo]]' -> 'Foo' (escaped for use in a list item)."""
    return _plain(link[3:-2]) if link.startswith('[[:') else _plain(link)


def load_aliases(site) -> dict:
    """Map every redirect name of the templates we care about to its
    canonical name."""
    import pywikibot
    aliases = {}
    for canon in CANONICAL:
        page = pywikibot.Page(site, canon, ns=10)
        try:
            for redir in page.redirects(namespaces=10):
                aliases[norm_name(redir.title(with_ns=False))] = canon
        except Exception as exc:   # noqa: BLE001 - keep going offline-ish
            pywikibot.warning(f'Could not load redirects to {canon}: {exc}')
    return aliases


def default_generator(site, only: str | None):
    import pywikibot
    cat = pywikibot.Category(site, f'Category:{TRACKING_CAT}')
    seen = set()
    for sub in cat.subcategories():
        if only and only.lower() not in sub.title().lower():
            continue
        pywikibot.info(f'\n<<lightyellow>>Category: {sub.title()}')
        for page in sub.articles(namespaces=0):
            if page.title() in seen:
                continue
            seen.add(page.title())
            yield page


def main(*args: str) -> None:
    import pywikibot
    from pywikibot import pagegenerators
    from pywikibot.bot import ExistingPageBot, SingleSiteBot

    class SuccessionBoxBot(SingleSiteBot, ExistingPageBot):
        update_options = {
            'report': None,
            'reportonly': False,
            'reportpage': DEFAULT_REPORT_PAGE,
            'scope': '',
            'allowlinks': False,
            'summary': None,
        }

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.fixer = Fixer(load_aliases(self.site),
                               allow_links=self.opt.allowlinks)
            self.stats = Counter()
            self.fixed_rows = []
            self.unfixed_rows = []
            self.report_file = self.report_writer = None
            if self.opt.report:
                # utf-8-sig so Excel detects the encoding; rows are written
                # (and flushed) page by page so an interrupted run keeps
                # everything done so far.
                self.report_file = open(self.opt.report, 'w', newline='',
                                        encoding='utf-8-sig')
                self.report_writer = csv.writer(self.report_file,
                                                delimiter='\t')
                self.report_writer.writerow(REPORT_HEADER)
                self.report_file.flush()

        def write_report(self, title, result, fixed_status):
            for tname, param, value, new in result.fixed:
                self.fixed_rows.append(
                    (title, tname, param, value, new, fixed_status))
            for row in result.unfixed:
                self.unfixed_rows.append((title, *row))
            if not self.report_writer:
                return
            for tname, param, value, new in result.fixed:
                self.report_writer.writerow(
                    (title, fixed_status, tname, param, value, new))
            for tname, param, value, why in result.unfixed:
                self.report_writer.writerow(
                    (title, 'needs manual fix', tname, param, value, why))
            self.report_file.flush()

        def skip_page(self, page):
            if page.namespace() != 0:
                pywikibot.info(f'Skipping {page} (not an article)')
                return True
            if super().skip_page(page):
                return True
            if page.isRedirectPage():
                pywikibot.info(f'Skipping {page} (redirect)')
                return True
            return False

        def treat_page(self):
            page = self.current_page
            result = self.fixer.fix(page.text)
            self.stats['pages checked'] += 1
            self.stats['values that need a manual fix'] += len(
                result.unfixed)
            if result.unfixed:
                self.stats['pages with values needing a manual fix'] += 1

            if self.opt.reportonly:
                # Never edits articles and never asks for confirmation.
                self.write_report(page.title(), result, 'would fix')
                n = len(result.fixed)
                pywikibot.info(f'{n} fixable, {len(result.unfixed)} '
                               'need a manual fix')
                if n:
                    self.stats['pages the bot would edit'] += 1
                    self.stats['values the bot would fix'] += n
                return

            if not result.changes:
                pywikibot.info('No safely fixable succession box issues.')
                self.write_report(page.title(), result, 'fixed')
                return
            summary = self.opt.summary or make_summary(result.changes)
            saved = self.put_current(result.text, summary=summary)
            self.write_report(page.title(), result,
                              'fixed' if saved else 'not saved')
            if saved:
                # With -always pywikibot saves asynchronously, so this
                # counts edits submitted; failures are logged separately.
                self.stats['edits submitted'] += 1
                self.stats['values fixed'] += len(result.fixed)

        def teardown(self):
            if self.report_file:
                self.report_file.close()
                pywikibot.info(f'TSV report written to {self.opt.report}')
            for key, n in sorted(self.stats.items()):
                pywikibot.info(f'{key}: {n}')
            try:
                self.publish_report()
            finally:
                super().teardown()

        def publish_report(self):
            root = self.opt.reportpage or DEFAULT_REPORT_PAGE
            data = ReportData(self.opt.reportonly, self.opt.scope,
                              self.stats, self.fixed_rows, self.unfixed_rows)
            pages = build_report(root, data)
            if not self.opt.reportpage:
                save_local_report(pages, 'publishing was turned off '
                                  '(-noreportpage)')
                return
            if not getattr(self, 'generator_completed', False):
                # Don't let a partial run overwrite a complete report.
                save_local_report(pages, 'the run did not finish')
                return
            summary = (
                f'Updating succession box misuse report: '
                f'{len(self.unfixed_rows):,} values need a manual fix, '
                f'{len(self.fixed_rows):,} '
                + ('fixable by bot' if self.opt.reportonly else 'bot fixes'))
            try:
                for title, text in pages:
                    pywikibot.info(f'Saving report page [[{title}]]')
                    page = pywikibot.Page(self.site, title)
                    page.text = text
                    page.save(summary=summary, minor=False, bot=True)
                self.retire_old_subpages(root, pages)
            except Exception as exc:  # noqa: BLE001 - keep the report
                pywikibot.error(f'Could not save the report page: {exc}')
                save_local_report(pages, 'saving it failed')

        def retire_old_subpages(self, root, pages):
            """Blank-out subpages left over from a longer earlier report."""
            used = {t for t, _ in pages}
            for subname in ('Manual fixes', 'Bot fixes'):
                n = 1
                while True:
                    title = f'{root}/{subname}/{n}'
                    n += 1
                    if title in used:
                        continue
                    page = pywikibot.Page(self.site, title)
                    if not page.exists():
                        break
                    if page.text.startswith("''No longer used"):
                        continue
                    page.text = (f"''No longer used: this part of the "
                                 f"report is now empty. See [[{root}]].''\n")
                    page.save(summary='Succession box report: part no '
                              'longer used', minor=False, bot=True)

    local_args = pywikibot.handle_args(args)
    gen_factory = pagegenerators.GeneratorFactory()
    local_args = gen_factory.handle_args(local_args)

    options = {}
    only = None
    for arg in local_args:
        opt, _, value = arg.partition(':')
        if opt == '-always':
            options['always'] = True
        elif opt == '-allowlinks':
            options['allowlinks'] = True
        elif opt == '-report':
            options['report'] = value or DEFAULT_REPORT
        elif opt == '-reportonly':
            options['reportonly'] = True
        elif opt == '-reportpage':
            if not value:
                pywikibot.error('-reportpage needs a page title, e.g. '
                                '-reportpage:"User:Example/Report"')
                return
            options['reportpage'] = value
        elif opt == '-noreportpage':
            options['reportpage'] = None
        elif opt == '-summary':
            options['summary'] = value
        elif opt == '-only':
            only = value
        else:
            pywikibot.bot.suggest_help(unknown_parameters=[arg])
            return

    if options.get('reportonly'):
        options.pop('always', None)

    site = pywikibot.Site()

    # Describe what this run covers, for the report header.
    scope = []
    if gen_factory.gens:
        scope.append('selected pages only')
    elif only:
        scope.append(f'subcategories matching "{only}"')
    else:
        scope.append(f'all of [[:Category:{TRACKING_CAT}]]')
    if gen_factory.limit:
        scope.append(f'limited to {gen_factory.limit:,} pages')
    options['scope'] = ', '.join(scope)

    # Log in now rather than after a long run, so a missing username or
    # password shows up straight away.
    if options.get('reportpage', DEFAULT_REPORT_PAGE) or not options.get(
            'reportonly'):
        try:
            site.login()
        except Exception as exc:  # noqa: BLE001
            pywikibot.error(
                f'Could not log in ({exc}). Saving the report page needs a '
                'logged-in account; set usernames[...] in user-config.py, '
                'or use -noreportpage to keep the report local.')
            return

    gen = gen_factory.getCombinedGenerator(preload=True)
    if gen is None:
        gen = default_generator(site, only)
        if gen_factory.limit:
            gen = itertools.islice(gen, gen_factory.limit)
        gen = pagegenerators.PreloadingGenerator(gen)

    SuccessionBoxBot(generator=gen, site=site, **options).run()


def test_file(path: str, allow_links: bool = False) -> None:
    """Offline: fix a local wikitext file and print a unified diff."""
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    result = Fixer(allow_links=allow_links).fix(text)
    sys.stdout.writelines(difflib.unified_diff(
        text.splitlines(True), result.text.splitlines(True),
        'before', 'after'))
    print('\nSummary:', make_summary(result.changes)
          if result.changes else '(no changes)')
    for row in result.unfixed:
        print('UNFIXED:', ' | '.join(row))


if __name__ == '__main__':
    argv = sys.argv[1:]
    tf = [a for a in argv if a.startswith('-testfile:')]
    if tf:
        test_file(tf[0].partition(':')[2], '-allowlinks' in argv)
    else:
        main(*argv)
