import {chromium} from '@playwright/test';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
const browser=await chromium.launch();
const page=await browser.newPage({viewport:{width:1440,height:1000}});
try{
 await page.goto(pathToFileURL(path.resolve('../docs/demo.webm')).href);
 await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
 const duration=await page.evaluate(()=>document.querySelector('video').duration);
 if(duration<170||duration>175)throw new Error(`Demo duration outside bounds: ${duration}`);
 for(const seconds of [45,100,160]){
  await page.evaluate(async seconds=>{const v=document.querySelector('video');v.pause();await new Promise((resolve,reject)=>{v.onseeked=resolve;v.onerror=()=>reject(v.error);v.currentTime=seconds})},seconds);
  await page.screenshot({path:`../data/demo-frame-${seconds}.png`});
 }
 const result={durationSeconds:duration,sampledPlaybackSeconds:[45,100,160],mediaError:await page.evaluate(()=>document.querySelector('video').error?.message||null),audio:'none; captioned real local execution',cloud:'explicitly labelled not deployed'};
 await fs.writeFile('../docs/video-validation.json',JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result));
}finally{await browser.close()}
