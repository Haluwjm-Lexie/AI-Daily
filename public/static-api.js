'use strict';
// GitHub Pages adapter. Private credentials NEVER enter the browser or site/data.
window.AI_DAILY_STATIC=true;
let bundlePromise=null;
const storeRead=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}};
const prefDefault={topics:[],reading_mode:'standard'};
const curated=()=>bundlePromise??=fetch('./data/export.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('公开报告尚未发布');return r.json()});
const issueDate=(iso)=>iso.split('T')[0];
window.aiDailyStaticApi=async function(path,method='GET',body){
 const u=new URL(path,location.href), p=u.pathname.split('/api/').pop(), d=await curated();
 if(method!=='GET'){
   if(p==='favorites'){
     let rows=storeRead('aidaily-pages-favorites',[]),idx=rows.findIndex(f=>f.kind===body.kind&&f.ref_id===body.ref_id);
     if(body.remove){if(idx>=0)rows.splice(idx,1)}else if(idx<0)rows.unshift({kind:body.kind,ref_id:body.ref_id,title:body.title,url:body.url,created_at:new Date().toISOString()});
     localStorage.setItem('aidaily-pages-favorites',JSON.stringify(rows));return {favorites:rows};
   }
   if(p==='preferences'){
     const val={...prefDefault,...body};localStorage.setItem('aidaily-pages-preferences',JSON.stringify(val));return {preferences:val};
   }
   throw Error('公开版不提供服务器写操作；GitHub Star 请打开项目页面，用自己的 GitHub 账号操作。');
 }
 if(p==='status')return {sync:{status:d.reports.length||Object.values(d.github_archive).some(x=>x.length)?'ok':'not_started',at:d.generated_at},counts:{reports:d.reports.length,github_entries:(d.github_archive.daily||[]).length},github_star_configured:false,feishu_configured:false,public_url_configured:true,public_url:location.origin+location.pathname,github_repo_url:'',timezone:'Asia/Shanghai'};
 if(p==='reports')return {reports:d.reports.map(({payload,...r})=>r)};
 if(p==='report'){
    const kind=u.searchParams.get('type')||'daily',key=u.searchParams.get('date')||'';
    return {report:d.reports.find(r=>r.type===kind&&(!key||r.issue_key===key))||null};
 }
 if(p==='github-archive')return {archive:d.github_archive[u.searchParams.get('period')||'daily']||[]};
 if(p==='github-period'){
    const kind=u.searchParams.get('period')||'daily',key=u.searchParams.get('key')||'';
    const rows=d.github_period[kind]||{};let last=key||Object.keys(rows).sort().at(-1);
    return rows[last]||{repos:[],period:kind,start:'—',end:'—',minimum_stars:d.min_stars,observed_only:true};
 }
 if(p==='trends')return {trend:d.trends[u.searchParams.get('type')||'monthly']||{issue_key:'—',covered_days:0,total_days:0,coverage:0,topics:[],events:[]}};
 if(p==='favorites')return {favorites:storeRead('aidaily-pages-favorites',[])};
 if(p==='preferences')return {preferences:storeRead('aidaily-pages-preferences',prefDefault)};
 if(p==='github-star-state')return {starred:null,configured:false};
 if(p==='github')return {repos:[]};
 throw Error('此功能仅在本地管理版提供');
};
