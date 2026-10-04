// Capture the real Studio for release documentation; does not analyse or render a movie.
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';

const [base='http://127.0.0.1:8871',project,output='docs/demo/beathi-studio-v015.png']=process.argv.slice(2);
if(!/^[0-9a-f]{12}$/.test(project??''))throw Error('Provide an existing project ID');
const browser=await chromium.launch({channel:'msedge'});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1080},deviceScaleFactor:1});
 await context.addInitScript(project=>localStorage.setItem('beathi.movie.session.1',JSON.stringify({name:'Music project',projectId:project,seed:17,template:'material-mix'})),project);
 const page=await context.newPage();await page.goto(base+'/app/');
 await page.waitForFunction(()=>document.querySelector('iframe.mv-preview')?.contentWindow?.previewReady===true,{},{timeout:120000});
 fs.mkdirSync(path.dirname(output),{recursive:true});await page.screenshot({path:output,fullPage:true});
 await page.getByRole('button',{name:'中文',exact:true}).click();
 await page.screenshot({path:output.replace(/\.png$/,'-zh.png'),fullPage:true});
 console.log('Captured '+output);
}finally{await browser.close();}
