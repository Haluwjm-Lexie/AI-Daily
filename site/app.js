'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe=x=>{try{const u=new URL(x);return u.protocol==='https:'?u.href:'#'}catch{return '#'}};
const types={daily:'日报',weekly:'周报',monthly:'月报',quarterly:'季报',yearly:'年报'};
const topicRules={'AI 模型':/\bllm\b|gpt|claude|gemini|deepseek|kimi|千问|模型|推理|token|算力/i,'Agent':/agent|智能体|multi.agent|编排|langgraph|autogen/i,'AI 编程':/编程|代码|coding|codex|cursor|开发工具|程序员|developer/i,'开源':/开源|github|repository|repo|opensource|框架/i,'产品发布':/发布|上线|产品|更新|推出|release|launch/i,'论文研究':/论文|研究|arxiv|paper|实验|学术|research/i,'多模态':/视频|图像|视觉|音频|语音|多模态|multimodal/i,'机器人':/机器人|robot|具身/i,'AI 产品经理':/产品经理|产品管理|prd|需求|用户研究|产品设计|业务流程|product management|产品发布/i,'行业动态':/产业|融资|营收|市场|企业|监管|合作|商业|行业/i};
const state={view:'daily',type:'daily',reports:[],current:null,github:[],githubPeriod:'daily',githubArchiveKey:null,githubArchive:[],favorites:[],favoriteFilter:'all',status:null,preferences:{topics:[],reading_mode:'standard'},trendType:'monthly',starred:new Set(JSON.parse(localStorage.getItem('aidaily-starred')||'[]'))};
async function api(path,method='GET',body){if(window.AI_DAILY_STATIC)return window.aiDailyStaticApi(path,method,body);const response=await fetch(path,{method,headers:{Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败 '+response.status);return result}
const dateText=d=>{try{return new Date(d+'T12:00:00+08:00').toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'})}catch{return d}};
const weekDay=d=>{try{return ['周日','周一','周二','周三','周四','周五','周六'][new Date(d+'T12:00:00+08:00').getUTCDay()]}catch{return ''}};
function issueDates(type,key){
  try{
    if(type==='daily'){let d=new Date(key+'T12:00:00+08:00');return {range:dateText(key),sub:key.slice(0,7).replace('-','年')+'月',number:key.slice(-2)}}
    if(type==='weekly'){let m=/^(\d{4})-W(\d{2})$/.exec(key);if(!m)return {range:key,sub:key,number:key};let jan4=new Date(Date.UTC(+m[1],0,4));let dow=(jan4.getUTCDay()+6)%7;let monday=new Date(jan4.getTime()+( (+m[2]-1)*7-dow)*86400000);let sunday=new Date(monday.getTime()+6*86400000);const zh=d=>`${d.getUTCFullYear()}年${d.getUTCMonth()+1}月${d.getUTCDate()}日`;return {range:`${+m[1]}年第${+m[2]}周 · ${zh(monday)}—${zh(sunday)}`,sub:`${zh(monday)}—${zh(sunday)}`,number:String(+m[2]).padStart(2,'0')}}
    if(type==='monthly'){let [y,m]=key.split('-');return {range:`${y}年${+m}月`,sub:`${y}年`,number:m}}
    if(type==='quarterly'){let [y,q]=key.split('-Q');return {range:`${y}年第${q}季度`,sub:`${y}年 · 第${q}季度`,number:'Q'+q}}
    return {range:key+'年度',sub:key+'年',number:key.slice(-2)}
  }catch(e){return {range:key,sub:key,number:key}}
}
function issueOrdinal(type,key){let sorted=state.reports.filter(r=>r.type===type).map(r=>r.issue_key).sort();let i=sorted.indexOf(key);return i<0?'—':String(i+1)}
function reportStats(r){
  let stories=new Set(),sources=new Set(),items=[];
  const add=(x)=>{if(!x||typeof x!=='object')return;let title=titleOf(x);if(title){stories.add(String(x.id||x.publicId||title));items.push(x)}let source=x.source?.name||x.sourceName||(typeof x.source==='string'?x.source:'');if(source&&source!=='原始来源')sources.add(source)};
  sectionsOf(r).forEach(sec=>(sec.items||sec.stories||[]).filter(x=>allowedArticle(x,sec.label||sec.title||'')).forEach(add));(r.flashes||[]).filter(x=>allowedArticle(x)).forEach(add);
  const lead=leadOf(r);if(lead&&typeof lead==='object'&&matchTopic(titleOf(lead)+' '+summaryOf(lead)))add(lead);
  let count=!(state.preferences?.topics||[]).length&&Number.isFinite(Number(r.storyCount??r.totalStories))?Number(r.storyCount??r.totalStories):stories.size;
  let sourceCount=!(state.preferences?.topics||[]).length&&Number.isFinite(Number(r.sourceCount??r.totalSources))?Number(r.sourceCount??r.totalSources):sources.size;
  return {stories:count||stories.size||'—',sources:sourceCount||'—'};
}
function setTheme(v){document.body.classList.toggle('dark',v);localStorage.setItem('aidaily-theme',v?'dark':'light');$('#theme').textContent=v?'☼':'☾'}
setTheme(localStorage.getItem('aidaily-theme')!=='light');$('#theme').onclick=()=>setTheme(!document.body.classList.contains('dark'));
function page(view){state.view=view;$$('.page').forEach(e=>e.hidden=e.id!==`page-${view}`);$$('.rail-item').forEach(e=>e.classList.toggle('active',e.dataset.view===view));const edition=view==='daily'||view==='github';$('#shell').classList.toggle('with-edition',edition);$('#edition-panel').hidden=view!=='daily';$('#github-panel').hidden=view!=='github';try{history.replaceState({},'',`?view=${view}`)}catch(_e){};$('#reading').scrollTop=0;if(view==='github')showGithub();if(view==='favorites')showFavorites();if(view==='trends')showTrend();if(view==='settings')showSettings()}
$$('[data-view]').forEach(b=>b.onclick=()=>page(b.dataset.view));
const titleOf=x=>typeof x==='string'?x:x?.title||x?.headline||x?.name||'';
const summaryOf=x=>typeof x==='string'?'':x?.summary||x?.leadParagraph||x?.description||x?.text||'';
const linkOf=x=>{if(!x||typeof x!=='object')return '';const l=x.links||{};const u=l.original||x.originalUrl||x.url||l.aihot||'';return typeof u==='string'?u:(u?.url||'')};
const sourceOf=x=>typeof x?.source==='string'?x.source:(x?.source?.name||x?.sourceName||'原始来源');
const sectionsOf=r=>Array.isArray(r?.sections)?r.sections:Array.isArray(r?.columns)?r.columns:[];
const leadOf=r=>r?.lead||r?.headline||r?.topStory||{};
const fKey=(kind,id)=>kind+'|'+id;
function isFav(kind,id){return state.favorites.some(x=>x.kind===kind&&x.ref_id===id)}
function favButton(kind,id,title,url){return `<button class="soft-button" data-fav-kind="${esc(kind)}" data-fav-id="${esc(id)}" data-fav-title="${esc(title)}" data-fav-url="${esc(url||'')}">${isFav(kind,id)?'♥ 已收藏':'♡ 收藏'}</button>`}
async function toggleFav(b){const kind=b.dataset.favKind,id=b.dataset.favId;try{state.favorites=(await api('/api/favorites','POST',{kind,ref_id:id,title:b.dataset.favTitle,url:b.dataset.favUrl,remove:isFav(kind,id)})).favorites;renderReport();if(state.view==='github')showGithub();if(state.view==='favorites')showFavorites()}catch(e){alert('收藏失败：'+e.message)}}
document.addEventListener('click',e=>{let b=e.target.closest('[data-fav-id]');if(b)toggleFav(b)});
function matchTopic(text,section=''){let selected=state.preferences?.topics||[];if(!selected.length)return true;let corpus=(text+' '+section).toLowerCase();return selected.some(t=>(topicRules[t]||new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i')).test(corpus))}
function allowedArticle(item,section=''){return matchTopic(titleOf(item)+' '+summaryOf(item),section)}
function articleHTML(x){const title=titleOf(x),url=linkOf(x),id=String(x?.publicId||x?.id||url||title);return `<article class="news-entry"><h3>${esc(title)}</h3>${summaryOf(x)?`<p>${esc(summaryOf(x))}</p>`:''}<div class="source-row"><span>${esc(sourceOf(x))}</span>${url?`<a href="${safe(url)}" target="_blank" rel="noopener">原始来源 ↗</a>`:''}${favButton('article',id,title,url)}</div></article>`}
function reportGroup(r){return r.type==='daily'?r.issue_key.slice(0,7):r.issue_key.slice(0,4)}
function renderIndex(){let list=state.reports.filter(x=>x.type===state.type),groups=new Map();$('#archive-count').textContent=list.length+' 期';for(let r of list){let key=reportGroup(r);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r)}let html='';for(let [key,rows] of groups){let label=/^\d{4}-\d{2}$/.test(key)?key.replace('-',' 年 ')+' 月':key+' 年';html+=`<div class="month-label">${esc(label)}<span>${rows.length}</span></div>`;for(let r of rows){let day=state.type==='daily'?r.issue_key.slice(-2):state.type==='weekly'?issueDates('weekly',r.issue_key).number:r.issue_key.slice(-2);html+=`<button class="issue-choice ${state.current?.issue_key===r.issue_key&&state.current?.type===r.type?'active':''}" data-key="${esc(r.issue_key)}"><span class="day-num">${esc(day)}<small>${state.type==='daily'?weekDay(r.issue_key):state.type==='weekly'?'第'+Number(issueDates('weekly',r.issue_key).number)+'周':types[r.type]}</small></span><span class="issue-choice-title">${esc((r.headline&&!/^(AI |daily|weekly|monthly|日报|周报|月报) ?(?:·|\s*[-0-9])/.test(r.headline))?r.headline:(r.lead_title||types[r.type]+' · '+r.issue_key))}</span></button>`}}$('#edition-scroll').innerHTML=html||'<p class="empty">暂无归档。同步后可在这里选择往期报告。</p>';$$('.issue-choice').forEach(b=>b.onclick=()=>loadReport(state.type,b.dataset.key));$('#panel-bottom-text').textContent=state.type==='daily'?'日报 · 每日 08:00 后':state.type==='weekly'?'周报 · 周一 10:00 后':state.type==='monthly'?'月报 · 每月 10:30 后':'历史归档 · 趋势分析'}
function setType(t){state.type=t;$$('[data-type]').forEach(b=>b.classList.toggle('selected',b.dataset.type===t));renderIndex();loadReport(t)}$$('[data-type]').forEach(b=>b.onclick=()=>setType(b.dataset.type));
function renderReport(){const saved=state.current,r=saved?.payload?.report||saved?.payload;$('#issue-label').textContent=types[state.type]||'期刊';$('#report-heading').textContent=types[state.type]||'日报';if(!saved||!r){$('#issue-datetime').textContent='AI DAILY · 等待归档';$('#issue-number').textContent='—';$('#issue-month').textContent='暂无刊物';$('#metric-stories').textContent='—';$('#metric-sources').textContent='—';$('#issue-ordinal').textContent='尚未出刊';$('#report-alert').textContent='本期暂无可用真实内容；可以同步最新刊物。';$('#issue-content').innerHTML='';renderIndex();return}
const lead=leadOf(r),leadTitle=titleOf(lead)||saved.headline,leadVisible=matchTopic(leadTitle+' '+summaryOf(lead));const details=issueDates(state.type,saved.issue_key),stats=reportStats(r);$('#issue-datetime').textContent=details.range;$('#issue-number').textContent=details.number;$('#issue-month').textContent=details.sub;$('#issue-ordinal').textContent='第 '+issueOrdinal(state.type,saved.issue_key)+' 期';$('#metric-stories').textContent=stats.stories;$('#metric-sources').textContent=stats.sources;
let content='';if(leadVisible)content+=`<div class="section-kicker">头条</div><h2 class="lead-title">${esc(leadTitle)}</h2>${summaryOf(lead)?`<p class="lead-summary">${esc(summaryOf(lead))}</p>`:''}<div class="source-row">${favButton('report',state.type+':'+saved.issue_key,leadTitle,saved.source_url)}<a href="${safe(saved.source_url)}" target="_blank" rel="noopener">查看原始刊物 ↗</a></div>`;
let highlights=r.highlights||r.todaysHighlights||r.digest||[];if(Array.isArray(highlights)){highlights=highlights.filter(it=>allowedArticle(it));if(highlights.length)content+=`<div class="highlight-strip"><h2>${state.type==='daily'?'今日看点':'本期看点'}</h2><ol>${highlights.slice(0,8).map(it=>`<li>${esc(titleOf(it))}</li>`).join('')}</ol></div>`}
let count=0;sectionsOf(r).forEach((sec,i)=>{let label=sec.label||sec.title||'本期事件',items=(sec.items||sec.stories||[]).filter(it=>allowedArticle(it,label));if(!items.length)return;count+=items.length;content+=`<section class="section-block"><h2><span class="section-number">${String(i+1).padStart(2,'0')}</span>${esc(label)}</h2>${items.map(articleHTML).join('')}</section>`});let flashes=(r.flashes||[]).filter(it=>allowedArticle(it));if(flashes.length){count+=flashes.length;content+=`<section class="section-block"><h2>快讯</h2>${flashes.map(articleHTML).join('')}</section>`}
if(!content)content='<p class="empty">当前关注主题没有匹配到本期新闻。可在「阅读偏好」修改主题后重新查看。</p>';$('#report-alert').textContent='';$('#issue-content').innerHTML=content;renderIndex();magazineNeighbors()}
async function loadReport(kind,key){if(['quarterly','yearly'].includes(kind)){await loadLongReport(kind);return}try{let response=await api('/api/report?type='+kind+(key?'&date='+encodeURIComponent(key):''));state.current=response.report;if(state.current)state.current.type=kind;renderReport()}catch(e){$('#report-alert').textContent='报告读取失败：'+e.message}}
async function loadLongReport(kind){try{let result=(await api('/api/trends?type='+kind)).trend;state.current={type:kind,issue_key:result.issue_key};$('#issue-datetime').textContent=issueDates(kind,result.issue_key).range;$('#issue-label').textContent=types[kind];$('#report-heading').textContent=types[kind];$('#issue-number').textContent=issueDates(kind,result.issue_key).number;$('#issue-month').textContent=issueDates(kind,result.issue_key).sub;$('#metric-stories').textContent=result.events.length;$('#metric-sources').textContent='—';$('#issue-ordinal').textContent='归档分析';$('#report-alert').textContent=result.status==='partial'?'目前只有部分历史记录，不能据此声称完整'+types[kind]+'趋势。':'';$('#issue-content').innerHTML=trendMarkup(result);renderIndex()}catch(e){$('#report-alert').textContent='归档分析失败：'+e.message}}
function trendMarkup(r){const mx=Math.max(1,...r.topics.map(t=>t[1]));return `<div class="coverage"><strong>${esc(r.issue_key)} · 数据覆盖 ${r.covered_days}/${r.total_days} 天（${r.coverage}%）</strong><p>${esc(r.note)}</p></div><div class="section-block"><h2>主题分布</h2>${r.topics.length?r.topics.map(t=>`<div class="bar-row"><div class="bar-head"><span>${esc(t[0])}</span><strong>${t[1]}</strong></div><div class="bar-track"><div style="width:${100*t[1]/mx}%"></div></div></div>`).join(''):'<p class="empty">当前没有足够数据。</p>'}</div><div class="section-block"><h2>代表事件</h2>${r.events.slice(0,30).map(e=>`<div class="news-entry"><div class="meta">${esc(e.date)}</div><h3>${esc(e.title)}</h3></div>`).join('')}</div>`}
async function showGithubPeriods(){
  $$('.edition-panel [data-gperiod]').forEach(b=>b.classList.toggle('selected',b.dataset.gperiod===state.githubPeriod));
  try{state.githubArchive=(await api('/api/github-archive?period='+state.githubPeriod)).archive||[]}
  catch(e){state.githubArchive=[]}
  let groups=new Map();for(const row of state.githubArchive){let group=state.githubPeriod==='daily'?row.key.slice(0,7):row.key.slice(0,4);if(!groups.has(group))groups.set(group,[]);groups.get(group).push(row)}
  let html='';for(const [group,rows] of groups){html+=`<div class="month-label">${esc(/^\d{4}-\d{2}$/.test(group)?group.replace('-','年')+'月':group+'年')}<span>${rows.length} 期</span></div>`;
    for(const r of rows){let info=issueDates(state.githubPeriod,r.key);let label=state.githubPeriod==='daily'?`<span class="day-num">${esc(r.key.slice(-2))}<small>${weekDay(r.key)}</small></span>`:`<span class="day-num">${esc(info.number)}<small>${types[state.githubPeriod]}</small></span>`;
    html+=`<button class="issue-choice ${state.githubArchiveKey===r.key?'active':''}" data-garchive="${esc(r.key)}">${label}<span class="issue-choice-title">${esc(r.headline||r.title||info.range)}</span></button>`;}}
  $('#github-period-list').innerHTML=html||'<p class="empty">暂无历史快照。首次同步后，往期会按月份及日期归档。</p>';
  $$('[data-garchive]').forEach(b=>b.onclick=async()=>{state.githubArchiveKey=b.dataset.garchive;await showGithub()});
}
async function setGithubPeriod(p){state.githubPeriod=p;state.githubArchiveKey=null;await showGithub()}
$$('[data-gperiod]').forEach(b=>b.onclick=()=>setGithubPeriod(b.dataset.gperiod));
async function showGithub(){await showGithubPeriods();let data;try{data=await api('/api/github-period?period='+state.githubPeriod+(state.githubArchiveKey?'&key='+encodeURIComponent(state.githubArchiveKey):''));state.github=data.repos||[]}catch(e){$('#github-notice').textContent='榜单读取失败：'+e.message+'。已保存数据不会被删除。';return}$('#repo-count').textContent=state.github.length;$('#minimum-stars').textContent=data.minimum_stars||500;$('#github-period-range').textContent=data.start+' — '+data.end;$('#github-subtitle').textContent=({daily:'GitHub 日报',weekly:'GitHub 周报',monthly:'GitHub 月报',quarterly:'GitHub 季报',yearly:'GitHub 年报'})[state.githubPeriod]+' · 开源生态观察';$('#github-coverage').textContent=data.observed_only?'历史快照归档':'Github Trending + 仓库 Stars';$('#github-notice').textContent=data.historical_fallback?'当前尚无今日榜单，显示最近一次真实快照：'+data.start+'。同步成功后自动更新。':data.observed_only?'按已归档的榜单快照排名，非 GitHub 官方季度／年度榜单；历史积累不足时结果可能不完整。':'入选需同时上榜且仓库总 Star ≥ '+data.minimum_stars+'。GitHub Star 是累计数，不等于本期新增 Star。';
$('#github-grid').innerHTML=state.github.length?state.github.map((r,i)=>`<article class="repo-entry"><span class="repo-index">${String(i+1).padStart(2,'0')}</span><div><h3><a href="${safe(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.repo)} ↗</a></h3><p>${esc(r.description_zh||r.description||'暂无项目简介')}</p>${r.description_zh?`<div class="meta">原文：${esc(r.description)}</div>`:''}<div class="repo-badges"><span class="note-tag">${esc(r.category||'其他')}</span><span class="note-tag">★ ${r.stars==null?'待验证':Number(r.stars).toLocaleString()}</span>${r.language?`<span class="note-tag">${esc(r.language)}</span>`:''}${r.appearances?`<span class="note-tag">入榜 ${r.appearances} 次</span>`:''}</div></div><div class="repo-actions">${favButton('github',r.repo,r.repo,r.url)}<button class="soft-button github-star" data-star-repo="${esc(r.repo)}">${window.AI_DAILY_STATIC?'☆':(state.starred.has(r.repo)?'★':'☆')}</button></div></article>`).join(''):'<p class="empty">这一周期还没有达到热度门槛的可靠榜单快照。首次安装后需要联网同步和历史积累。</p>';
if(!window.AI_DAILY_STATIC)refreshGithubStars();magazineNeighbors();}
// The browser cache is not the source of truth: refresh each visible GitHub Star state.
async function refreshGithubStars(){
  if(window.AI_DAILY_STATIC||!state.status?.github_star_configured)return;
  const repos=state.github.map(r=>r.repo).slice(0,20);
  for(const repo of repos){
    try{
      const d=await api('/api/github-star-state?repo='+encodeURIComponent(repo));
      if(typeof d.starred!=='boolean')continue;
      if(d.starred)state.starred.add(repo);else state.starred.delete(repo);
      const b=[...document.querySelectorAll('[data-star-repo]')].find(x=>x.dataset.starRepo===repo);
      if(b){b.textContent=d.starred?'★':'☆';b.classList.toggle('is-starred',d.starred);b.setAttribute('aria-label',d.starred?'取消 GitHub Star':'添加 GitHub Star');b.title=d.starred?'已 Star，点击取消':'点击 Star';}
    }catch(e){}
  }
  localStorage.setItem('aidaily-starred',JSON.stringify([...state.starred]));
}
document.addEventListener('click',async e=>{
  const btn=e.target.closest('[data-star-repo]'); if(!btn)return; if(window.AI_DAILY_STATIC){window.open('https://github.com/'+encodeURI(btn.dataset.starRepo),'_blank','noopener,noreferrer');return;}
  const repo=btn.dataset.starRepo, remove=state.starred.has(repo);
  btn.disabled=true;
  try{
    const result=await api('/api/github-star','POST',{repo,remove});
    if(remove){
      if(result.status!=='unstarred')throw Error('GitHub 未确认取消 Star');
      state.starred.delete(repo);
      // 站内收藏与 GitHub Star 是两种不同操作：取消 Star 不自动删除收藏。
    }else{
      if(result.status!=='starred')throw Error('GitHub 未确认 Star');
      state.starred.add(repo);
      // 保留原有体验：首次 Star 时，同时加入 AI Daily 收藏。
      if(!isFav('github',repo)){
        try{state.favorites=(await api('/api/favorites','POST',{kind:'github',ref_id:repo,title:repo,url:'https://github.com/'+repo})).favorites}
        catch(favError){alert('GitHub Star 已成功，但 AI Daily 收藏失败：'+favError.message)}
      }
    }
    localStorage.setItem('aidaily-starred',JSON.stringify([...state.starred]));
    await showGithub();
  }catch(err){
    alert(err.message+'\n如需检查实际状态，可以打开项目的 GitHub 页面。');
    btn.disabled=false;
  }
});

function showFavorites(){let entries=state.favorites.filter(f=>state.favoriteFilter==='all'||f.kind===state.favoriteFilter);$$('[data-fav-filter]').forEach(b=>b.classList.toggle('selected',b.dataset.favFilter===state.favoriteFilter));$('#favorites-list').innerHTML=entries.length?entries.map(f=>`<article class="favorite-entry"><span class="repo-index">♡</span><div><h3>${esc(f.title)}</h3><div class="meta">${({github:'开源项目',article:'资讯',report:'报告'})[f.kind]||f.kind} · ${esc((f.created_at||'').slice(0,16))}</div>${f.url?`<a href="${safe(f.url)}" target="_blank" rel="noopener">查看来源 ↗</a>`:''}</div>${favButton(f.kind,f.ref_id,f.title,f.url)}</article>`).join(''):'<p class="empty">这里还没有相应收藏。点击日报或开源项目旁边的「♡ 收藏」即可保存。</p>'}$$('[data-fav-filter]').forEach(b=>b.onclick=()=>{state.favoriteFilter=b.dataset.favFilter;showFavorites()});
async function showTrend(){try{const r=(await api('/api/trends?type='+state.trendType)).trend;$$('[data-trend]').forEach(b=>b.classList.toggle('selected',b.dataset.trend===state.trendType));$('#trend-content').innerHTML=trendMarkup(r)}catch(e){$('#trend-content').textContent='趋势读取失败：'+e.message}}$$('[data-trend]').forEach(b=>b.onclick=()=>{state.trendType=b.dataset.trend;showTrend()});
const allTopics=Object.keys(topicRules);
function showSettings(){const p=state.preferences||{topics:[]};$('#topics').innerHTML=allTopics.map(t=>`<label><input type="checkbox" value="${esc(t)}" ${p.topics?.includes(t)?'checked':''}> ${esc(t)}</label>`).join('');$('#settings-status').textContent='';}
$('#save-settings').onclick=async()=>{try{let topics=$$('#topics input:checked').map(x=>x.value);state.preferences=(await api('/api/preferences','POST',{topics,reading_mode:'standard'})).preferences;$('#settings-status').textContent=`已应用 ${topics.length} 个主题 · 返回日报即可查看筛选结果`;if(state.current?.payload)renderReport()}catch(e){$('#settings-status').textContent='保存失败：'+e.message}};
$('#open-runtime').onclick=()=>{let panel=$('#runtime-panel');panel.hidden=!panel.hidden;const s=state.status||{};$('#runtime-metrics').innerHTML=`<div><span>飞书推送</span><b>${s.feishu_configured?'已配置':'未配置'}</b></div><div><span>资讯同步</span><b>${s.sync?.status==='ok'?'正常':'待检查'}</b></div><div><span>最近同步</span><b style="font-size:13px">${esc(s.sync?.at?.slice(0,19)||'暂无')}</b></div>`};
$('#test-feishu').onclick=async()=>{try{let r=await api('/api/send-test','POST');$('#runtime-msg').textContent='发送结果：'+r.status}catch(e){$('#runtime-msg').textContent='测试失败：'+e.message}};
$('#open-source').onclick=e=>{if($('#open-source').getAttribute('aria-disabled')==='true'){e.preventDefault();alert('GitHub 仓库创建后，在配置中设置仓库链接即可启用。')}};
async function reload(){const paths=['/api/status','/api/reports','/api/favorites','/api/preferences'];let answers=await Promise.allSettled(paths.map(p=>api(p)));if(answers[0].status==='fulfilled')state.status=answers[0].value;if(answers[1].status==='fulfilled')state.reports=answers[1].value.reports||[];if(answers[2].status==='fulfilled')state.favorites=answers[2].value.favorites||[];if(answers[3].status==='fulfilled')state.preferences=answers[3].value.preferences;if(state.status?.github_repo_url){$('#open-source').href=state.status.github_repo_url;$('#open-source').setAttribute('aria-disabled','false');$('#open-source').target='_blank';$('#open-source').rel='noopener noreferrer'}$('#connection-dot').classList.toggle('ok',state.status?.sync?.status==='ok');$('#connection-label').textContent=state.status?.sync?.status==='ok'?'资讯已同步':'等待同步';renderIndex()}
$('#sync').onclick=async()=>{if(window.AI_DAILY_STATIC){location.reload();return;}let b=$('#sync');b.disabled=true;try{await api('/api/sync','POST');await reload();await loadReport(state.type);alert('同步完成')}catch(e){alert('同步失败：'+e.message)}finally{b.disabled=false}};
$('#refresh-github').onclick=async()=>{if(window.AI_DAILY_STATIC){location.reload();return;}let b=$('#refresh-github');b.disabled=true;try{await api('/api/sync-github','POST');await showGithub()}catch(e){alert('GitHub 同步失败：'+e.message)}finally{b.disabled=false}};
// Robust canvas export: actual glyph measurement, no splitting English tokens, uniform margins.
function wrapText(ctx,text,maxWidth){const paras=String(text||'').split('\n'),out=[];for(const para of paras){let words=para.match(/[A-Za-z0-9][A-Za-z0-9_./:+@#$%&-]*|\s+|[^A-Za-z0-9\s]/gu)||[];let line='';for(const word of words){if(!line&&!word.trim())continue;let next=line+word;if(ctx.measureText(next).width<=maxWidth){line=next;continue}if(line.trim()){out.push(line.trim());line=''}if(!word.trim())continue;if(ctx.measureText(word).width<=maxWidth){line=word;continue}let piece='';for(const ch of [...word]){if(ctx.measureText(piece+ch).width>maxWidth&&piece){out.push(piece);piece=ch}else piece+=ch}line=piece}if(line.trim())out.push(line.trim());if(!para)out.push('')}return out.length?out:['']}
function downloadCanvas(canvas,filename){canvas.toBlob(blob=>{if(!blob){alert('图片生成失败');return}const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000)},'image/png')}
async function drawDocument(entries,filename){const dark=document.body.classList.contains('dark'),theme=dark?{bg:'#11191c',text:'#edf4f2',muted:'#a4b6ba',line:'#344247',accent:'#12c1cd'}:{bg:'#fbfcfa',text:'#1e282d',muted:'#738086',line:'#d9e1df',accent:'#087d86'};const width=1080,margin=76,textWidth=width-2*margin,scale=2,measure=document.createElement('canvas').getContext('2d'),font='"Microsoft YaHei UI","Microsoft YaHei","Noto Sans SC",sans-serif';let laid=[],height=164;const settings={brand:[27,39,16],lead:[33,51,22],section:[25,39,22],item:[21,33,15],text:[17,30,12],meta:[14,25,10]};for(let entry of entries){let kind=entry.kind||'text';if(kind==='divider'){laid.push({kind:'divider',y:height+8});height+=26;continue}let s=settings[kind]||settings.text,weight=['brand','lead','section','item'].includes(kind)?'700':'400';measure.font=`${weight} ${s[0]}px ${font}`;let lines=wrapText(measure,entry.text,textWidth);let padBefore=kind==='section'?35:kind==='item'?18:kind==='lead'?28:kind==='brand'?8:7;let padAfter=kind==='section'?8:kind==='item'?5:8;laid.push({kind,lines,size:s[0],line:s[1],weight,y:height+padBefore});height+=padBefore+lines.length*s[1]+padAfter+(kind==='section'?16:0)}height+=120;if(height>27000){alert('本期内容过长，请缩小筛选范围后导出');return}const cv=document.createElement('canvas');cv.width=width*scale;cv.height=height*scale;let c=cv.getContext('2d');c.scale(scale,scale);c.fillStyle=theme.bg;c.fillRect(0,0,width,height);c.fillStyle=theme.accent;c.font=`700 30px ${font}`;c.fillText('AI Daily',margin,78);c.strokeStyle=theme.line;c.lineWidth=1;c.beginPath();c.moveTo(margin,106);c.lineTo(width-margin,106);c.stroke();for(let it of laid){let y=it.y;if(it.kind==='divider'){c.strokeStyle=theme.line;c.beginPath();c.moveTo(margin,y);c.lineTo(width-margin,y);c.stroke();continue}if(it.kind==='section'){c.strokeStyle=theme.line;c.beginPath();c.moveTo(margin,y-21);c.lineTo(width-margin,y-21);c.stroke()}c.font=`${it.weight} ${it.size}px ${font}`;c.fillStyle=it.kind==='section'?theme.accent:it.kind==='meta'?theme.muted:theme.text;for(let l of it.lines){c.fillText(l,margin,y);y+=it.line}}c.font=`14px ${font}`;c.fillStyle=theme.muted;c.fillText('AI Daily · '+new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'}),margin,height-49);
// QR appears only when a real public URL is configured and the optional QR server module works.
if(state.status?.public_url_configured){try{let img=new Image();img.src='/api/qr';await img.decode();c.fillStyle=dark?'#fff':'#fff';c.fillRect(width-margin-106,height-153,106,106);c.drawImage(img,width-margin-101,height-148,96,96)}catch(e){/* no QR if URL or QR library not ready */}}downloadCanvas(cv,filename)}
$('#export-daily').onclick=async()=>{const saved=state.current,r=saved?.payload?.report||saved?.payload;if(!saved||!r){alert('暂无真实归档');return}const entries=[{kind:'brand',text:'AI '+types[state.type]+' · '+saved.issue_key}];let lead=leadOf(r);if(matchTopic(titleOf(lead)+' '+summaryOf(lead)))entries.push({kind:'lead',text:titleOf(lead)||saved.headline},{kind:'text',text:summaryOf(lead)});for(let sec of sectionsOf(r)){const items=(sec.items||sec.stories||[]).filter(it=>allowedArticle(it,sec.label||sec.title));if(!items.length)continue;entries.push({kind:'section',text:sec.label||sec.title||'本期事件'});for(let item of items){entries.push({kind:'item',text:titleOf(item)});if(summaryOf(item))entries.push({kind:'text',text:summaryOf(item)});entries.push({kind:'divider'})}}for(let item of (r.flashes||[]).filter(it=>allowedArticle(it))){entries.push({kind:'item',text:titleOf(item)});entries.push({kind:'text',text:summaryOf(item)});entries.push({kind:'divider'})}await drawDocument(entries,'AI-Daily-'+saved.issue_key+'.png')};
$('#export-png').onclick=async()=>{if(!state.github.length){alert('当前没有可导出的真实项目');return}let entries=[{kind:'brand',text:'GitHub Trending · '+({daily:'今日',weekly:'本周',monthly:'上月',quarterly:'上季度',yearly:'去年'})[state.githubPeriod]}];for(let [i,r] of state.github.entries()){entries.push({kind:'item',text:String(i+1).padStart(2,'0')+' · '+r.repo});entries.push({kind:'text',text:r.description_zh||r.description||''});entries.push({kind:'meta',text:(r.category||'其他')+'   ★ '+(r.stars??'未验证')+'   '+(r.language||'')})}await drawDocument(entries,'AI-Daily-GitHub-'+state.githubPeriod+'.png')};

// V0.8 magazine navigation and scroll behavior.
function magazineNeighbors(){
 const rows=state.view==='github' ? state.githubArchive.map(r=>({key:r.key,headline:r.headline||issueDates(state.githubPeriod,r.key).range})) : state.reports.filter(r=>r.type===state.type).map(r=>({key:r.issue_key,headline:r.headline||r.issue_key}));
 const key=state.view==='github'?(state.githubArchiveKey||rows[0]?.key):state.current?.issue_key;
 const i=rows.findIndex(r=>r.key===key);const host=state.view==='github'?$('#github-neighbors'):$('#daily-neighbors');if(!host)return;
 const links=[[rows[i+1],'← 前一期'],[rows[i-1],'后一期 →']];
 host.innerHTML=links.map(([r,label])=>r?`<button type="button" data-mag-kind="${state.view}" data-mag-key="${esc(r.key)}"><small>${label}</small><b>${esc(r.headline||r.key)}</b></button>`:'<span></span>').join('');
}
document.addEventListener('click',async e=>{let b=e.target.closest('[data-mag-kind]');if(!b)return;
 if(b.dataset.magKind==='github'){state.githubArchiveKey=b.dataset.magKey;await showGithub()}else await loadReport(state.type,b.dataset.magKey);
 const p=$('#reading');if(p) p.scrollTo({top:0,behavior:'smooth'});
});
const topBtn=$('#back-to-top');const readingPane=$('#reading');
function topVisibility(){topBtn.classList.toggle('visible',readingPane.scrollTop>350||window.scrollY>450)}
readingPane.addEventListener('scroll',topVisibility,{passive:true});window.addEventListener('scroll',topVisibility,{passive:true});
topBtn.addEventListener('click',()=>{readingPane.scrollTo({top:0,behavior:'smooth'});window.scrollTo({top:0,behavior:'smooth'})});

reload().then(async()=>{await loadReport('daily');const v=new URLSearchParams(location.search).get('view');if(['daily','github','favorites','trends','settings','models','changelog'].includes(v))page(v)}).catch(e=>{$('#report-alert').textContent='本地服务未连接：'+e.message});
