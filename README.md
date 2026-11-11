# sbox-fixer

A [pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot) script that cleans up
succession-box misuse on English Wikipedia, as tracked in
[Category:Succession box misuse tracking](https://en.wikipedia.org/wiki/Category:Succession_box_misuse_tracking).

Editors often type text like "Incumbent", "Vacant", "New office" or
"Office abolished" into `{{s-aft}}`, `{{s-bef}}` or `{{Succession box}}`. The
tracking categories ask for the dedicated templates instead. This script makes
those replacements.

## What it fixes

| Misuse | Replacement |
|---|---|
| `after = Incumbent`, `N/A (incumbent)`, `[[Incumbent]]` | `{{s-inc}}` |
| `after`/`before = Vacant`, `Post vacant` | `{{s-vac}}` |
| `Vacant, next held by [[X]]` / `Vacant, last held by [[X]]` | `{{s-vac\|next=[[X]]}}` / `{{s-vac\|last=[[X]]}}` |
| `Unknown` / `Unknown, then [[X]]` | `{{s-vac\|unknown}}` / `{{s-vac\|unknown\|unknnext=[[X]]}}` |
| `Sede vacante`, `See vacant` | `{{s-vac\|sedevacante}}` |
| `Suspended` / `Position recreated` | `{{s-vac\|suspended}}` / `{{s-vac\|recreated}}` |
| `Office abolished`, `Party dissolved`, `Title extinct` | `{{s-non\|reason=…}}` (original wording kept) |
| `New office`, `Position created`, `Newly created` | `{{s-new\|office}}`, `{{s-new\|post}}`, `{{s-new}}` |
| `{{s-ttl\|title=X<br />with Y}}` | `{{s-ttl\|title=X\|with=Y}}` |

- `{{Succession box}}` calls with a misused value are split into
  `{{s-bef}}`/`{{s-ttl}}`/`{{s-aft}}` (or their replacements), because the
  wrapper has no way to express "incumbent", "vacant", etc.
- `{{s-vac}}` and `{{s-non}}` don't produce table-row markup the way
  `{{s-bef}}`/`{{s-aft}}` do. The script adds a `|-` line only where a
  neighbouring template wouldn't already start or end the row, so the rendered
  table keeps the same rows and cells.
- "New position" becomes `{{s-new|post}}`, which displays as "New post"
  (`{{s-new}}` has no "position" option).

### What it deliberately leaves alone

A value is only rewritten when the **whole** value matches a known pattern.
These are skipped and listed in the report for a person to fix:

- values that name a real successor, e.g. `[[A]]<br/>(vacant until 2017)`
- values containing references, footnotes (`<sup>`), templates or comments
- ambiguous wording, e.g. `Unknown or Vacant`, `Vacant until 1927`, `vacant?`
- "abolished/dissolved" values containing links (unless `-allowlinks`)
- calls with extra parameters the replacement can't carry (`before2=`,
  `as=` on templates that don't support it, unknown non-empty parameters)
- wrapper templates such as `{{US House succession box}}`

In a read-only test on 433 real pages from the category, 86% were fully cleaned
in one pass. Every page gets all of its fixes in a single edit, and running the
script again on the result changes nothing.

## Setup

Requires Python 3.10+.

```bash
pip install pywikibot mwparserfromhell
```

Create a `user-config.py` in the folder you run the script from:

```python
family = 'wikipedia'
mylang = 'en'
# Only needed for editing (not for -reportonly):
# usernames['wikipedia']['en'] = 'YourBotAccount'
```

`user-config.py`, pywikibot's cache/log files and report TSVs are git-ignored.

## Usage

### Report only (no edits)

```bash
python succession_box_fixer.py -reportonly
```

This reads every page in the tracking subcategories and writes
`succession_box_report.tsv`. It never logs in, never asks for confirmation and
never edits. Each page is visited once, even if it's in several subcategories.

Narrow it down while trying it out:

```bash
python succession_box_fixer.py -reportonly -limit:50 -report:trial.tsv
python succession_box_fixer.py -reportonly -only:incumbent -report:incumbent.tsv
python succession_box_fixer.py -reportonly -page:"Some article"
```

The report has one row per misused value:

| Column | Meaning |
|---|---|
| `page` | Article title |
| `status` | `would fix`, `needs manual fix`, `fixed` or `not saved` |
| `template` | `s-aft`, `s-bef`, `s-ttl` or `succession box` |
| `param` | `after`, `before` or `title` |
| `current value` | The wikitext currently in the parameter |
| `replacement / reason` | The template it would become, or why it was skipped |

The file is UTF-8 and opens directly in Excel or Google Sheets. It is written as
the run goes, so stopping with Ctrl+C keeps everything done so far.

### Editing

Editing at this scale on English Wikipedia needs a bot account and an approved
[bot request](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval).
Add the account's username to `user-config.py`, then:

```bash
python succession_box_fixer.py -report:run.tsv           # shows each diff, asks before saving
python succession_box_fixer.py -report:run.tsv -always   # saves without asking
```

### Options

| Option | Effect |
|---|---|
| `-reportonly` | Read and report only; never edit. Implies `-report`. |
| `-report:<file>` | Write the TSV report (default `succession_box_report.tsv`). |
| `-only:<text>` | Only subcategories whose name contains `<text>`, e.g. `-only:incumbent`, `-only:"'before'"`. |
| `-allowlinks` | Also convert abolished/dissolved/extinct values that contain links. |
| `-summary:<text>` | Override the edit summary. |
| `-always` | Save without asking. |
| `-testfile:<file>` | Offline: fix a local wikitext file and print a diff. No network. |

Standard pywikibot options also work: page generators (`-page:`, `-cat:`,
`-file:`, `-limit:`) and global options (`-simulate`, `-lang:`, `-user:`,
`-pt:`). With no page generator, every subcategory of the tracking category is
processed.

## Tests

```bash
python -m unittest test_succession_box_fixer
```

The tests are offline and cover the value patterns, the table-row handling,
`{{Succession box}}` splitting and the report data.
