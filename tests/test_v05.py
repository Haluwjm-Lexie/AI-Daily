import sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=server.DB
        server.DB=Path(self.tmp.name)/'archive.sqlite3';server.connect().close()
        with server.connect() as c:
            for date_,rank,repo in [('2026-10-27',1,'example/agent'),('2026-10-28',2,'example/agent'),('2026-11-03',1,'example/new')]:
                c.execute('INSERT INTO github_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',('daily',date_,repo,rank,900,'Agent',None,'Python','https://github.com/'+repo,'Agent'))
    def tearDown(self):server.DB=self.old;self.tmp.cleanup()
    def test_archive_daily_groups_actual_observation_dates(self):
        keys=[x['key'] for x in server.github_archive('daily')]
        self.assertEqual(keys,['2026-11-03','2026-10-28','2026-10-27'])
    def test_archive_weekly_groups_iso_weeks(self):
        r=server.github_archive('weekly')
        self.assertEqual({x['key'] for x in r},{'2026-W44','2026-W45'})
    def test_archive_monthly_groups_calendar_months(self):
        self.assertEqual([x['key'] for x in server.github_archive('monthly')],['2026-11','2026-10'])
    def test_past_day_does_not_show_future_trending_projects(self):
        r=server.github_period('daily','2026-10-27')
        self.assertEqual([x['repo'] for x in r['repos']],['example/agent'])
        self.assertEqual(r['end'],'2026-10-27')
    def test_missing_archive_period_does_not_invent_results(self):
        with self.assertRaises(ValueError):server.github_period('daily','2025-01-01')
if __name__=='__main__':unittest.main()
