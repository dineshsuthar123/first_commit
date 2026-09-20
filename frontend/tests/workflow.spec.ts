import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';

test('real exploration, reduction, replay, repair comparison and evidence download',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('/');
 await expect(page.getByText('Runner connected')).toBeVisible();
 await expect(page.getByText('A passing test is only the beginning.')).toBeVisible();
 await page.screenshot({path:'../data/browser-results/empty.png',fullPage:true});
 await page.getByRole('button',{name:'Run exploration',exact:true}).click();
 await expect(page.getByText('Campaign recorded',{exact:true})).toBeVisible({timeout:90000});
 await expect(page.getByText('₹2,000',{exact:true})).toBeVisible();
 await expect(page.getByText('Worker terminated',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Reduce workload',exact:true}).click();
 await expect(page.getByText('4 → 2 actions')).toBeVisible({timeout:45000});
 await page.getByRole('button',{name:'Replay case',exact:true}).click();
 await expect(page.getByText('Replay matched the saved evidence contract.')).toBeVisible({timeout:30000});
 await page.getByRole('button',{name:'Compare stable key'}).click();
 await expect(page.getByText('₹1,000 captured',{exact:true})).toBeVisible({timeout:30000});
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'../data/browser-results/verified.png',fullPage:true});
 const downloadPromise=page.waitForEvent('download');
 await page.getByRole('button',{name:'Download evidence'}).click();
 const download=await downloadPromise;await download.saveAs('../data/browser-results/browser-evidence.zip');
 expect((await fs.readFile('../data/browser-results/browser-evidence.zip')).subarray(0,2).toString()).toBe('PK');
 expect(errors).toEqual([]);
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'../data/browser-results/mobile.png',fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test('connection failure, recovery and cancellation remain visible',async({page})=>{
 await page.route('**/api/fixtures',route=>route.abort());
 await page.goto('/');
 await expect(page.getByRole('alert')).toContainText('Cannot connect');
 await page.unroute('**/api/fixtures');
 await page.getByRole('button',{name:'Reconnect'}).click();
 await expect(page.getByText('Runner connected')).toBeVisible();
 await page.getByRole('button',{name:'Run exploration',exact:true}).click();
 await page.getByRole('button',{name:'Cancel run',exact:true}).click({timeout:30000});
 await expect(page.getByText('Campaign cancelled',{exact:true})).toBeVisible({timeout:30000});
 await page.screenshot({path:'../data/browser-results/cancelled.png',fullPage:true});
});
