// Real Chromium main-thread/worker parity against an existing timing package.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';

const [oldRoot,newRoot]=process.argv.slice(2).map(p=>path.resolve(p));
if (!oldRoot || !newRoot) throw new Error('Provide old and new unpacked package roots');
const server=createServer(async(req,res)=>{
  try {
    if(req.url==='/') {res.setHeader('Content-Type','text/html');res.end('<!doctype html>');return;}
    const match=/^\/(old|new)\/([a-zA-Z0-9_.-]+)$/.exec(req.url);
    if(!match) {res.writeHead(404);res.end();return;}
    const file=path.join(match[1]==='old'?oldRoot:newRoot,match[2]);
    res.setHeader('Content-Type',file.endsWith('.json')?'application/json':'text/javascript');
    res.end(await readFile(file));
  } catch(error) {res.writeHead(404);res.end(String(error));}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage(); await page.goto(`http://127.0.0.1:${server.address().port}`);
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const result=await page.evaluate(async()=>{
    const old=await import('/old/visual-state.js'),next=await import('/new/visual-state.js');
    const times=[0,30,34.4584,37.5757,42.8002,44.3501,54,287.2143,1,44.3501,0];
    const states=times.map(t=>({time:t,equal:JSON.stringify(old.getVisualState(t))===JSON.stringify(next.getVisualState(t))}));
    const worker=new Worker('/new/worker-example.js',{type:'module'});
    const workerResults=[];
    try {
      for(const [id,time] of times.entries()) {
        const response=await new Promise((resolve,reject)=>{
          worker.onmessage=e=>resolve(e.data);worker.onerror=reject;worker.postMessage({id,time});
        });
        workerResults.push(JSON.stringify(response.timing)===JSON.stringify(next.getVisualState(time)));
      }
    } finally {worker.terminate();}
    return {states,workerResults,eventParity:JSON.stringify(old.getResponseEvents(30,54,10))===JSON.stringify(next.getResponseEvents(30,54,10))};
  });
  assert.deepEqual(errors,[]);assert.ok(result.states.every(s=>s.equal));
  assert.ok(result.workerResults.every(Boolean));assert.ok(result.eventParity);
  console.log(JSON.stringify({ok:true,...result}));
} finally {await browser.close();server.close();}
