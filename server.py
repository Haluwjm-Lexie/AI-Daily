"""AI Daily — personal, read-only AIHOT client, SQLite archive, Feishu notifier.
Python 3.10+, standard library only. No pretend AI generations.
"""
import os, sys, json, sqlite3, threading, time, re, html, urllib.request, urllib.error, collections, calendar, shutil
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
TZ=ZoneInfo('Asia/Shanghai')
DATA_DIR=Path(os.getenv('DAILY_DATA_DIR',str(ROOT/'data'))).expanduser()
DB=Path(os.getenv('DAILY_DB',str(DATA_DIR/'daily.sqlite3')))
BACKUP_DIR=DATA_DIR/'backups'
AIHOT=os.getenv('AIHOT_BASE','https://aihot.news').rstrip('/')
PORT=int(os.getenv('PORT','3218'))
HOST=os.getenv('HOST','127.0.0.1')
FEISHU=os.getenv('FEISHU_WEBHOOK_URL','')
DEEPSEEK_KEY=os.getenv('DEEPSEEK_API_KEY','')
DEEPSEEK_MODEL=os.getenv('DEEPSEEK_MODEL','deepseek-chat')
PUBLIC_URL=os.getenv('PUBLIC_URL','').rstrip('/')
GITHUB_TOKEN=os.getenv('GITHUB_TOKEN','').strip()
GITHUB_REPO_URL=os.getenv('GITHUB_REPO_URL','').strip()
GITHUB_MIN_STARS=int(os.getenv('GITHUB_MIN_STARS','500'))
SYNC_INTERVAL=int(os.getenv('SYNC_INTERVAL_SECONDS','3600'))
LOCK=threading.RLock()
PREFERENCES_PATH=DATA_DIR/'preferences.json'
DEFAULT_PREFERENCES={"topics":["AI 模型","Agent","AI 编程","开源","产品发布"],"reading_mode":"standard","translate_github":False}
LAST_SYNC={'status':'not_started','at':None,'error':None}

def now():return datetime.now(TZ)
def sh_date():return now().date().isoformat()
def yesterday():return (now().date()-timedelta(days=1)).isoformat()
def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB,timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS reports(
      type TEXT NOT NULL, issue_key TEXT NOT NULL, headline TEXT, payload TEXT NOT NULL,
      source_url TEXT NOT NULL, retrieved_at TEXT NOT NULL, PRIMARY KEY(type,issue_key));
      CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,title TEXT NOT NULL,summary TEXT,
      url TEXT,source TEXT,published_at TEXT,retrieved_at TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT NOT NULL,
      detail TEXT,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS favorites(kind TEXT NOT NULL,ref_id TEXT NOT NULL,title TEXT NOT NULL,url TEXT,created_at TEXT NOT NULL,PRIMARY KEY(kind,ref_id));
      CREATE TABLE IF NOT EXISTS github_entries(repo TEXT PRIMARY KEY,description TEXT,stars INTEGER,
      language TEXT,url TEXT,updated_at TEXT NOT NULL);
    ''')
    if not any(x[1]=='description_zh' for x in c.execute('PRAGMA table_info(github_entries)').fetchall()):c.execute('ALTER TABLE github_entries ADD COLUMN description_zh TEXT')
    c.executescript('''CREATE TABLE IF NOT EXISTS github_snapshots(
      period TEXT NOT NULL, observed_date TEXT NOT NULL, repo TEXT NOT NULL,
      rank INTEGER NOT NULL, stars INTEGER, description TEXT, description_zh TEXT,
      language TEXT, url TEXT, category TEXT,
      PRIMARY KEY(period,observed_date,repo));
      CREATE INDEX IF NOT EXISTS idx_github_snapshots_period ON github_snapshots(period,observed_date);
    ''')
    c.commit();return c

def get_json(url,timeout=18):
    if not url.startswith('https://'):raise ValueError('HTTPS required')
    req=urllib.request.Request(url,headers={'User-Agent':'aihot-api/2.0.0 aihot-actor/94cf4de3-832a-439c-a9e6-16e6a2f1bb76','Accept':'application/json','Accept-Encoding':'identity'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        if r.status!=200: raise RuntimeError(f'HTTP {r.status}')
        if int(r.headers.get('Content-Length','0'))>3_000_000: raise ValueError('response too large')
        raw=r.read(3_000_001)
        if len(raw)>3_000_000:raise ValueError('response too large')
        return json.loads(raw)

def safe_url(x):
    if not isinstance(x,str):return ''
    p=urlparse(x)
    return x if p.scheme=='https' and p.hostname else ''

def issue_from_report(d):
    if not isinstance(d,dict):return None
    rep=d.get('report',d)
    if not isinstance(rep,dict):return None
    for k in ('date','issueDate','day','publishedOn','periodStart'):
        v=rep.get(k)
        if isinstance(v,str) and re.match(r'^\d{4}-\d{2}-\d{2}',v):return v[:10]
    return None

def save_report(kind,key,payload,source):
    if not key or not isinstance(payload,dict):raise ValueError('invalid report')
    report=payload.get('report',payload)
    headline=(report.get('lead') or {}).get('title') if isinstance(report.get('lead'),dict) else None
    headline=headline or report.get('headline') or report.get('title') or f'{kind} · {key}'
    with LOCK:
        with connect() as c:c.execute('INSERT INTO reports VALUES (?,?,?,?,?,?) ON CONFLICT(type,issue_key) DO UPDATE SET payload=excluded.payload,headline=excluded.headline,retrieved_at=excluded.retrieved_at',
        (kind,key,str(headline),json.dumps(payload,ensure_ascii=False),source,now().isoformat()))

def get_report(kind,key=None):
    with connect() as c:
        row=c.execute('SELECT * FROM reports WHERE type=? '+('AND issue_key=?' if key else 'ORDER BY issue_key DESC LIMIT 1'),(kind,key) if key else (kind,)).fetchone()
    if not row:return None
    d=dict(row);d['payload']=json.loads(d['payload']);d['source_url']=human_report_url(kind,d['issue_key'],d['payload']);return d

def normalize_item(item):
    if not isinstance(item,dict):return None
    iid=item.get('id');title=item.get('title')
    if not iid or not title:return None
    links=item.get('links') or {}
    origin=item.get('source') or {}
    u=links.get('original') or links.get('aihot') or item.get('url') or ''
    if isinstance(u,dict):u=u.get('url','')
    return {'id':str(iid),'title':str(title),'summary':item.get('summary') or item.get('description') or '',
      'url':safe_url(u),'source':origin.get('name','AIHOT') if isinstance(origin,dict) else str(origin),
      'published_at':item.get('publishedAt') or item.get('discoveredAt'), 'payload':item}

def save_items(payload):
    items=payload.get('items',[]) if isinstance(payload,dict) else []
    count=0
    with LOCK:
      with connect() as c:
        for raw in items:
          i=normalize_item(raw)
          if not i:continue
          c.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,summary=excluded.summary,url=excluded.url,source=excluded.source,published_at=excluded.published_at,payload=excluded.payload',
            (i['id'],i['title'],i['summary'],i['url'],i['source'],i['published_at'],now().isoformat(),json.dumps(raw,ensure_ascii=False)))
          count+=1
    return count

def report_endpoint(kind):
    return {'daily':'dailies','weekly':'weeklies','monthly':'monthlies'}[kind]

def report_issue(kind, payload):
    if kind=='daily':return issue_from_report(payload)
    rep=payload.get('report',payload)
    if not isinstance(rep,dict):return None
    for field in ('week','weekKey','isoWeek','month','monthKey','periodKey','key','issueKey'):
        val=rep.get(field)
        if isinstance(val,str):
            if kind=='weekly' and re.fullmatch(r'\d{4}-W\d{2}',val):return val
            if kind=='monthly' and re.fullmatch(r'\d{4}-\d{2}',val):return val
    dt=issue_from_report(payload)
    if dt:
        d=date.fromisoformat(dt)
        return f'{d.isocalendar().year}-W{d.isocalendar().week:02d}' if kind=='weekly' else dt[:7]
    return None

def human_report_url(kind,key,payload=None):
    """Canonical human-readable edition, never an API JSON endpoint."""
    report=(payload or {}).get('report',payload or {})
    links=report.get('links',{}) if isinstance(report,dict) else {}
    if isinstance(links,dict):
        u=links.get('aihot') or links.get('public')
        if safe_url(u) and '/api/' not in u:return u
    route={'daily':'daily','weekly':'weekly','monthly':'monthly'}[kind]
    return f'{AIHOT}/{route}/{key}'

def create_backup():
    """Copy live SQLite DB into data/backups via sqlite backup API; never clear archives."""
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    if DB.exists() and DB.stat().st_size:
        target=BACKUP_DIR/('daily-'+now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
        with sqlite3.connect(DB) as src, sqlite3.connect(target) as dst:src.backup(dst)
        for old in sorted(BACKUP_DIR.glob('daily-*.sqlite3'),reverse=True)[14:]:old.unlink()
    if PREFERENCES_PATH.exists():
        shutil.copy2(PREFERENCES_PATH,BACKUP_DIR/'preferences-latest.json')

def sync_report_kind(kind):
    payload=get_json(AIHOT+'/api/v1/'+report_endpoint(kind)+'/latest')
    key=report_issue(kind,payload)
    if not key:raise ValueError(kind+' report key absent, cannot save')
    save_report(kind,key,payload, human_report_url(kind,key,payload))
    return key

def sync_aihot():
    global LAST_SYNC
    try:
      # One public daily request and one recent selected-items request; no bulk mirroring.
      key=sync_report_kind('daily')
      items=get_json(AIHOT+'/api/v1/items?mode=selected&window=7d&limit=100')
      count=save_items(items)
      extras={}
      for kind in ('weekly','monthly'):
        try:extras[kind]=sync_report_kind(kind)
        except Exception as ex:extras[kind+'_error']=str(ex)[:120]
      LAST_SYNC={'extras':extras,'status':'ok','at':now().isoformat(),'error':None,'items_processed':count,'report_date':key}
      return LAST_SYNC
    except Exception as e:
      LAST_SYNC={'status':'error','at':now().isoformat(),'error':str(e)[:250]}
      raise

def load_preferences():
    try:
        data=json.loads(PREFERENCES_PATH.read_text('utf8'))
        return {'topics':[str(x)[:32] for x in data.get('topics',[]) if isinstance(x,str)][:16], 'reading_mode':data.get('reading_mode','standard') if data.get('reading_mode') in ('standard','compact') else 'standard', 'translate_github':bool(data.get('translate_github',False))}
    except (ValueError, OSError, TypeError):return dict(DEFAULT_PREFERENCES)

def save_preferences(data):
    prefs={'topics':[str(x).strip()[:32] for x in data.get('topics',[]) if isinstance(x,str) and x.strip()][:16], 'reading_mode':data.get('reading_mode','standard') if data.get('reading_mode') in ('standard','compact') else 'standard','translate_github':bool(data.get('translate_github',False))}
    PREFERENCES_PATH.parent.mkdir(exist_ok=True,parents=True)
    tmp=PREFERENCES_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(prefs,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(PREFERENCES_PATH)
    return prefs

def get_favorites():
    with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM favorites ORDER BY created_at DESC LIMIT 500')]

def trend_report(kind):
    if kind not in ('monthly','quarterly','yearly'):raise ValueError('unsupported period')
    today=now().date()
    if kind=='monthly':
        current=date(today.year,today.month,1);end=current;start=(current-timedelta(days=1)).replace(day=1);key=start.strftime('%Y-%m')
    elif kind=='quarterly':
        y=today.year; q=(today.month-1)//3
        if q==0:y-=1;q=4
        start=date(y,(q-1)*3+1,1)
        end=date(y+1,1,1) if q==4 else date(y,q*3+1,1)
        key=f'{y}-Q{q}'
    else:
        y=today.year-1;start=date(y,1,1);end=date(y+1,1,1);key=str(y)
    with connect() as c:
        reports=[dict(r) for r in c.execute('SELECT issue_key,headline,payload FROM reports WHERE type="daily" AND issue_key>=? AND issue_key<? ORDER BY issue_key',(start.isoformat(),end.isoformat()))]
    total=(end-start).days
    # Deliberately count only existing records. Do not fabricate a full historical summary.
    topics=collections.Counter()
    events=[]
    for rr in reports:
        payload=json.loads(rr['payload']);rep=payload.get('report',payload)
        if not isinstance(rep,dict):continue
        lead=rep.get('lead') or {}
        title=lead.get('title') if isinstance(lead,dict) else ''
        if title:events.append({'date':rr['issue_key'],'title':title})
        for sec in rep.get('sections',[]) or []:
            if not isinstance(sec,dict):continue
            label=sec.get('label') or sec.get('name') or '其他'
            topics[str(label)]+=len(sec.get('items',[]) or [])
    result={'type':kind,'issue_key':key,'start':start.isoformat(),'end_exclusive':end.isoformat(),'covered_days':len(reports),'total_days':total,'coverage':round(100*len(reports)/total,1),'topics':topics.most_common(12),'events':events[:100],'status':'partial' if len(reports)!=total else 'complete','note':'基于本地已保存的日报事件统计；仅反映归档覆盖，不代表整个 AI 行业。'}
    return result

def parse_trending(htmltext):
    # GitHub Trending is an HTML page, without a supported official Trending API.
    # Never silently label fallback Github search results as Trending.
    block=re.findall(r'<article[^>]+class="[^"]*Box-row[^>]*"[^>]*>(.*?)</article>',htmltext,re.S|re.I)
    output=[]
    for b in block:
      m=re.search(r'href="(/[^/\"\s]+/[^/\"\s?#]+)"',b)
      if not m:continue
      repo=html.unescape(m.group(1).strip('/'))
      if '/' not in repo:continue
      txt=re.sub(r'<[^>]+>',' ',b);txt=html.unescape(re.sub(r'\s+',' ',txt)).strip()
      output.append({'repo':repo,'description':txt[:230],'url':'https://github.com/'+repo,'stars':None,'language':''})
    return output[:15]

def translate_github_batch(entries):
    """Optional real LLM translation. No key means no fabricated translations."""
    if not DEEPSEEK_KEY:return {}
    source=[{'repo':x['repo'],'description':x['description'][:220]} for x in entries if x['description']]
    if not source:return {}
    prompt='请将以下 GitHub 项目的英文简介准确翻译为简明中文，不要编造功能。输出严格 JSON 对象，键是 repo，值是中文翻译，不要添加 Markdown。\n'+json.dumps(source,ensure_ascii=False)
    body=json.dumps({'model':DEEPSEEK_MODEL,'messages':[{'role':'system','content':'你是技术开源项目翻译助手。仅翻译所给内容，不添加事实。'},{'role':'user','content':prompt}],'temperature':0,'response_format':{'type':'json_object'}},ensure_ascii=False).encode()
    req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=body,method='POST',headers={'Authorization':'Bearer '+DEEPSEEK_KEY,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:result=json.loads(r.read(200000))
    content=result['choices'][0]['message']['content']
    values=json.loads(content)
    return {str(k):str(v)[:350] for k,v in values.items() if isinstance(v,str)} if isinstance(values,dict) else {}

def github_metadata(repo):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):return {}
    headers={'Accept':'application/vnd.github+json','User-Agent':'AI-Daily-Personal/0.7','X-GitHub-Api-Version':'2022-11-28'}
    # Public metadata needs no account credentials; PAT scopes can cause 403 here.
    req=urllib.request.Request('https://api.github.com/repos/'+repo,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=12) as resp:return json.loads(resp.read(120000))
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError):return {}

def categorize_repo(repo,description,topics=None):
    text=' '.join([repo,description,' '.join(topics or [])]).lower()
    rules=[('Agent',r'agent|multi.agent|autogen|langgraph|crew|orchestr'),
           ('Skill',r'skill|plugin|extension|mcp'),
           ('AI 编程',r'coding|code assistant|copilot|developer|cursor|terminal'),
           ('模型',r'model|llm|inference|transformer|diffusion|embedding'),
           ('Web',r'web|next.js|react|frontend|browser|website'),
           ('自动化',r'workflow|automation|n8n|pipeline'),
           ('数据与 RAG',r'rag|retriev|vector|database')]
    for name,pattern in rules:
        if re.search(pattern,text):return name
    return '其他'

def github_time_window(period):
    t=now().date()
    if period=='daily':return t.isoformat(),t.isoformat()
    if period=='weekly':return (t-timedelta(days=6)).isoformat(),t.isoformat()
    if period=='monthly':return (t.replace(day=1)-timedelta(days=1)).replace(day=1).isoformat(),t.replace(day=1).isoformat()
    if period=='quarterly':
        q=(t.month-1)//3;year=t.year-(1 if q==0 else 0);q=4 if q==0 else q
        return date(year,(q-1)*3+1,1).isoformat(),(date(year+1,1,1) if q==4 else date(year,q*3+1,1)).isoformat()
    return date(t.year-1,1,1).isoformat(),date(t.year,1,1).isoformat()

def github_period(period,key=None):
    if period not in ('daily','weekly','monthly','quarterly','yearly'):raise ValueError('unknown period')
    if key:
        start,end_exclusive=github_historic_window(period,key)
    else:
        start,end=github_time_window(period)
        end_exclusive=(date.fromisoformat(end)+timedelta(days=1)).isoformat() if period in ('daily','weekly') else end
        # On restart or before first sync, show latest truly archived daily snapshot;
        # never overwrite the archive or invent that it is today's Trending.
        if period=='daily':
            with connect() as c:
                exists=c.execute('SELECT 1 FROM github_snapshots WHERE observed_date>=? AND observed_date<? LIMIT 1',(start,end_exclusive)).fetchone()
                last=c.execute('SELECT MAX(observed_date) FROM github_snapshots').fetchone()[0]
            if not exists and last:
                start=last;end_exclusive=(date.fromisoformat(last)+timedelta(days=1)).isoformat()
    with connect() as c:
        rows=[dict(x) for x in c.execute('''SELECT repo,COALESCE(MAX(stars),(SELECT stars FROM github_entries e WHERE e.repo=github_snapshots.repo)) AS stars,MAX(description) AS description,
             COALESCE(MAX(description_zh),(SELECT description_zh FROM github_entries e WHERE e.repo=github_snapshots.repo)) AS description_zh,MAX(language) AS language,MAX(url) AS url,
             MAX(category) AS category,COUNT(DISTINCT observed_date) AS appearances,MIN(rank) AS best_rank
             FROM github_snapshots WHERE observed_date>=? AND observed_date<? AND period IN ('daily','weekly','monthly')
             GROUP BY repo ORDER BY appearances DESC,best_rank ASC LIMIT 40''',(start,end_exclusive))]
    # Periodic lists show observation-based rankings, not claims about GitHub's official quarterly/yearly trends.
    return {'repos':[r for r in rows if (r['stars'] or 0)>=GITHUB_MIN_STARS][:20],
            'period':period,'start':start,'end':(date.fromisoformat(end_exclusive)-timedelta(days=1)).isoformat(),'archive_key':key,'minimum_stars':GITHUB_MIN_STARS,
            'method':'GitHub Trending daily/weekly/monthly snapshots; quarterly/yearly based on archived observations',
            'observed_only':period in ('quarterly','yearly'),'historical_fallback':period=='daily' and not key and start!=sh_date()}

def github_archive(period):
    """Observed GitHub Trending snapshots only; no invented historic rankings."""
    if period not in ('daily','weekly','monthly','quarterly','yearly'):
        raise ValueError('invalid period')
    with connect() as c:
        days=[r[0] for r in c.execute('SELECT DISTINCT observed_date FROM github_snapshots ORDER BY observed_date DESC')]
    result={}
    for value in days:
        try:d=date.fromisoformat(value)
        except ValueError:continue
        iso=d.isocalendar()
        if period=='daily':key=value;start=d;end=d+timedelta(days=1)
        elif period=='weekly':key=f'{iso.year}-W{iso.week:02d}';start=d-timedelta(days=d.weekday());end=start+timedelta(days=7)
        elif period=='monthly':key=d.strftime('%Y-%m');start=d.replace(day=1);end=date(d.year+1,1,1) if d.month==12 else date(d.year,d.month+1,1)
        elif period=='quarterly':q=(d.month-1)//3;key=f'{d.year}-Q{q+1}';start=date(d.year,q*3+1,1);end=date(d.year+1,1,1) if q==3 else date(d.year,q*3+4,1)
        else:key=str(d.year);start=date(d.year,1,1);end=date(d.year+1,1,1)
        if key not in result:result[key]={'key':key,'start':start.isoformat(),'end_exclusive':end.isoformat(),'snapshot_days':0}
        result[key]['snapshot_days']+=1
    issues=list(result.values())[:150]
    with connect() as c:
      for issue in issues:
        # One-line Chinese editorial subject based on the actual category mix.
        # Never use opaque repository names as a meaningless headline.
        category_rows=c.execute('''SELECT COALESCE(NULLIF(TRIM(category), ''),'其他') category,
                    COUNT(DISTINCT repo) n FROM github_snapshots
                    WHERE observed_date>=? AND observed_date<?
                    GROUP BY category ORDER BY n DESC,category ASC LIMIT 3''',
                    (issue['start'],issue['end_exclusive'])).fetchall()
        labels={'Agent':'智能体','AI Agent':'智能体','Skill':'技能工具','Skills':'技能工具',
                'Web':'Web 开发','AI 编程':'AI 编程','AI Coding':'AI 编程',
                'Developer Tools':'开发者工具','Tools':'开发者工具','LLM':'大模型',
                'Model':'大模型','RAG':'知识检索','Data':'数据工具',
                'Infrastructure':'基础设施','其他':'开源工具'}
        topics=[]
        for cat,n in category_rows:
          label=labels.get(str(cat),str(cat) if re.fullmatch(r'[\u4e00-\u9fff ]{2,9}',str(cat)) else '开源工具')
          if label not in topics:topics.append(label)
          if len(topics)==2:break
        issue['headline']='、'.join(topics)+'项目上榜' if topics else '暂无已归档的热门项目'
    return issues

def github_historic_window(period,key):
    for row in github_archive(period):
        if row['key']==key:return row['start'],row['end_exclusive']
    raise ValueError('所选历史周期暂无真实快照')

def github_star(repo, remove=False):
    if not GITHUB_TOKEN:raise ValueError('未配置 GitHub 授权令牌，暂不能同步 Star；可以点击仓库名称前往 GitHub')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('仓库名称不正确')
    headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+GITHUB_TOKEN,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'AI-Daily-Personal/0.4'}
    req=urllib.request.Request('https://api.github.com/user/starred/'+repo,data=None if remove else b'',headers=headers,method='DELETE' if remove else 'PUT')
    try:
        with urllib.request.urlopen(req,timeout=13) as r:
            if r.status!=204:raise RuntimeError('GitHub 未确认'+('取消 Star' if remove else 'Star')+'成功')
    except urllib.error.HTTPError as e:
        # Read GitHub's structured error rather than hiding the cause behind HTTP 403.
        # Never include Authorization, cookies, raw request headers or API keys.
        try:
            detail=json.loads(e.read(8192).decode('utf-8','replace'))
        except (ValueError,UnicodeError,AttributeError):
            detail={}
        message=str(detail.get('message') or 'GitHub 没有提供具体错误说明') if isinstance(detail,dict) else 'GitHub 没有提供具体错误说明'
        # Avoid reflecting arbitrary tokens that an upstream error may echo.
        message=re.sub(r'github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+', '[已隐藏的令牌]', message)
        message=message[:260]
        if e.code==403:
            remaining=e.headers.get('X-RateLimit-Remaining','')
            if remaining=='0':
                suggestion='GitHub API 额度已用完；稍后再尝试。'
            elif 'secondary rate limit' in message.lower() or 'abuse detection' in message.lower():
                suggestion='触发 GitHub 次级限流；请暂时停止重复点击。'
            elif 'resource not accessible' in message.lower() or 'permission' in message.lower():
                suggestion='请检查 Token 对目标仓库的 Metadata（读取）和账户 Starring（写入）权限。'
            else:
                suggestion='请先根据 GitHub 返回的原因排查；不要直接扩大 Token 权限。'
        elif e.code==401:
            suggestion='Token 无效或已失效；确认 .env 里的令牌正确，再重启程序。'
        elif e.code==404:
            suggestion='仓库可能不存在，或 Token 无法访问该仓库。'
        else:
            suggestion='检查 GitHub API 返回内容。'
        request_id=e.headers.get('X-GitHub-Request-Id','')
        request_id=re.sub(r'[^A-Za-z0-9:-]','',request_id)[:64]
        extra=(' | GitHub 请求编号：'+request_id) if request_id else ''
        raise ValueError(f'GitHub '+('取消 Star' if remove else 'Star')+f' 失败：HTTP {e.code} | GitHub 原因：{message} | {suggestion}{extra}') from None
    except urllib.error.URLError as e:
        raise ValueError('无法连接 GitHub API，请检查网络或代理设置。') from None
    return {'status':'unstarred' if remove else 'starred','repo':repo}

def github_starred(repo):
    if not GITHUB_TOKEN: return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):return None
    headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+GITHUB_TOKEN,'User-Agent':'AI-Daily-Personal/0.7','X-GitHub-Api-Version':'2022-11-28'}
    req=urllib.request.Request('https://api.github.com/user/starred/'+repo,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=10) as resp:return resp.status==204
    except urllib.error.HTTPError as e:
        if e.code==404:return False
        return None
    except (urllib.error.URLError,TimeoutError):return None

def sync_github():
    """Capture real Trending snapshots for daily/weekly/monthly and add verified repository metadata."""
    total={};today=sh_date()
    for period in ('daily','weekly','monthly'):
        request=urllib.request.Request('https://github.com/trending?since='+period,headers={'User-Agent':'Mozilla/5.0 (compatible; AI-Daily/0.4)','Accept':'text/html'})
        with urllib.request.urlopen(request,timeout=22) as resp:raw=resp.read(1_500_000).decode('utf8','replace')
        entries=parse_trending(raw)
        if not entries:raise ValueError('GitHub '+period+' 榜单解析失败：已保存快照不删除')
        if period=='daily':
            # GitHub REST metadata enhances totals/languages and gives a grounded popularity threshold.
            for x in entries:
                metadata=github_metadata(x['repo'])
                if metadata:
                    x['stars']=metadata.get('stargazers_count')
                    x['description']=metadata.get('description') or x['description']
                    x['language']=metadata.get('language') or ''
                    x['category']=categorize_repo(x['repo'],x['description'],metadata.get('topics'))
                else:x['category']=categorize_repo(x['repo'],x['description'])
            translations={}
            if DEEPSEEK_KEY:
                try:translations=translate_github_batch(entries)
                except Exception as e:print('[github translate]',str(e)[:100],file=sys.stderr)
            with connect() as c:
                old={r['repo']:r['description_zh'] for r in c.execute('SELECT repo,description_zh FROM github_entries')}
                for i,x in enumerate(entries):
                    zh=translations.get(x['repo']) or old.get(x['repo'])
                    x['description_zh']=zh
                    c.execute("""INSERT INTO github_entries(repo,description,stars,language,url,updated_at,description_zh)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(repo) DO UPDATE SET description=excluded.description,stars=excluded.stars,
                    language=excluded.language,url=excluded.url,updated_at=excluded.updated_at,
                    description_zh=COALESCE(excluded.description_zh,github_entries.description_zh)""",
                    (x['repo'],x['description'],x['stars'],x['language'],x['url'],now().isoformat(),zh))
        with connect() as c:
            for i,x in enumerate(entries):
                c.execute("""INSERT OR REPLACE INTO github_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (period,today,x['repo'],i+1,x.get('stars'),x.get('description'),x.get('description_zh'),x.get('language'),x['url'],x.get('category') or categorize_repo(x['repo'],x.get('description',''))))
        total[period]=len(entries)
    return {'counts':total,'at':now().isoformat(),'minimum_stars':GITHUB_MIN_STARS}

def feishu_payload(report):
    """Readable Feishu card with grounded recommendations and original links.
    PUBLIC_URL links to our own edition; the original belongs to the publisher.
    """
    key=str(report.get('issue_key') or '')
    raw=report.get('payload') or {}
    data=raw.get('report',raw) if isinstance(raw,dict) else {}
    if not isinstance(data,dict):data={}
    lead=data.get('lead') if isinstance(data.get('lead'),dict) else {}
    title=str(lead.get('title') or report.get('headline') or '本期 AI 资讯')[:170]
    summary=re.sub(r'\s+',' ',str(lead.get('leadParagraph') or lead.get('summary') or data.get('summary') or '').strip())[:290]
    highlights=[]
    for section in data.get('sections') or []:
      if not isinstance(section,dict):continue
      for item in (section.get('items') or [])[:8]:
        if not isinstance(item,dict):continue
        t=str(item.get('title') or '').strip()
        if t and t!=title and t not in highlights:highlights.append(t[:110])
        if len(highlights)>=3:break
      if len(highlights)>=3:break
    lines=['**今日头条**',title]
    if summary:lines+=['',summary]
    if highlights:lines+=['','**其他重点**']+['• '+x for x in highlights]
    leadlinks=lead.get('links') if isinstance(lead.get('links'),dict) else {}
    orig=safe_url(leadlinks.get('original') or lead.get('originalUrl') or '')
    # No fabricated public link: local 127.0.0.1 is not a reader-accessible URL.
    public=PUBLIC_URL if safe_url(PUBLIC_URL) and urlparse(PUBLIC_URL).hostname not in ('127.0.0.1','localhost') else ''
    recommendation='帮助你快速把握本期模型、Agent 与开发工具的重要变化。'
    elements=[{'tag':'markdown','content':'\n'.join(lines)},
              {'tag':'markdown','content':"<font color='grey'>**推荐理由**："+recommendation+"</font>",
               'text_size':'notation'}]
    if public:
      target=public+'/?view=daily'
      elements.append({'tag':'button','text':{'tag':'plain_text','content':'在 AI Daily 阅读完整日报'},
                       'type':'primary','width':'default','size':'medium',
                       'behaviors':[{'type':'open_url','default_url':target}]})
    if orig:
      elements.append({'tag':'button','text':{'tag':'plain_text','content':'阅读头条原文'},
                       'type':'default','width':'default','size':'medium',
                       'behaviors':[{'type':'open_url','default_url':orig}]})
    card={'schema':'2.0',
      'header':{'title':{'tag':'plain_text','content':'AI Daily｜'+key+' AI 日报'},'template':'turquoise'},
      'body':{'elements':elements}}
    return {'msg_type':'interactive','card':card}

def send_feishu(report, force=False):
    if not FEISHU:raise ValueError('未配置 FEISHU_WEBHOOK_URL')
    if not safe_url(FEISHU) or not urlparse(FEISHU).hostname.endswith('.feishu.cn'):
      raise ValueError('飞书 Webhook 必须是有效的飞书 HTTPS 地址')
    if not report:raise ValueError('没有真实日报，不发送成功提醒')
    jid='feishu-'+sh_date()+'-'+report['issue_key']
    with LOCK:
      with connect() as c:
        row=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
        if row and row['status']=='sent' and not force:return {'status':'already_sent'}
        c.execute('INSERT INTO jobs VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at', (jid,'sending','',now().isoformat()))
    try:
      body=json.dumps(feishu_payload(report),ensure_ascii=False).encode()
      req=urllib.request.Request(FEISHU,data=body,headers={'Content-Type':'application/json'},method='POST')
      with urllib.request.urlopen(req,timeout=12) as resp:data=json.loads(resp.read(10000))
      if data.get('code',data.get('StatusCode',-1))!=0:raise RuntimeError('Feishu rejected request: '+str(data.get('msg',data))[:150])
      status='sent'
    except Exception as ex:
      status='failed';error=str(ex)[:200]
      with connect() as c:c.execute('UPDATE jobs SET status=?,detail=?,updated_at=? WHERE id=?',(status,error,now().isoformat(),jid))
      raise
    with connect() as c:c.execute('UPDATE jobs SET status=?,detail=?,updated_at=? WHERE id=?',(status,'Delivered by Feishu API',now().isoformat(),jid))
    return {'status':status}

def send_periodic_digest(kinds):
    """Send a separate delayed digest once upstream weeklies/monthlies are published.
    Never claim their availability at 08:30 when upstream releases later.
    """
    if not FEISHU:raise ValueError('未配置飞书 Webhook')
    if not safe_url(FEISHU) or not urlparse(FEISHU).hostname.endswith('.feishu.cn'):
        raise ValueError('飞书 Webhook 必须是有效飞书 HTTPS 地址')
    valid=[]
    for kind in kinds:
        r=get_report(kind)
        if not r:continue
        if kind=='weekly':
            last_week=(now().date()-timedelta(days=7)).isocalendar()
            expected=f'{last_week.year}-W{last_week.week:02d}'
        else:
            prev=now().date().replace(day=1)-timedelta(days=1)
            expected=prev.strftime('%Y-%m')
        if r['issue_key']==expected:valid.append((kind,r))
    if not valid:return {'status':'not_published'}
    key='feishu-period-'+sh_date()+'-'+','.join(kind for kind,_ in valid)
    with LOCK:
      with connect() as c:
        old=c.execute('SELECT status FROM jobs WHERE id=?',(key,)).fetchone()
        if old and old['status']=='sent':return {'status':'already_sent'}
        c.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',(key,'sending','',now().isoformat()))
    names={'weekly':'周报','monthly':'月报'}
    msg='AI Daily｜长周期刊物已更新\n'+'\n'.join(f'{names[k]}：{r["issue_key"]}' for k,r in valid)
    msg+='\n阅读入口：'+(PUBLIC_URL+'/?view=daily' if PUBLIC_URL else '尚未配置 AI Daily 公开网址')
    try:
        body=json.dumps({'msg_type':'text','content':{'text':msg}},ensure_ascii=False).encode()
        req=urllib.request.Request(FEISHU,data=body,headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=12) as resp:result=json.loads(resp.read(10000))
        if result.get('code',result.get('StatusCode',-1))!=0:raise RuntimeError('Feishu rejected digest')
        with connect() as c:c.execute('UPDATE jobs SET status=?,detail=?,updated_at=? WHERE id=?',('sent','Published digest',now().isoformat(),key))
        return {'status':'sent','reports':[r['issue_key'] for _,r in valid]}
    except Exception as e:
        with connect() as c:c.execute('UPDATE jobs SET status=?,detail=?,updated_at=? WHERE id=?',('failed',str(e)[:200],now().isoformat(),key))
        raise

def scheduler():
    # Within one process. Avoid multiple instances in production; use one worker instance.
    last_sync=0;last_git=0;morning_attempt='';period_attempt='';period_sent_attempt='' 
    while True:
      t=now();epoch=time.time()
      if epoch-last_sync>=SYNC_INTERVAL:
        last_sync=epoch
        try:sync_aihot()
        except Exception as e:print('[sync]',e,file=sys.stderr)
      if t.hour==8 and 12<=t.minute<=20 and morning_attempt!=sh_date():
        morning_attempt=sh_date()
        try:sync_aihot()
        except Exception as e:print('[morning sync]',e,file=sys.stderr)
      if (t.weekday()==0 and t.hour==10 and t.minute>=10 or t.day==1 and t.hour==10 and t.minute>=40) and period_attempt!=sh_date():
        period_attempt=sh_date()
        try:sync_aihot()
        except Exception as e:print('[period sync]',e,file=sys.stderr)
      if t.hour==10 and t.minute>=50 and t.day==1 or t.weekday()==0 and t.hour==10 and t.minute>=50:
        if period_sent_attempt!=sh_date() and FEISHU:
          period_sent_attempt=sh_date()
          try:send_periodic_digest([k for k,required in [('weekly',t.weekday()==0),('monthly',t.day==1)] if required])
          except Exception as e:print('[period feishu]',e,file=sys.stderr)
      if epoch-last_git>=6*3600:
        last_git=epoch
        try:sync_github()
        except Exception as e:print('[github]',e,file=sys.stderr)
      if t.hour==8 and t.minute>=30 and t.minute<50 and FEISHU:
        try:
          r=get_report('daily')
          # AIHOT publishes today's edition at 08:00 Beijing, but never send a stale report.
          if r and r['issue_key']==sh_date():
            with connect() as c:
              old=c.execute('SELECT status FROM jobs WHERE id=?',('feishu-'+sh_date()+'-'+r['issue_key'],)).fetchone()
            if not old or old['status']=='sending':send_feishu(r)
        except Exception as e:print('[feishu]',e,file=sys.stderr)
      time.sleep(30)

class Handler(BaseHTTPRequestHandler):
    def respond(self,obj,status=200):
      data=json.dumps(obj,ensure_ascii=False,default=str).encode('utf8')
      self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
      path=urlparse(self.path).path;query=parse_qs(urlparse(self.path).query)
      try:
        if path=='/api/status':
          with connect() as c:
            counts={x:c.execute(f'SELECT count(*) FROM {x}').fetchone()[0] for x in ('items','reports','github_entries')}
            sent=[dict(x) for x in c.execute('SELECT id,status,updated_at FROM jobs ORDER BY updated_at DESC LIMIT 5')]
          return self.respond({'sync':LAST_SYNC,'counts':counts,'jobs':sent,'feishu_configured':bool(FEISHU),'translation_configured':bool(DEEPSEEK_KEY),'github_star_configured':bool(GITHUB_TOKEN),'public_url_configured':bool(PUBLIC_URL),'public_url':PUBLIC_URL,'github_repo_url':safe_url(GITHUB_REPO_URL),'timezone':'Asia/Shanghai','usage':'personal-noncommercial'})
        if path=='/api/preferences':return self.respond({'preferences':load_preferences()})
        if path=='/api/favorites':return self.respond({'favorites':get_favorites()})
        if path=='/api/trends':
          kind=query.get('type',['quarterly'])[0]
          if kind not in ('monthly','quarterly','yearly'):return self.respond({'error':'invalid trend type'},400)
          return self.respond({'trend':trend_report(kind)})
        if path=='/api/reports':
          with connect() as c:rows=[dict(x) for x in c.execute('SELECT type,issue_key,headline,retrieved_at,source_url FROM reports ORDER BY issue_key DESC LIMIT 500')]
          for r in rows:
            r['source_url']=human_report_url(r['type'],r['issue_key'])
            # Repair titles from old releases without changing saved report content.
            if not r['headline'] or re.match(r'^(?:AI\s+)?(?:daily|weekly|monthly)\s*[·-]',r['headline'],re.I):
              rr=get_report(r['type'],r['issue_key'])
              if rr:
                rep=rr['payload'].get('report',rr['payload'])
                if isinstance(rep,dict):
                  lead=rep.get('lead') or {}
                  title=lead.get('title') if isinstance(lead,dict) else ''
                  r['headline']=title or rep.get('title') or r['headline']
          return self.respond({'reports':rows})
        if path=='/api/report':
          kind=query.get('type',['daily'])[0];key=query.get('date',[None])[0]
          if kind not in ('daily','weekly','monthly'):return self.respond({'error':'invalid report type'},400)
          return self.respond({'report':get_report(kind,key)})
        if path=='/api/items':
          with connect() as c:rows=[dict(x) for x in c.execute('SELECT id,title,summary,url,source,published_at FROM items ORDER BY published_at DESC LIMIT 80')]
          return self.respond({'items':rows})
        if path=='/api/github-archive':
          period=query.get('period',['daily'])[0]
          return self.respond({'archive':github_archive(period)})
        if path=='/api/github-period':
          period=query.get('period',['daily'])[0]
          key=query.get('key',[None])[0]
          return self.respond(github_period(period,key))
        if path=='/api/github-star-state':
          repo=query.get('repo',[''])[0];return self.respond({'repo':repo,'starred':github_starred(repo),'configured':bool(GITHUB_TOKEN)})
        if path=='/api/github':
          with connect() as c:rows=[dict(x) for x in c.execute('SELECT * FROM github_entries ORDER BY rowid LIMIT 15')]
          return self.respond({'repos':rows,'method':'GitHub Trending daily HTML; no fallback ranking'})
        if path=='/api/qr':
          if not PUBLIC_URL:return self.respond({'error':'请先配置可从手机访问的 PUBLIC_URL'},404)
          try:
            import qrcode.image.svg
            import qrcode
            img=qrcode.make(PUBLIC_URL, image_factory=qrcode.image.svg.SvgPathImage)
            from io import BytesIO
            buf=BytesIO();img.save(buf);raw=buf.getvalue()
            self.send_response(200);self.send_header('Content-Type','image/svg+xml');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
          except ImportError:return self.respond({'error':'二维码可选组件未安装：pip install qrcode'},503)
        if path=='/api/health':return self.respond({'ok':True})
        filename='index.html' if path in ('/','/index.html') else path.lstrip('/')
        # Explicitly allowlist the image assets used by the V0.8 branding.
        static_types={'index.html':'text/html; charset=utf-8',
                      'app.js':'application/javascript; charset=utf-8',
                      'style.css':'text/css; charset=utf-8',
                      'brand.svg':'image/svg+xml',
                      'wordmark.svg':'image/svg+xml',
                      'wordmark-dark.svg':'image/svg+xml',
                      'favicon.png':'image/png',
                      'favicon.ico':'image/x-icon'}
        if filename not in static_types:return self.respond({'error':'not found'},404)
        content=(ROOT/'public'/filename).read_bytes()
        self.send_response(200);self.send_header('Content-Type',static_types[filename]);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-cache, must-revalidate');self.end_headers();self.wfile.write(content)
      except Exception as e:return self.respond({'error':str(e)[:200]},500)
    def do_POST(self):
      if self.path not in ('/api/sync','/api/sync-github','/api/send-test','/api/preferences','/api/favorites','/api/github-star'):return self.respond({'error':'not found'},404)
      # Manual changes only when bound to localhost. No public mutation endpoints.
      if HOST not in ('127.0.0.1','localhost') or self.client_address[0] not in ('127.0.0.1','::1'):
        return self.respond({'error':'Manual actions are local-only'},403)
      try:
        if self.path in ('/api/preferences','/api/favorites','/api/github-star'):
          length=int(self.headers.get('Content-Length','0'))
          if length>12000 or length<1:return self.respond({'error':'invalid body size'},400)
          data=json.loads(self.rfile.read(length))
          if not isinstance(data,dict):return self.respond({'error':'invalid input'},400)
          if self.path=='/api/preferences':return self.respond({'preferences':save_preferences(data)})
          if self.path=='/api/github-star':return self.respond(github_star(str(data.get('repo','')),remove=data.get('remove') is True))
          kind=data.get('kind');ref_id=str(data.get('ref_id',''))[:160]
          if kind not in ('article','report','github') or not ref_id:return self.respond({'error':'invalid favorite'},400)
          with connect() as c:
            if data.get('remove'):
              c.execute('DELETE FROM favorites WHERE kind=? AND ref_id=?',(kind,ref_id))
            else:
              c.execute('INSERT OR REPLACE INTO favorites VALUES (?,?,?,?,?)',(kind,ref_id,str(data.get('title',''))[:300],safe_url(data.get('url','')),now().isoformat()))
          return self.respond({'favorites':get_favorites()})
        if self.path=='/api/sync':return self.respond(sync_aihot())
        if self.path=='/api/sync-github':return self.respond(sync_github())
        return self.respond(send_feishu(get_report('daily'),force=True))
      except Exception as e:return self.respond({'error':str(e)[:200]},502)

if __name__=='__main__':
    connect().close()
    thread=threading.Thread(target=scheduler,daemon=True);thread.start()
    print('AI Daily: http://%s:%s (personal mode)'%(HOST,PORT),flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
