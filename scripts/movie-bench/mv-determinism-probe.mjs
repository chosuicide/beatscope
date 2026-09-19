import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http'; import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root=path.resolve(process.argv[2]);
const {chromium}=await import(pathToFileURL(process.env.BEATSCOPE_PLAYWRIGHT_MODULE).href);
const input=JSON.parse(fs.readFileSync(path.join(root,'input.json')));
const allowed=new Set(['mv-render.html','mv-frame.mjs','mv-visual.js','beatscope-runtime.js','input.json','plan.json']);
const publicInput=JSON.stringify({rhythm:input.rhythm,ranking:input.ranking});
const server=http.createServer((req,res)=>{const n=new URL(req.url,'http://local').pathname.slice(1)||'mv-render.html';
 if(!allowed.has(n)){res.writeHead(404).end();return;}
 res.setHeader('Content-Type',n.endsWith('.html')?'text/html':n.endsWith('.json')?'application/json':'text/javascript');
 res.end(n==='input.json'?publicInput:fs.readFileSync(path.join(root,n)));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,channel:process.env.BEATSCOPE_BROWSER_CHANNEL||(process.platform==='win32'?'msedge':'chromium'),args:['--enable-webgl','--ignore-gpu-blocklist']});
const grab=async()=>{const page=await browser.newPage({viewport:{width:1080,height:1080},deviceScaleFactor:1});
 const cdp=await page.context().newCDPSession(page);
 await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.waitForFunction(()=>window.ready,{},{timeout:45000});
 return {page,shot:async t=>{await page.evaluate(x=>window.renderAt(x),t);return Buffer.from((await cdp.send('Page.captureScreenshot',{format:'png',optimizeForSpeed:true,captureBeyondViewport:false})).data,'base64');}};};
const a=await grab(),b=await grab();
const times=[3.5,7.25,10.0];
for(const t of times){
 const sa=await a.shot(t),sb=await b.shot(t);
 const ra=await a.shot(t),rb=await b.shot(t);              // repeat on the same page
 const h=x=>createHash('sha256').update(x).digest('hex').slice(0,16);
 console.log(`t=${t}: pageA=${h(sa)} pageB=${h(sb)} A-again=${h(ra)} B-again=${h(rb)} | cross=${h(sa)===h(sb)} repeatA=${h(sa)===h(ra)} repeatB=${h(sb)===h(rb)}`);
}
await browser.close();server.close();
