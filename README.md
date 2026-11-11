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
usernames['wikipedia']['en'] = 'PhuzBot'
password_file = 'user-password.py'
```

The script logs in to save the report page (and, in editing runs, the
articles). Create a [bot password](https://en.wikipedia.org/wiki/Special:BotPasswords)
for the account with "Edit existing pages" and "Create, edit, and move pages"
grants, and put it in `user-password.py` next to `user-config.py`:

```python
('PhuzBot', BotPassword('sbox-fixer', 'the-generated-password'))
```

`user-config.py`, `user-password.py`, pywikibot's cache/log files and local
report files are git-ignored.

## Usage

### Report only (no edits)

```bash
python succession_box_fixer.py -reportonly
```

This reads every page in the tracking subcategories without editing or asking
anything, then saves the report as a wikitable to
[User:PhuzBot/Succession box report](https://en.wikipedia.org/wiki/User:PhuzBot/Succession_box_report).
Each page is visited once, even if it's in several subcategories.

Narrow it down while trying it out:

```bash
python succession_box_fixer.py -reportonly -limit:50
python succession_box_fixer.py -reportonly -only:incumbent
python succession_box_fixer.py -reportonly -page:"Some article"
```

#### The report page

- A summary: when it was generated, the run type and scope, and counts of
  pages checked, values the bot would fix and values needing a manual fix.
- **Why values need a manual fix**: each skip reason with a count.
- **Needs a manual fix**: page, template, parameter, current value, reason.
- **Would be fixed by the bot** (or **Fixed by the bot** after an editing run,
  with a status column): page, template, parameter, current value, replacement.

The tables are sortable. A section with more than 2,000 rows is split onto
numbered subpages (`…/Manual fixes/1`, `…/Bot fixes/1`, `…/Bot fixes/2`, …),
linked from the main page. A full run produces roughly a dozen of these.
Subpages left over from an earlier, longer report are replaced with a short
"no longer used" note.

The page is overwritten on every run, so it always reflects the latest run.

#### Choosing where the report goes

```bash
python succession_box_fixer.py -reportonly -reportpage:"User:PhuzBot/Some other page"
```

To change the default permanently, edit `DEFAULT_REPORT_PAGE` near the middle
of `succession_box_fixer.py`.

#### Keeping the report off the wiki

```bash
python succession_box_fixer.py -reportonly -noreportpage
```

This saves the wikitext to `succession_box_report.wiki` instead, and with
`-reportonly` it doesn't need to log in at all. The same local file is written
if a run is interrupted (Ctrl+C or an error), so a partial run never overwrites
a complete report on the wiki, or if saving the page fails.

The script logs in at the start of a run, so a missing username or password
shows up immediately rather than after hours of reading.

#### Local TSV (optional)

Add `-report:<file>` to also write a tab-separated file with the same rows. It
opens in Excel or Google Sheets and is written as the run goes, so it keeps
everything up to an interruption.

### Editing

Editing at this scale on English Wikipedia needs a bot account and an approved
[bot request](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval).
Add the account's username to `user-config.py`, then:

```bash
python succession_box_fixer.py           # shows each diff, asks before saving
python succession_box_fixer.py -always   # saves without asking
```

Editing runs also update the report page, listing what was fixed and what
still needs a person. A trial editing run with `-page:` or `-limit:` will
replace the full report, so add `-noreportpage` to those.

### Options

| Option | Effect |
|---|---|
| `-reportonly` | Read and report only; never edit articles. |
| `-reportpage:<title>` | Where to save the report wikitable (default `User:PhuzBot/Succession box report`). |
| `-noreportpage` | Don't publish the report; save its wikitext to `succession_box_report.wiki`. |
| `-report:<file>` | Also write a local TSV (default `succession_box_report.tsv`). |
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
