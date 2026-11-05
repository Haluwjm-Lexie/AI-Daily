import tempfile,unittest,sys,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class V07Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db=server.DB;self.old_backup=server.BACKUP_DIR;self.old_prefs=server.PREFERENCES_PATH
        server.DB=Path(self.tmp.name)/'data'/'daily.sqlite3'
        server.BACKUP_DIR=Path(self.tmp.name)/'data'/'backups'
        server.PREFERENCES_PATH=Path(self.tmp.name)/'data'/'preferences.json'
        server.connect().close()
    def tearDown(self):
        server.DB=self.old_db;server.BACKUP_DIR=self.old_backup;server.PREFERENCES_PATH=self.old_prefs
        self.tmp.cleanup()
    def test_original_publication_is_html_url(self):
        self.assertEqual(server.human_report_url('daily','2026-11-05'), 'https://aihot.news/daily/2026-11-05')
        self.assertNotIn('/api/',server.human_report_url('weekly','2026-W44'))
    def test_old_json_source_is_rewritten_when_read(self):
        d={'report':{'date':'2026-11-05','lead':{'title':'Real source headline'}}}
        server.save_report('daily','2026-11-05',d,'https://aihot.news/api/v1/dailies/2026-11-05')
        row=server.get_report('daily')
        self.assertEqual(row['source_url'],'https://aihot.news/daily/2026-11-05')
        self.assertEqual(row['headline'],'Real source headline')
    def test_restart_preserves_archives_and_backup(self):
        d={'report':{'date':'2026-11-03','lead':{'title':'Some headline'}}}
        server.save_report('daily','2026-11-03',d,'https://aihot.news/daily/2026-11-03')
        server.create_backup()
        backups=list(server.BACKUP_DIR.glob('daily-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as c:self.assertEqual(c.execute('select count(*) from reports').fetchone()[0],1)
        server.connect().close()
        self.assertEqual(server.get_report('daily')['issue_key'],'2026-11-03')
    def test_github_fallback_latest_archived_day(self):
        with server.connect() as c:
            c.execute('INSERT INTO github_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)',('daily','2026-11-03','owner/repo',1,800,'Test','测试','Python','https://github.com/owner/repo','Agent'))
        data=server.github_period('daily')
        self.assertTrue(data['historical_fallback'])
        self.assertEqual(data['start'],'2026-11-03')
        self.assertEqual(data['repos'][0]['repo'],'owner/repo')
if __name__=='__main__':unittest.main()
