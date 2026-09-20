import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

type Operation = {operationId:string; orderId:string; amountMinor:number; currency:string};
type Capture = Operation & {effectId:number; idempotencyKey:string|null};
type RecordedEvent = {type:string; operationId?:string; attempt?:number; effectId?:number; amountMinor?:number; currency?:string; boundary?:{checkpoint:string}};
type Case = {worldId:string; label:string; verdict:string; elapsedSeconds:number; buildDigest:string; plan:{variant:string; operations:Operation[]; actions:unknown[]}; observation:{ledger:Capture[]; application:Record<string,unknown>[]} | null; events:RecordedEvent[]; diagnostics:string[]; properties:{property:string;passed:boolean;operationId:string;detail:string}[]; replayMatched?:boolean; comparison?:boolean};
type Reduction = {beforeActions:number; afterActions:number; oneMinimal:boolean; case:Case};
type Campaign = {id:string; variant:string; lifecycle:string; operation:Operation; cases:Case[]; counts:Record<string,number>; discoveredCheckpoints:string[]; executed:number; reduction?:Reduction; diagnostics?:string[]};
type Job = {id:string; kind:string; lifecycle:string; error?:string; result:unknown; campaignId?:string; sourceCaseId?:string; sourceCaseLabel?:string};
type Fixtures = {variants:Record<string,string>; readOnly:boolean; tokenRequired:boolean; activeJob:string|null};
type Target = {id?:string; label?:string};
type View = 'lab'|'evidence';

const PASS='PASS_WITHIN_BOUNDS', FAIL='PROPERTY_VIOLATION';
const pretty=(value:string)=>value.replaceAll('_',' ').toLowerCase();
const tone=(value?:string)=>value===PASS?'pass':value===FAIL?'fail':value?'warn':'neutral';
const money=(minor:number,currency='INR')=>new Intl.NumberFormat('en-IN',{style:'currency',currency,maximumFractionDigits:minor%100?2:0}).format(minor/100);
const viewFromHash=():View=>window.location.hash==='#evidence'?'evidence':'lab';

function Badge({value}:{value?:string}) {
 return <span className={'badge '+tone(value)}><i/>{value===PASS?'Pass within bounds':value===FAIL?'Property violation':value?pretty(value):'Not run'}</span>;
}
function Icon({name}:{name:'logo'|'play'|'grid'|'file'|'arrow'}) {
 return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">{name==='logo'?<><path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="m7 12 3 3 7-7"/></>:name==='play'?<path d="m9 5 10 7-10 7z"/>:name==='grid'?<><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>:name==='file'?<><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 12h6M9 16h6"/></>:<path d="M5 12h14m-5-5 5 5-5 5"/>}</svg>;
}

function App(){
 const [view,setView]=useState<View>(viewFromHash);
 const [fixtures,setFixtures]=useState<Fixtures|null>(null),[error,setError]=useState('');
 const [variant,setVariant]=useState('local_dedup'),[amount,setAmount]=useState(100000),[operationId,setOperationId]=useState('capture-001');
 const [campaign,setCampaign]=useState<Campaign|null>(null),[selected,setSelected]=useState<string|null>(null);
 const [job,setJob]=useState<Job|null>(null),[busy,setBusy]=useState(false),[recorded,setRecorded]=useState(false);
 const [comparison,setComparison]=useState<Case|null>(null),[replayed,setReplayed]=useState<Case|null>(null);
 const [comparisonTarget,setComparisonTarget]=useState<Target>({}),[replayTarget,setReplayTarget]=useState<Target>({});
 const [history,setHistory]=useState<{id:string;variant:string;lifecycle:string}[]>([]);
 const [token,setToken]=useState(()=>sessionStorage.getItem('stateproof-token')||'');
 const epoch=useRef(0);

 async function api<T>(url:string,body?:unknown):Promise<T>{
  const response=await fetch('/api'+url,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{detail=`HTTP ${response.status}`}throw new Error(typeof detail==='string'?detail:JSON.stringify(detail))}
  return response.json();
 }
 async function refreshCampaign(id:string,requestEpoch:number){
  try{const saved=await api<Campaign>('/campaigns/'+id);if(epoch.current===requestEpoch){setCampaign(saved);return saved}}catch(cause){if(epoch.current===requestEpoch)setError(String(cause))}
 }
 async function applyJob(next:Job,requestEpoch:number){
  if(epoch.current!==requestEpoch)return;
  setJob(next);
  let saved:Campaign|undefined;
  if(next.campaignId)saved=await refreshCampaign(next.campaignId,requestEpoch);
  if(epoch.current!==requestEpoch)return;
  if(next.sourceCaseId)setSelected(next.sourceCaseId);
  if(next.lifecycle==='RUNNING')return;
  if(next.error)setError(next.error);
  if(next.kind==='reduce'&&saved?.reduction)setSelected(saved.reduction.case.worldId);
  if(next.kind==='replay'){
   setReplayed(next.result as Case);setReplayTarget({id:next.sourceCaseId,label:next.sourceCaseLabel});
  }
  if(next.kind==='comparison'){
   setComparison(next.result as Case);setComparisonTarget({id:next.sourceCaseId,label:next.sourceCaseLabel});
  }
  setHistory(await api('/campaigns'));
 }
 async function connect(){
  const requestEpoch=++epoch.current;
  try{
   const f=await api<Fixtures>('/fixtures');
   const savedHistory=await api<{id:string;variant:string;lifecycle:string}[]>('/campaigns');
   if(epoch.current!==requestEpoch)return;
   setFixtures(f);setHistory(savedHistory);setError('');
   const resumeId=f.activeJob||sessionStorage.getItem('stateproof-job');
   if(resumeId){
    try{setRecorded(true);const active=await api<Job>('/jobs/'+resumeId);await applyJob(active,requestEpoch)}
    catch{sessionStorage.removeItem('stateproof-job')}
   }
  }catch(cause){if(epoch.current===requestEpoch){setFixtures(null);setError('Cannot connect to the runner. '+String(cause))}}
 }
 useEffect(()=>{
  const onHash=()=>{
   if(window.location.hash&&window.location.hash!=='#lab'&&window.location.hash!=='#evidence')window.history.replaceState(null,'','#lab');
   setView(viewFromHash());
  };
  if(!window.location.hash)window.history.replaceState(null,'','#lab');
  onHash();window.addEventListener('hashchange',onHash);void connect();
  return()=>window.removeEventListener('hashchange',onHash);
 },[]);
 useEffect(()=>{
  if(!job||job.lifecycle!=='RUNNING')return;
  let stopped=false;const jobId=job.id, requestEpoch=epoch.current;
  const tick=async()=>{try{const next=await api<Job>('/jobs/'+jobId);if(!stopped&&epoch.current===requestEpoch)await applyJob(next,requestEpoch)}catch(cause){if(!stopped&&epoch.current===requestEpoch)setError(String(cause))}};
  const timer=window.setInterval(()=>void tick(),700);void tick();
  return()=>{stopped=true;window.clearInterval(timer)};
 },[job?.id,job?.lifecycle]);

 const running=busy||job?.lifecycle==='RUNNING', disabled=running||!fixtures||fixtures.readOnly;
 const displayCases=[...(campaign?.cases||[]),...(campaign?.reduction?[campaign.reduction.case]:[])];
 const current=displayCases.find(item=>item.worldId===selected)||campaign?.cases.find(item=>item.verdict===FAIL)||campaign?.cases.at(-1)||campaign?.reduction?.case;
 const operation=campaign?.operation;
 const captures=current?.observation?.ledger.filter(row=>row.operationId===operation?.operationId)||[];
 const total=captures.reduce((sum,row)=>sum+row.amountMinor,0);
 const failure=campaign?.cases.some(item=>item.verdict===FAIL);
 const comparisonSource=displayCases.find(item=>item.worldId===comparisonTarget.id);
 const timedEvents=current?.events.filter(item=>['delivery','effect_committed','worker_terminated','ack'].includes(item.type))||[];

 async function act(path:string,body:unknown={}){
  const requestEpoch=++epoch.current;setBusy(true);setError('');
  try{const next=await api<Job>(path,body);sessionStorage.setItem('stateproof-job',next.id);if(epoch.current===requestEpoch)setJob(next)}catch(cause){if(epoch.current===requestEpoch)setError(String(cause))}finally{if(epoch.current===requestEpoch)setBusy(false)}
 }
 async function run(){setCampaign(null);setSelected(null);setComparison(null);setReplayed(null);setRecorded(false);await act('/campaigns',{variant,operation:{operationId,orderId:'order-001',amountMinor:amount,currency:'INR'}})}
 async function restore(id:string){
  const requestEpoch=++epoch.current;sessionStorage.removeItem('stateproof-job');setJob(null);setComparison(null);setReplayed(null);setError('');
  if(!id){setCampaign(null);setRecorded(false);setSelected(null);return}
  try{const saved=await api<Campaign>('/campaigns/'+id);if(epoch.current===requestEpoch){setCampaign(saved);setRecorded(true);setSelected(saved.reduction?.case.worldId||null)}}catch(cause){if(epoch.current===requestEpoch)setError(String(cause))}
 }
 async function download(){
  if(!campaign)return;setBusy(true);
  try{const response=await fetch(`/api/campaigns/${campaign.id}/evidence`);if(!response.ok)throw new Error(await response.text());const url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');anchor.href=url;anchor.download=`stateproof-${campaign.id}.zip`;anchor.click();URL.revokeObjectURL(url)}catch(cause){setError(String(cause))}finally{setBusy(false)}
 }
 const historyPicker=<div className="history"><select aria-label="Saved campaigns" value={recorded?campaign?.id||'':''} disabled={running} onChange={event=>void restore(event.target.value)}><option value="">Open a saved campaign</option>{history.map(item=><option key={item.id} value={item.id}>{item.variant} · {item.id.slice(0,8)} · {item.lifecycle.toLowerCase()}</option>)}</select></div>;

 return <div className="shell">
  <aside className="sidebar"><a href="#lab" className="brand"><span className="brandmark"><Icon name="logo"/></span>StateProof<span className="version">/ 01</span></a><div className="workspace-label">ENGINEERING WORKSPACE</div><a className={'nav '+(view==='lab'?'active':'')} aria-current={view==='lab'?'page':undefined} href="#lab"><Icon name="grid"/>Retry lab<span>01</span></a><a className={'nav '+(view==='evidence'?'active':'')} aria-current={view==='evidence'?'page':undefined} href="#evidence"><Icon name="file"/>Evidence explorer</a><div className="rail-note"><div className="rail-symbol">↻</div><strong>Trust the effect.<br/>Test the retry.</strong><p>Real worker failures.<br/>Independent durable evidence.</p></div><div className="rail-bottom"><span className="tiny-dot"/>Local / CI runner<div>Seeded payment benchmark</div></div></aside>
  <div className="body"><header><div>Workspace <span className="slash">/</span> <strong>{view==='lab'?'Payment capture':'Evidence explorer'}</strong></div><div className="connection"><i className={fixtures?'online':''}/>{fixtures?'Runner connected':'Connecting to runner'}<span className="header-tag">BOUNDED EXPLORATION</span></div></header>
   <main id={view}>
    <div className="title-row"><div><div className="eyebrow">{view==='lab'?'RETRY CORRECTNESS LAB':'RECORDED CAMPAIGNS'}</div><h1>{view==='lab'?'One payment. Every retry counts.':'Inspect durable evidence.'}</h1><p className="subtitle">{view==='lab'?'Interrupt a real consumer. Redeliver the operation. Inspect what actually happened.':'Open a saved campaign, select any direct or reduced case, and inspect its outcome.'}</p></div><span className="sample-chip">SAMPLE FIXTURE <b>payment-v1</b></span></div>
    {error&&<div role="alert" className="error"><strong>Action needs attention</strong><span>{error}</span><button onClick={()=>void connect()}>Reconnect</button></div>}
    {fixtures?.readOnly&&<div className="notice">Read-only deployment · Explore saved evidence below. Execution is available to the operator through the CLI.</div>}
    {fixtures?.tokenRequired&&<label className="token">Operator token <input type="password" value={token} onChange={event=>{setToken(event.target.value);sessionStorage.setItem('stateproof-token',event.target.value)}} placeholder="Required to run tests"/></label>}
    {view==='lab'&&<section className="config panel"><div className="section-heading"><span className="step">01</span><h2>Configure the experiment</h2><span className="muted">Trusted fixture · real execution</span></div><div className="config-grid"><label>Fixture<select disabled><option>Payment capture / INR</option></select></label><label>Implementation<select value={variant} disabled={running} onChange={event=>setVariant(event.target.value)}>{Object.keys(fixtures?.variants||{local_dedup:''}).map(item=><option key={item} value={item}>{item}{item==='stable_key'?' · repaired benchmark':''}</option>)}</select></label><label>Payment amount <span>(paise)</span><input type="number" min="1" max="100000000" value={amount} disabled={running} onChange={event=>setAmount(Number(event.target.value))}/></label><button className="primary run" disabled={disabled} onClick={()=>void run()}><Icon name="play"/>{running?'Execution in progress':'Run exploration'}</button></div><div className="config-footer"><span className="code-note">{fixtures?.variants[variant]||'Loading implementation details…'}</span><div className="bounds"><span>1 worker</span><span>1 crash / case</span><span>1 retry</span><span>15s / attempt</span></div></div><details className="operation-options"><summary>Operation identity</summary><label>Logical operation ID<input value={operationId} pattern="[a-zA-Z0-9_-]{1,64}" onChange={event=>setOperationId(event.target.value)} disabled={running}/></label><p>Remains stable across attempts. Use a different ID for a separately intended capture.</p></details></section>}
    <div className="section-heading results-heading"><span className="step">{view==='lab'?'02':'01'}</span><h2>{view==='lab'?'Execution & evidence':'Campaign history'}</h2>{historyPicker}</div>
    {view==='lab'&&<div className="control-grid">{['Normal delivery','Ordinary duplicate delivery'].map((label,index)=><div className="control-card" key={label}><span className="control-number">0{index+1}</span><div><strong>{label}</strong><p>{index===0?'One operation, one delivery':'Same operation delivered twice'}</p></div><Badge value={campaign?.cases[index]?.verdict}/></div>)}</div>}
    {job&&<div className="job-status" role="status"><strong>{pretty(job.kind)} · {pretty(job.lifecycle)}</strong>{job.sourceCaseId&&<span>Target: {job.sourceCaseLabel||'case'} · {job.sourceCaseId.slice(0,8)}</span>}{job.error&&<span>{job.error}</span>}{job.lifecycle==='RUNNING'&&<button onClick={()=>void api('/jobs/'+job.id+'/cancel',{}).catch(cause=>setError(String(cause)))}>Cancel job</button>}</div>}
    {!campaign&&replayed&&<div className="replay-result"><Badge value={replayed.verdict}/><strong>{replayTarget.id?`Target: ${replayTarget.label||'case'} · ${replayTarget.id.slice(0,8)}`:'Standalone manifest replay'}</strong><span>{replayed.replayMatched?'Replay matched the saved evidence contract.':'Replay did not establish a match. Inspect diagnostics.'}</span></div>}
    {!campaign&&comparison&&<div className="replay-result"><Badge value={comparison.verdict}/><strong>Standalone manifest comparison · stable_key</strong><span>{comparison.diagnostics?.join(' · ')}</span></div>}
    {!campaign?<section className="empty panel"><div className="empty-icon"><Icon name={view==='lab'?'logo':'file'}/></div><h3>{running?'Restoring the active job…':view==='lab'?'A passing test is only the beginning.':'No campaign selected.'}</h3><p>{running?'Status and results will remain available if this page reloads.':view==='lab'?'Run the controls, then explore each checkpoint observed in a normal execution.':'Choose a saved campaign above. Evidence remains available without starting a new run.'}</p>{view==='lab'&&<div className="empty-flow"><span>Deliver</span><b>→</b><span>Interrupt</span><b>→</b><span>Retry</span><b>→</b><span>Verify</span></div>}</section>:<>
     <div className="campaign-status"><div><span className={'status-dot '+(campaign.lifecycle==='RUNNING'?'pulse':'')}/><strong>{campaign.lifecycle==='CANCELLED'?'Campaign cancelled':campaign.lifecycle==='INTERRUPTED'?'Campaign interrupted':campaign.lifecycle==='FAILED'?'Campaign failed':campaign.lifecycle==='RUNNING'?'Running exploration':recorded?'Saved campaign':'Campaign recorded'}</strong><code>{campaign.id.slice(0,12)}</code></div><div><span>{campaign.executed||0} cases executed</span><span>{campaign.counts[FAIL]||0} violations</span><span>{campaign.counts.INCONCLUSIVE||0} inconclusive</span><span>{(campaign.counts.HARNESS_ERROR||0)+(campaign.counts.DIVERGED||0)} errors / diverged</span><span>{campaign.discoveredCheckpoints.length} observed sites</span>{campaign.lifecycle==='RUNNING'&&job?.kind==='campaign'&&<button className="cancel" onClick={()=>void api('/jobs/'+job.id+'/cancel',{}).catch(cause=>setError(String(cause)))}>Cancel run</button>}</div></div>
     {!!campaign.diagnostics?.length&&<div className="notice">{campaign.diagnostics.join(' · ')}</div>}
     <div className="experiment-grid"><section className="case-panel panel"><div className="panel-title"><h3>Executed cases</h3><span>{displayCases.length}</span></div><div className="case-list">{displayCases.map((item,index)=><button key={item.worldId} className={'case '+(current?.worldId===item.worldId?'selected':'')} aria-pressed={current?.worldId===item.worldId} onClick={()=>setSelected(item.worldId)}><span className={'case-dot '+tone(item.verdict)}/><div><strong>{campaign.reduction?.case.worldId===item.worldId?'Reduced · '+item.label:item.label.replace('crash at ','')}</strong><small>{campaign.reduction?.case.worldId===item.worldId?'1-minimal regression case':item.label.startsWith('crash')?'Worker kill + redelivery':item.label==='mixed workload'?'Includes unrelated work':'Control'} · {item.elapsedSeconds.toFixed(1)}s</small></div><span className="case-index">{String(index+1).padStart(2,'0')}</span></button>)}</div><div className="case-foot">Bounded coverage of observed sites.<br/>No claim about the full state space.</div></section>
      <section className="outcome panel"><div className="panel-title"><div><span className="eyebrow">BUSINESS OUTCOME</span><h3>{current?.label||'Waiting for the first result'}</h3></div><Badge value={current?.verdict}/></div><div className="money-grid"><div><span>Intended capture</span><strong>{money(operation?.amountMinor||0,operation?.currency)}</strong><small>One logical operation</small></div><div className={tone(current?.verdict)}><span>Provider captured</span><strong>{current?.observation?money(total,operation?.currency):'—'}</strong><small>{current?.observation?`${captures.length} committed effect${captures.length===1?'':'s'}`:'Evidence unavailable'}</small></div></div>
       {current?.verdict===FAIL&&<div className="violation-note"><span>!</span><div><strong>{captures.length>1?'A retry repeated the external effect.':'Local completion does not match the provider.'}</strong><p>{captures.length>1?'The provider ledger contains more than one capture for this operation.':'A paid operation must have exactly one matching capture.'}</p></div></div>}
       {!!current?.diagnostics.length&&<div className="notice">{current.diagnostics.join(' · ')}</div>}
       <div className="timeline-header"><h4>Recorded execution</h4><span>Ordered events · {current?.worldId.slice(0,8)}</span></div><ol className="timeline">{timedEvents.map((item,index)=><li key={index} className={item.type==='worker_terminated'?'crash':item.type==='effect_committed'?'effect':''}><span className="event-mark"/><span className="event-number">{String(index+1).padStart(2,'0')}</span><div><strong>{item.type==='delivery'?item.attempt===2?'Retry delivered':'Operation delivered':item.type==='effect_committed'?'Provider effect committed':item.type==='worker_terminated'?'Worker terminated':'Delivery acknowledged'}</strong><small>{item.type==='worker_terminated'?item.boundary?.checkpoint:item.operationId}</small></div><span className="event-value">{item.type==='effect_committed'?money(item.amountMinor||0,item.currency):item.type==='delivery'?`attempt ${item.attempt}`:item.type==='worker_terminated'?'process killed':'ack'}</span></li>)}</ol>
      </section></div>
     <div className="state-grid"><section className="panel"><div className="panel-title"><h3>Independent provider ledger</h3><span className="storage-label">SQLite · durable</span></div><div className="table-scroll"><table><thead><tr><th>Effect</th><th>Operation</th><th>Amount</th><th>Provider key</th></tr></thead><tbody>{current?.observation?.ledger.map(row=><tr key={row.effectId}><td>#{row.effectId}</td><td><code>{row.operationId}</code></td><td>{money(row.amountMinor,row.currency)}</td><td className="key-cell" title={row.idempotencyKey||'No key'}>{row.idempotencyKey||<span className="muted">No key</span>}</td></tr>)}</tbody></table>{!current?.observation?.ledger.length&&<p className="table-empty">{current?.observation?'No committed captures.':'No provider evidence available.'}</p>}</div></section><section className="panel"><div className="panel-title"><h3>Application state</h3><span className="storage-label">PostgreSQL</span></div>{current?.observation?.application.length?<div className="app-rows">{current.observation.application.map((row,index)=><div key={index}><code>{String(row.operation_id)}</code><span className="local-status">{String(row.status)}</span><small>recorded effect: {String(row.effect_id??'none')}</small></div>)}</div>:<p className="table-empty">{current?.observation?'No local completion recorded.':'Application evidence unavailable.'}</p>}<p className="state-foot">Local status alone cannot establish payment correctness.</p></section></div>
     <section className="panel regression"><div className="section-heading"><span className="step">{view==='lab'?'03':'02'}</span><h2>Turn the failure into a regression case</h2></div><div className="action-row"><div><h3>{campaign.reduction?`${campaign.reduction.beforeActions} → ${campaign.reduction.afterActions} actions`:'Keep only what reproduces the failure.'}</h3><p>{campaign.reduction?(campaign.reduction.oneMinimal?'Verified 1-minimal under prerequisite-preserving action deletion.':'Reduction incomplete; minimality not established.'):'Delete actions, rerun in fresh worlds, retain the same property and operation.'}</p></div><div className="actions"><button disabled={disabled||!failure} onClick={()=>void act(`/campaigns/${campaign.id}/reduce`)}>Reduce workload</button><button disabled={disabled||!current} onClick={()=>void act('/replays',{campaignId:campaign.id,caseId:current?.worldId})}>Replay selected case</button><button className="dark" disabled={disabled||!current} onClick={()=>void act('/replays',{campaignId:campaign.id,caseId:current?.worldId,comparisonVariant:'stable_key'})}>Compare selected with stable key <Icon name="arrow"/></button></div></div>
      {replayed&&<div className="replay-result"><Badge value={replayed.verdict}/><strong>Target: {replayTarget.label||'case'} · {replayTarget.id?.slice(0,8)}</strong><span>{replayed.replayMatched?'Replay matched the saved evidence contract.':'Replay did not establish a match. Inspect diagnostics.'}</span><span>{replayed.diagnostics?.join(' · ')}</span></div>}
      {comparison&&<div className="comparison"><div><span className="eyebrow">SELECTED BENCHMARK · {comparisonTarget.id?.slice(0,8)}</span><h3>{comparisonTarget.label||comparisonSource?.label||campaign.variant}</h3><Badge value={comparisonSource?.verdict}/><strong className="text-fail">{money(comparisonSource?.observation?.ledger.filter(row=>row.operationId===operation?.operationId).reduce((sum,row)=>sum+row.amountMinor,0)||0,operation?.currency)} captured</strong><code>{campaign.variant==='mark_before'?'persist paid → call provider':'provider key absent or changes across attempts'}</code></div><div><span className="eyebrow">SAME FAULT PLAN · REPAIR COMPARISON</span><h3>stable_key</h3><Badge value={comparison.verdict}/><strong>{comparison.observation?money(comparison.observation.ledger.filter(row=>row.operationId===operation?.operationId).reduce((sum,row)=>sum+row.amountMinor,0)||0,operation?.currency)+' captured':'Evidence unavailable'}</strong><code>key = "stateproof:payment:v1:" + operationId</code><p>Provider deduplicates the logical capture; local success is written afterward. Selected benchmark repair, not automatic code repair.</p></div></div>}
      <details className="technical"><summary>Property checks & replay details</summary><div>{current?.properties.map((item,index)=><p key={index}><span className={item.passed?'text-pass':'text-fail'}>{item.passed?'PASS':'FAIL'}</span> <code>{item.property}</code> · {item.operationId} — {item.detail}</p>)}</div><code>Build SHA-256: {current?.buildDigest}</code><p>Replay normalizes process IDs, ports and world names; meaningful operation, amount, key, durable outcome and fault relationships remain. This is not full-machine determinism.</p></details>
      <div className="export-row"><div><Icon name="file"/><span>Manifest, observations, SQLite ledgers & SHA-256 checksums</span></div><button disabled={running||campaign.lifecycle==='RUNNING'} onClick={()=>void download()}>Download evidence ↓</button></div></section>
    </>}
    <footer><span><Icon name="logo"/>StateProof <b>·</b> Evidence over assumptions.</span><span>Seeded benchmark. Bounded results. No production-bug discovery claim.</span></footer>
   </main>
  </div>
 </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
