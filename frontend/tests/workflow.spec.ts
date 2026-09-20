import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';

test('real exploration, explicit reduction replay, repair comparison and evidence download',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(String(error)));
 const replayBodies:{campaignId?:string;caseId?:string;comparisonVariant?:string}[]=[];
 page.on('request',request=>{if(request.url().endsWith('/api/replays')&&request.method()==='POST')replayBodies.push(request.postDataJSON())});
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
 const reduced=page.getByRole('button',{name:/Reduced ·/});
 await expect(reduced).toHaveAttribute('aria-pressed','true');
 const reducedId=(await page.locator('.timeline-header span').textContent())?.split(' · ')[1];

 await page.getByRole('link',{name:'Evidence explorer'}).click();
 await expect(page.getByRole('link',{name:'Evidence explorer'})).toHaveAttribute('aria-current','page');
 await expect(reduced).toHaveAttribute('aria-pressed','true');
 await page.goBack();
 await expect(page.getByRole('link',{name:/Retry lab/})).toHaveAttribute('aria-current','page');
 await expect(reduced).toHaveAttribute('aria-pressed','true');

 await page.getByRole('button',{name:'Replay selected case',exact:true}).click();
 await page.reload();
 await expect(page.getByText(/Target: reduced failure/)).toBeVisible({timeout:30000});
 await expect(page.getByText('Replay matched the saved evidence contract.')).toBeVisible({timeout:30000});
 expect(replayBodies[0].caseId?.slice(0,8)).toBe(reducedId);
 await page.getByRole('button',{name:'Compare selected with stable key'}).click();
 await expect(page.getByText('₹1,000 captured',{exact:true})).toBeVisible({timeout:30000});
 expect(replayBodies[1].caseId).toBe(replayBodies[0].caseId);

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

test('hash navigation supports deep links, empty evidence, back and forward',async({page})=>{
 await page.route('**/api/fixtures',route=>route.fulfill({json:{variants:{local_dedup:'fixture'},readOnly:false,tokenRequired:false,activeJob:null}}));
 await page.route('**/api/campaigns',route=>route.fulfill({json:[]}));
 await page.goto('/#evidence');
 await expect(page.getByRole('link',{name:'Evidence explorer'})).toHaveAttribute('aria-current','page');
 await expect(page.getByRole('heading',{name:'Inspect durable evidence.'})).toBeVisible();
 await expect(page.getByLabel('Saved campaigns')).toBeVisible();
 await expect(page.getByRole('heading',{name:'No campaign selected.'})).toBeVisible();
 await page.getByRole('link',{name:/Retry lab/}).click();
 await expect(page.getByRole('heading',{name:'One payment. Every retry counts.'})).toBeVisible();
 await page.goBack();
 await expect(page.getByRole('heading',{name:'Inspect durable evidence.'})).toBeVisible();
 await page.goForward();
 await expect(page.getByRole('heading',{name:'One payment. Every retry counts.'})).toBeVisible();
 await page.goto('/#unknown');
 await expect(page).toHaveURL(/#lab$/);
 await expect(page.getByRole('link',{name:/Retry lab/})).toHaveAttribute('aria-current','page');
});

test('restored failed derived job shows campaign context and failure',async({page})=>{
 const campaigns=await (await page.request.get('/api/campaigns')).json();
 test.skip(!campaigns.length,'requires a recorded campaign from the real workflow');
 const campaign=await (await page.request.get('/api/campaigns/'+campaigns[0].id)).json();
 const source=campaign.reduction?.case||campaign.cases[0];
 const failedId='f'.repeat(32);
 await page.route('**/api/fixtures',route=>route.fulfill({json:{variants:{local_dedup:'fixture'},readOnly:false,tokenRequired:false,activeJob:failedId}}));
 await page.route('**/api/jobs/'+failedId,route=>route.fulfill({json:{id:failedId,kind:'replay',lifecycle:'FAILED',error:'RuntimeError: injected browser failure',result:null,campaignId:campaign.id,sourceCaseId:source.worldId,sourceCaseLabel:source.label}}));
 await page.goto('/');
 await expect(page.getByRole('status')).toContainText('replay · failed');
 await expect(page.getByRole('status')).toContainText(source.worldId.slice(0,8));
 await expect(page.getByRole('alert')).toContainText('injected browser failure');
 await expect(page.locator('.campaign-status code')).toContainText(campaign.id.slice(0,12));
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
