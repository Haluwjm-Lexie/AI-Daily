"""Export curated, public-safe AI Daily data for GitHub Pages.
Do not publish a private SQLite DB, tokens, favorites, or full AIHOT API payloads.
"""
from pathlib import Path
from datetime import datetime
import json, os, importlib.util, shutil
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ai_daily_local',ROOT/'server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
SITE=ROOT/'site'; DATA=SITE/'data'


def clean_item(obj):
    if not isinstance(obj,dict):return None
    links=obj.get('links') or {}
    original=links.get('original') or obj.get('originalUrl') or obj.get('url') or ''
    if isinstance(original,dict):original=original.get('url','')
    aiurl=links.get('aihot') or ''
    if isinstance(aiurl,dict):aiurl=aiurl.get('url','')
    return {'title':str(obj.get('title') or obj.get('headline') or '')[:180],
            'summary':str(obj.get('summary') or obj.get('description') or '')[:260],
            'source':obj.get('source') if isinstance(obj.get('source'),dict) else {'name':str(obj.get('source') or '')[:80]},
            'links':{'original':server.safe_url(original),'aihot':server.safe_url(aiurl)},
            'id':str(obj.get('id') or obj.get('publicId') or '')[:100]}


def public_report(record):
    raw=record.get('payload',{});r=raw.get('report',raw)
    lead=r.get('lead') if isinstance(r.get('lead'),dict) else {}
    lead=clean_item(lead) if lead else {'title':str(record.get('headline') or '')[:180]}
    if lead:lead['leadParagraph']=str((r.get('lead') or {}).get('leadParagraph') or '')[:350]
    sections=[]
    for group in (r.get('sections') or [])[:9]:
        if not isinstance(group,dict):continue
        items=[clean_item(x) for x in (group.get('items') or group.get('stories') or [])[:6]]
        sections.append({'label':str(group.get('label') or group.get('title') or '资讯')[:60], 'items':[x for x in items if x and x['title']]})
    highlights=[clean_item(x) for x in (r.get('highlights') or [])[:6]]
    payload={'report':{'lead':lead, 'sections':sections, 'highlights':[x for x in highlights if x]}}
    return {'type':record['type'],'issue_key':record['issue_key'],'headline':record['headline'],'source_url':record.get('source_url',''), 'retrieved_at':record.get('retrieved_at',''),'payload':payload}


def restore_archive():
    """Rehydrate ephemeral Actions DB from already published, curated public data."""
    p=DATA/'export.json'
    if not p.exists():return
    try:old=json.loads(p.read_text('utf8'))
    except (OSError,ValueError):return
    for rec in old.get('reports',[]):
        try:server.save_report(rec['type'],rec['issue_key'],rec['payload'],rec.get('source_url',''))
        except (KeyError,TypeError,ValueError):pass
    with server.connect() as c:
        for key,record in (old.get('github_period') or {}).get('daily',{}).items():
            for rank,r in enumerate(record.get('repos') or [],1):
                if not r.get('repo'):continue
                c.execute('INSERT OR IGNORE INTO github_snapshots (period,observed_date,repo,rank,stars,description,description_zh,language,url,category) VALUES (?,?,?,?,?,?,?,?,?,?)',
                     ('daily',key,r['repo'],rank,r.get('stars'),r.get('description'),r.get('description_zh'),r.get('language'),r.get('url'),r.get('category')))
    print('Restored historical public report records and daily snapshots.')

def notify_once():
    if not server.FEISHU or not server.PUBLIC_URL:return
    key=server.sh_date();flag=DATA/'notifications.json'
    try:sent=json.loads(flag.read_text('utf8'))
    except (OSError,ValueError):sent={}
    report=server.get_report('daily',key) or server.get_report('daily')
    unique_key=report['issue_key'] if report else key
    if report and unique_key not in sent:
        result=server.send_feishu(report,force=True)
        if result.get('status')=='sent':
            sent[unique_key]=server.now().isoformat()
            flag.write_text(json.dumps(sent,ensure_ascii=False,indent=2),'utf8')
        print('Feishu daily result:',result)

def export(refresh=False,notify=False):
    DATA.mkdir(parents=True,exist_ok=True)
    restore_archive()
    if refresh:
        # Retry independently; never destroy existing exports when a source fails.
        for label,fn in [('AIHOT',server.sync_aihot),('GitHub',server.sync_github)]:
            try: print('Sync',label,fn())
            except Exception as exc:print('Sync warning',label,str(exc)[:220])
    with server.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT type,issue_key,headline,retrieved_at,source_url,payload FROM reports ORDER BY issue_key DESC LIMIT 500')]
    reports=[]
    for row in rows:
        try:row['payload']=json.loads(row['payload']);reports.append(public_report(row))
        except (TypeError,ValueError):continue
    garchive={};gperiod={}
    for period in ('daily','weekly','monthly','quarterly','yearly'):
        try:
            archive=server.github_archive(period)
            garchive[period]=archive
            per={}
            for r in archive[:150]:
                try:per[r['key']]=server.github_period(period,r['key'])
                except ValueError:pass
            gperiod[period]=per
        except Exception as exc:print('Github export warning',period,str(exc)[:140]);garchive[period]=[];gperiod[period]={}
    trend={}
    for p in ('monthly','quarterly','yearly'):
        try:trend[p]=server.trend_report(p)
        except Exception:pass
    public={'generated_at':server.now().isoformat(), 'reports':reports, 'github_archive':garchive,
            'github_period':gperiod,'trends':trend,'min_stars':server.GITHUB_MIN_STARS,
            'source_policy':'Selected titles and short summaries only; originals linked per item'}
    temp=DATA/'export.json.tmp';temp.write_text(json.dumps(public,ensure_ascii=False,separators=(',',':')),'utf8');temp.replace(DATA/'export.json')
    print('Published curated issues:',len(reports),'GitHub periods:',sum(len(x) for x in gperiod.values()))
    if notify:notify_once()

if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--refresh',action='store_true');a.add_argument('--notify',action='store_true');args=a.parse_args()
    export(args.refresh,args.notify)
