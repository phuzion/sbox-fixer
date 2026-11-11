"""Offline tests for succession_box_fixer (run: python -m pytest -q)."""
import unittest
from collections import Counter

from succession_box_fixer import (Fixer, ReportData, build_report, classify,
                                  make_summary)


def fix(text, **kw):
    return Fixer(**kw).fix(text)


class ClassifyTests(unittest.TestCase):

    def check(self, value, side, kind, params=()):
        rep, why = classify(value, side)
        self.assertIsNotNone(rep, f'{value!r} skipped: {why}')
        self.assertEqual(rep.kind, kind)
        self.assertEqual(rep.params, list(params))

    def skip(self, value, side):
        rep, _ = classify(value, side)
        self.assertIsNone(rep, f'{value!r} should be skipped, got {rep}')

    def test_after(self):
        self.check("'''Incumbent'''", 'after', 's-inc')
        self.check('N/A (incumbent)', 'after', 's-inc')
        self.check('[[Incumbent]]', 'after', 's-inc')
        self.check("''Post vacant''", 'after', 's-vac')
        self.check('Vacant seat', 'after', 's-vac')
        self.check('[[Episcopal see|See vacant]]', 'after', 's-vac',
                   [(None, 'sedevacante')])
        self.check('Unknown', 'after', 's-vac', [(None, 'unknown')])
        self.check('Unknown, then [[Q. Adventus]]', 'after', 's-vac',
                   [(None, 'unknown'), ('unknnext', '[[Q. Adventus]]')])
        self.check('Vacant<br><small>(next held by [[A B|Sir A B]])</small>',
                   'after', 's-vac', [('next', '[[A B|Sir A B]]')])
        self.check('Suspended', 'after', 's-vac', [(None, 'suspended')])
        self.check("''Office abolished''", 'after', 's-non',
                   [('reason', 'Office abolished')])
        self.check('None (District dissolved)', 'after', 's-non',
                   [('reason', 'District dissolved')])

    def test_after_skips(self):
        self.skip('[[John Smith]] (incumbent)', 'after')
        self.skip('Unknown or Vacant', 'after')
        self.skip('Vacant until 1927', 'after')
        self.skip("''Vacant''<sup>1</sup>", 'after')
        self.skip('[[A]]<br/>{{small|(vacant until 2017)}}', 'after')
        self.skip('Dissolved, became [[17th Army]]', 'after')
        self.skip('Incumbent<!-- update -->', 'after')
        self.skip("[[Li Qiang]]'s wife (name unknown)", 'after')

    def test_before(self):
        self.check('New office', 'before', 's-new', [(None, 'office')])
        self.check('New position', 'before', 's-new', [(None, 'post')])
        self.check('Newly created', 'before', 's-new')
        self.check('New title →', 'before', 's-new')
        self.check("''Position created''", 'before', 's-new',
                   [(None, 'post')])
        self.check('New constituency', 'before', 's-new',
                   [(None, 'constituency')])
        self.check('District recreated', 'before', 's-vac',
                   [(None, 'recreated')])
        self.check('Vacant, last held by [[X Y]]', 'before', 's-vac',
                   [('last', '[[X Y]]')])
        self.check("''unknown''", 'before', 's-vac', [(None, 'unknown')])

    def test_before_skips(self):
        self.skip('New company', 'before')
        self.skip('Dynasty created', 'before')
        self.skip('First member, riding created in 1976', 'before')
        self.skip("''vacant?''", 'before')
        self.skip('Vacant<br/>[[Marie Thérèse de Bourbon]]', 'before')
        self.skip('New Zealand Party', 'before')


class WikitextTests(unittest.TestCase):

    def test_s_aft_incumbent(self):
        text = ('{{s-start}}\n{{s-off}}\n{{s-bef|before=[[A]]}}\n'
                '{{s-ttl|title=[[Mayor]]|years=2020–present}}\n'
                "{{s-aft|after=''Incumbent''}}\n{{s-end}}")
        r = fix(text)
        self.assertIn('{{s-ttl|title=[[Mayor]]|years=2020–present}}\n'
                      '{{s-inc}}\n{{s-end}}', r.text)
        self.assertEqual(r.changes['s-aft→s-inc'], 1)

    def test_case_preserved(self):
        r = fix('{{S-aft | after = Incumbent}}')
        self.assertEqual(r.text, '{{S-inc}}')

    def test_svac_after_then_bef_gets_no_extra_row(self):
        text = ('{{s-bef|before=[[A]]}}\n{{s-ttl|title=T}}\n'
                '{{s-aft|after=Vacant}}\n'
                '{{s-bef|before=[[B]]}}\n{{s-ttl|title=U}}\n'
                '{{s-aft|after=[[C]]}}')
        r = fix(text)
        self.assertIn('{{s-vac}}\n{{s-bef|before=[[B]]}}', r.text)

    def test_svac_both_sides_row_separator(self):
        text = ('{{s-bef|before=[[A]]}}\n{{s-ttl|title=T}}\n'
                '{{s-aft|after=Vacant}}\n'
                '{{s-bef|before=Vacant}}\n{{s-ttl|title=U}}\n'
                '{{s-aft|after=[[C]]}}')
        r = fix(text)
        self.assertIn('{{s-vac}}\n|-\n{{s-vac}}\n{{s-ttl|title=U}}', r.text)
        self.assertEqual(r.text.count('|-'), 1)

    def test_svac_before_after_header_needs_row(self):
        text = '{{s-off}}\n{{s-bef|before=Vacant}}\n{{s-ttl|title=T}}'
        r = fix(text)
        self.assertIn('{{s-off}}\n|-\n{{s-vac}}', r.text)

    def test_svac_before_after_s_aft_no_row(self):
        text = '{{s-aft|after=[[X]]}}\n{{s-bef|before=Unknown}}'
        r = fix(text)
        self.assertEqual(r.text,
                         '{{s-aft|after=[[X]]}}\n{{s-vac|unknown}}')

    def test_snon_before_end(self):
        r = fix('{{s-aft|after=Seat abolished}}\n{{s-end}}')
        self.assertEqual(r.text,
                         '{{s-non|reason=Seat abolished}}\n{{s-end}}')

    def test_snon_before_ttl_gets_row(self):
        r = fix('{{s-aft|after=Seat abolished}}\n{{s-vac}}')
        self.assertEqual(
            r.text, '{{s-non|reason=Seat abolished}}\n|-\n{{s-vac}}')

    def test_as_param(self):
        r = fix('{{s-aft|after=Vacant|as=Duke}}\n{{s-end}}')
        self.assertEqual(r.text, '{{s-vac|as=Duke}}\n{{s-end}}')
        r = fix('{{s-aft|after=Incumbent|as=Duke}}')
        self.assertEqual(r.text, '{{s-aft|after=Incumbent|as=Duke}}')
        self.assertTrue(r.unfixed)

    def test_after2_skipped(self):
        r = fix('{{s-aft|after=Incumbent|after2=[[X]]}}')
        self.assertFalse(r.changes)

    def test_succession_box_split(self):
        text = ('{{s-start}}\n{{Succession box | before = New office '
                '| title = [[Chair]] | years = 2001–present '
                '| after = Incumbent}}\n{{s-end}}')
        r = fix(text)
        self.assertEqual(
            r.text, '{{s-start}}\n{{s-new|office}}\n'
            '{{s-ttl|title=[[Chair]]|years=2001–present}}\n{{s-inc}}\n'
            '{{s-end}}')

    def test_succession_box_one_side(self):
        text = ('{{succession box|before=[[A]]|title=T|years=1|'
                'after=Vacant|rows=2}}\n{{s-end}}')
        r = fix(text)
        self.assertEqual(
            r.text, '{{s-bef|before=[[A]]|rows=2}}\n'
            '{{s-ttl|title=T|years=1|rows=2}}\n{{s-vac|rows=2}}\n{{s-end}}')

    def test_succession_box_fine_untouched(self):
        text = '{{Succession box|before=[[A]]|title=T|after=[[B]]}}'
        self.assertEqual(fix(text).text, text)

    def test_succession_box_with_rows_before_needs_row(self):
        text = ('{{s-off}}\n{{succession box|before=Vacant|title=T|'
                'after=[[B]]}}')
        r = fix(text)
        self.assertEqual(
            r.text, '{{s-off}}\n|-\n{{s-vac}}\n{{s-ttl|title=T}}\n'
            '{{s-aft|after=[[B]]}}')

    def test_s_ttl_with(self):
        import mwparserfromhell as mwp
        r = fix('{{s-ttl | title = [[Foobar]] <br />with John Smith '
                '| years = 1990}}')
        tpl = mwp.parse(r.text).filter_templates()[0]
        self.assertEqual(str(tpl.get('title').value), ' [[Foobar]] ')
        self.assertEqual(str(tpl.get('with').value).strip(), 'John Smith')
        self.assertEqual(str(tpl.get('years').value).strip(), '1990')

    def test_nested(self):
        text = '{{Navbox|list1={{s-aft|after=Incumbent}}}}'
        self.assertEqual(fix(text).text, '{{Navbox|list1={{s-inc}}}}')

    def test_redirect_alias(self):
        r = Fixer(aliases={'succession after': 's-aft'}).fix(
            '{{Succession after|after=Incumbent}}')
        self.assertEqual(r.text, '{{S-inc}}')

    def test_unfixed_reported(self):
        r = fix('{{s-aft|after=Vacant until 1927}}')
        self.assertEqual(r.text, '{{s-aft|after=Vacant until 1927}}')
        self.assertEqual(len(r.unfixed), 1)

    def test_stray_empty_param(self):
        r = fix('{{succession box|before=New seat||title=T|after=[[B]]|}}')
        self.assertEqual(r.text, '{{s-new|seat}}\n{{s-ttl|title=T}}\n'
                         '{{s-aft|after=[[B]]}}')

    def test_see_created(self):
        r = fix('{{s-bef|before=See created}}')
        self.assertEqual(r.text, '{{s-new|diocese}}')

    def test_end_and_header_templates_start_rows(self):
        r = fix('{{S-aft|after=See dissolved}}\n{{End}}')
        self.assertEqual(r.text, '{{S-non|reason=See dissolved}}\n{{End}}')
        r = fix('{{s-aft|after=Vacant}}\n{{s-rel|ca}}')
        self.assertEqual(r.text, '{{s-vac}}\n{{s-rel|ca}}')

    def test_fixed_list_for_report(self):
        r = fix('{{s-aft|after=Incumbent}}\n'
                '{{succession box|before=New office|title=T|after=[[B]]}}\n'
                '{{s-bef|before=Vacant until 1927}}')
        self.assertEqual(r.fixed, [
            ('s-aft', 'after', 'Incumbent', '{{s-inc}}'),
            ('succession box', 'before', 'New office', '{{s-new|office}}'),
        ])
        self.assertEqual([u[:3] for u in r.unfixed],
                         [('s-bef', 'before', 'Vacant until 1927')])

    def test_report_single_page(self):
        stats = Counter({'pages checked': 2, 'pages the bot would edit': 1,
                         'values the bot would fix': 1,
                         'values that need a manual fix': 1,
                         'pages with values needing a manual fix': 1})
        data = ReportData(
            True, 'all', stats,
            fixed=[('B', 's-aft', 'after', 'Incumbent', '{{s-inc}}',
                    'would fix')],
            unfixed=[('A', 's-bef', 'before', 'x | y</nowiki>{{z}}',
                      'no safe pattern matched')])
        pages = build_report('User:Bot/Report', data)
        self.assertEqual(len(pages), 1)
        title, text = pages[0]
        self.assertEqual(title, 'User:Bot/Report')
        self.assertIn('~~~~~', text)
        self.assertIn('report only', text)
        self.assertIn('| [[:B]] || <nowiki>s-aft</nowiki>', text)
        self.assertIn('<code><nowiki>{{s-inc}}</nowiki></code>', text)
        # a closing nowiki inside a value must not end the nowiki early
        self.assertIn('x | y&lt;/nowiki>{{z}}</nowiki>', text)
        self.assertNotIn('Status', text)     # report-only has no status

    def test_report_splits_into_subpages(self):
        data = ReportData(
            False, 'all', Counter(),
            fixed=[(f'P{i:03}', 's-aft', 'after', 'Vacant', '{{s-vac}}',
                    'fixed') for i in range(25)],
            unfixed=[('Q', 's-aft', 'after', 'Vacant?', 'why')])
        pages = build_report('User:Bot/R', data, rows_per_page=10)
        titles = [t for t, _ in pages]
        self.assertEqual(titles, ['User:Bot/R', 'User:Bot/R/Bot fixes/1',
                                  'User:Bot/R/Bot fixes/2',
                                  'User:Bot/R/Bot fixes/3'])
        main = pages[0][1]
        self.assertIn('[[User:Bot/R/Bot fixes/3|Part 3]]', main)
        self.assertIn('| [[:Q]]', main)       # small section stays inline
        self.assertIn('Status', pages[1][1])
        self.assertEqual(pages[3][1].count('|-'), 5)

    def test_summary(self):
        r = fix('{{s-aft|after=Incumbent}}\n{{s-aft|after=Incumbent}}')
        self.assertIn('s-aft→s-inc ×2', make_summary(r.changes))


if __name__ == '__main__':
    unittest.main()
