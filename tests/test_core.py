import os,sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.before=server.DB
        server.DB=Path(self.temp.name)/'test.sqlite3'
        server.connect().close()
    def tearDown(self):
        server.DB=self.before
        self.temp.cleanup()
    def test_deduplicates_by_upstream_id(self):
        p={'items':[{'id':'a','title':'One','source':{'name':'AIHOT'}},{'id':'a','title':'Updated','source':{'name':'AIHOT'}}]}
        self.assertEqual(server.save_items(p),2)
        with server.connect() as c:
            self.assertEqual(c.execute('select count(*) from items').fetchone()[0],1)
            self.assertEqual(c.execute('select title from items').fetchone()[0],'Updated')
    def test_report_persists_and_versions_by_date(self):
        report={'report':{'date':'2026-11-03','lead':{'title':'Verified','leadParagraph':'Fact'},'sections':[],'flashes':[]}}
        key=server.issue_from_report(report)
        self.assertEqual(key,'2026-11-03')
        server.save_report('daily',key,report,'https://aihot.news/api/v1/dailies/2026-11-03')
        server.save_report('daily',key,report,'https://aihot.news/api/v1/dailies/2026-11-03')
        with server.connect() as c:self.assertEqual(c.execute('select count(*) from reports').fetchone()[0],1)
        self.assertEqual(server.get_report('daily')['payload']['report']['lead']['title'],'Verified')
    def test_never_invents_date(self):
        self.assertIsNone(server.issue_from_report({'report':{'lead':{'title':'No date'}}}))
    def test_no_feishu_without_hook(self):
        old=server.FEISHU;server.FEISHU=''
        try:
            with self.assertRaises(ValueError):server.send_feishu({'issue_key':'2026-11-03'})
        finally:server.FEISHU=old
    def test_trending_parser(self):
        s='<article class="Box-row"><h2><a href="/owner/project">owner/project</a></h2></article>'
        self.assertEqual(server.parse_trending(s)[0]['repo'],'owner/project')
if __name__=='__main__':unittest.main()

class ExtendedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=server.DB
        self.preferences_original=server.PREFERENCES_PATH
        server.DB=Path(self.temp.name)/'archive.sqlite3'
        server.PREFERENCES_PATH=Path(self.temp.name)/'preferences.json'
        server.connect().close()
    def tearDown(self):
        server.DB=self.original
        server.PREFERENCES_PATH=self.preferences_original
        self.temp.cleanup()
    def test_preferences_persist(self):
        saved=server.save_preferences({'topics':['Agent','AI 模型'],'reading_mode':'compact'})
        self.assertEqual(saved['reading_mode'],'compact')
        self.assertEqual(server.load_preferences()['topics'],['Agent','AI 模型'])
    def test_empty_quarter_is_incomplete(self):
        r=server.trend_report('quarterly')
        self.assertEqual(r['status'],'partial')
        self.assertEqual(r['covered_days'],0)
        self.assertEqual(r['coverage'],0)
    def test_period_key_parsing(self):
        self.assertEqual(server.report_issue('weekly',{'report':{'week':'2026-W44'}}),'2026-W44')
        self.assertEqual(server.report_issue('monthly',{'report':{'month':'2026-10'}}),'2026-10')
    def test_translation_no_key_no_fake_translation(self):
        old=server.DEEPSEEK_KEY
        server.DEEPSEEK_KEY=''
        try:self.assertEqual(server.translate_github_batch([{'repo':'x/y','description':'tool'}]),{})
        finally:server.DEEPSEEK_KEY=old

class V04Tests(ExtendedTests):
    def test_previous_month_is_supported(self):
        r=server.trend_report('monthly')
        self.assertEqual(r['type'],'monthly')
        self.assertTrue(r['start']<r['end_exclusive'])
        self.assertEqual(r['status'],'partial')
    def test_github_period_requires_500_stars_and_snapshots(self):
        today=server.sh_date()
        with server.connect() as c:
            c.execute("INSERT INTO github_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",('daily',today,'one/good',1,760,'A useful agent project','智能体项目','Python','https://github.com/one/good','Agent'))
            c.execute("INSERT INTO github_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",('daily',today,'two/small',2,96,'Small project',None,'Python','https://github.com/two/small','Web'))
        r=server.github_period('daily')
        self.assertEqual(len(r['repos']),1)
        self.assertEqual(r['repos'][0]['repo'],'one/good')
    def test_categorizes_repository(self):
        self.assertEqual(server.categorize_repo('foo/bar','Agent orchestration toolkit'),'Agent')
        self.assertEqual(server.categorize_repo('foo/bar','UI website templates'),'Web')
    def test_github_star_requires_token(self):
        before=server.GITHUB_TOKEN
        try:
            server.GITHUB_TOKEN=''
            with self.assertRaises(ValueError):server.github_star('owner/repo')
        finally:server.GITHUB_TOKEN=before
