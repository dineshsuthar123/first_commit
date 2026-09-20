// Capture genuine local execution. Captions are recording annotations, not app results.
import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const report=JSON.parse(await fs.readFile('../docs/replay-validation.json','utf8'));
const browser=await chromium.launch();
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:'../data/demo-raw',size:{width:1440,height:1000}}});
const started=Date.now();
const page=await context.newPage();
const video=page.video();
async function at(seconds){const remaining=seconds*1000-(Date.now()-started);if(remaining>0)await new Promise(r=>setTimeout(r,remaining));}
async function caption(text){
 await page.evaluate(text=>{
  let box=document.getElementById('recording-caption');
  if(!box){box=document.createElement('div');box.id='recording-caption';box.style.cssText='position:fixed;bottom:18px;left:260px;right:28px;padding:16px 24px;background:#132e2bf2;color:#f4f8f5;border:1px solid #91b79d;border-radius:8px;z-index:99999;font:16px/1.5 system-ui;box-shadow:0 6px 30px #0002;pointer-events:none';document.body.appendChild(box)}
  box.textContent='DEMO CAPTION · '+text;
 },text);
 console.log(`${((Date.now()-started)/1000).toFixed(1)}s ${text}`);
}
try{
 await page.goto('http://127.0.0.1:8000');
 await page.getByText('Runner connected').waitFor();
 await caption('StateProof — bounded retry-correctness testing. Seeded payment benchmark; real worker failure and durable evidence.');
 await at(15);await page.getByRole('button',{name:'Run exploration',exact:true}).click();
 await caption('Normal delivery and ordinary duplicate delivery pass. The runner discovers sites from execution, then kills the worker at each observed boundary.');
 await page.getByText('Campaign recorded',{exact:true}).waitFor({timeout:90000});
 await at(35);await page.getByText('BUSINESS OUTCOME',{exact:true}).scrollIntoViewIfNeeded();
 await caption('₹1,000 intended. ₹2,000 actually captured. The provider committed before the worker died; retry repeated the charge.');
 await at(60);await page.getByText('Independent provider ledger',{exact:true}).scrollIntoViewIfNeeded();
 await caption('Independent SQLite ledger beside PostgreSQL application state. Local success alone cannot establish payment correctness.');
 await at(82);await page.getByRole('button',{name:'Reduce workload',exact:true}).click();
 await page.getByText('4 → 2 actions',{exact:true}).waitFor({timeout:30000});
 await caption('Four real workload actions reduce to two. Fresh-world deletion checks preserve the same violated property and operation. 1-minimal under the supported grammar.');
 await at(97);await page.getByRole('button',{name:'Replay case',exact:true}).click();
 await page.getByText('Replay matched the saved evidence contract.').waitFor({timeout:30000});
 await caption('Replay matched the saved build and semantic boundaries. The ZIP exports the manifest, durable observations and SHA-256 checksums.');
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download evidence'}).click();
 await (await downloadPromise).saveAs('../data/demo-evidence.zip');
 await at(108);await page.getByRole('button',{name:'Compare stable key'}).click();
 await page.getByText('₹1,000 captured',{exact:true}).waitFor({timeout:30000});
 await page.getByText('SAME FAULT PLAN · REPAIR COMPARISON',{exact:true}).scrollIntoViewIfNeeded();
 await caption('Same fault plan, stable logical-operation key: ₹1,000 captured. This is an explicit benchmark repair comparison, not automatic code repair.');
 await at(134);await caption(`Measured evidence: ${report.faultyMatched}/30 faulty replays matched; ${report.fixedPassed}/30 stable-key comparisons passed. Worker runtime: Amazon Corretto 21.0.8.9.1.`);
 await at(155);await caption('AWS status: Corretto was used in actual local execution. EC2 + S3 are prepared but NOT deployed; approved account, region, budget and authorization are pending.');
 await at(165);await page.evaluate(()=>window.scrollTo(0,0));await caption('One consumer · one provider · one retry · at most one crash. Bounded fixture results, not proof about arbitrary distributed systems.');
 await at(173);
}finally{await context.close();await browser.close();}
await fs.mkdir('../docs',{recursive:true});
await fs.copyFile(await video.path(),'../docs/demo.webm');
console.log('Saved docs/demo.webm — silent recording with captions; no cloud execution claim.');
