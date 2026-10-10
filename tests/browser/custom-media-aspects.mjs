// Native frames preserve one focal subject; explicit radial effects cover rectangular viewports.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.argv[2]??'http://127.0.0.1:8773',root='output/playwright/custom-media-aspects';fs.mkdirSync(root,{recursive:true});
const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined});
const rows=[];
try{
 for(const gpu of [false,true]){
  const page=await browser.newPage();await page.goto(base+'/app/');
  const result=await page.evaluate(async gpu=>{
   const {createTemplateMovie}=await import('/movie-factory.mjs');
   const {createMaterialMovie}=await import('/material-frame.mjs');
   const images={};
   for(const [name,color]of [['fixture','#193674'],['green','#1bb064'],['old','#8b233f']]){
    const c=document.createElement('canvas');c.width=c.height=720;const q=c.getContext('2d');q.fillStyle=color;q.fillRect(0,0,720,720);
    if(name==='fixture'){q.fillStyle='#b46327';q.fillRect(20,30,90,230);q.fillStyle='#eeeeeb';q.beginPath();q.arc(560,360,46,0,7);q.fill();}
    images[name+'.png']=c.toDataURL();
   }
   const bird=document.createElement('canvas');bird.width=bird.height=1080;const birdCtx=bird.getContext('2d');
   birdCtx.fillStyle='#fd00fd';birdCtx.fillRect(0,0,1080,1080);birdCtx.fillStyle='#1bb064';birdCtx.fillRect(0,255,1080,570);images['bird.png']=bird.toDataURL();
   let timeline;
   const originalFetch=window.fetch;
   window.fetch=(url,...args)=>String(url).endsWith('material-timeline.json')?Promise.resolve(new Response(JSON.stringify(timeline))):images[String(url).split('/').at(-1)]?originalFetch(images[String(url).split('/').at(-1)]):originalFetch(url,...args);
   const asset=id=>({id,focus:{x:.5,y:.5,zoom:1,fit:'cover'},overrides:{}});
   const fixture={...asset('fixture'),focus:{x:.78,y:.5,zoom:1,fit:'cover'},overrides:{'9:16':{x:.78,y:.5,zoom:1,fit:'cover'}}};
   const settings={sourceId:'fixture',mode:'subject',subjectZoom:[1],phases:[0],attack:.1,settle:.2,phrase:[0,1.5],variant:1,sectors:10,group:'blue',palette:{base:'#fd00fd',accent:'#3b6686',secondary:'#adc3cc'}};
   const pixels=canvas=>{const c=document.createElement('canvas');c.width=canvas.width;c.height=canvas.height;c.getContext('2d').drawImage(canvas,0,0);return c;};
   const markerBounds=(data,w,h)=>{
    let x0=w,y0=h,x1=-1,y1=-1,count=0;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){const k=(y*w+x)*4;if(data[k]>220&&data[k+1]>220&&data[k+2]>220){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);count++;}}
    if(!count)throw Error('Missing focal subject');
    const bw=x1-x0+1,bh=y1-y0+1;
    if(Math.abs(bw-bh)>3||count/(bw*bh)<.70)throw Error('Ordinary shot repeated or stretched its circular subject');
    if(x0<3||y0<3||x1>w-4||y1>h-4)throw Error('Focal subject clipped at the edge');
    return {x:x0,y:y0,width:bw,height:bh};
   };
   const rows=[];
   try{for(const short of [720,1080])for(const [aspect,width,height]of [['1:1',short,short],['16:9',short*16/9,short],['9:16',short,short*16/9]]){
    const frames=Array.from({length:45},(_,i)=>({sinceCut:i/30,setup:{...settings},values:{}}));
    timeline={duration:1.5,assets:{fixture:{kind:'image',files:['fixture.png']}},frames};
    const media={assets:[fixture],slots:[{start:0,end:1.5,asset:'fixture',fixed:true}]};
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
    const render=await createTemplateMovie(canvas,{},null,{template:'material-mix',seed:17,media,mediaFiles:{fixture:'png'},output:{aspect}},{gpu});
    await render(.1);const snapshot=pixels(canvas),ctx=snapshot.getContext('2d'),full=ctx.getImageData(0,0,width,height).data;
    if(full.some((v,i)=>i%4===3&&v!==255))throw Error(aspect+' exposed an empty edge');
    const bounds=markerBounds(full,width,height);
    rows.push({gpu,aspect,width,height,bounds,acceleration:render.acceleration.effects,png:snapshot.toDataURL()});render.dispose();
   }
   for(const [aspect,width,height]of [['16:9',640,360],['9:16',360,640]]){
    timeline={duration:1.5,assets:{birdB:{kind:'image',files:[images['bird.png']]}},frames:Array.from({length:45},(_,i)=>({sinceCut:i/30,setup:{...settings,sourceId:'birdB',focal:[.53,.4]},values:{}}))};
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
    const render=await createMaterialMovie(canvas,timeline,'',{gpu});
    await render(.1);const snapshot=pixels(canvas),data=snapshot.getContext('2d').getImageData(0,0,width,height).data;
    for(let i=0;i<data.length;i+=4)if(data[i]>80||data[i+1]<140)throw Error('Cached bird padding leaked into native cover');
    rows.push({gpu,aspect,width,height,mode:'cached-bird',png:snapshot.toDataURL()});render.dispose();
   }
   for(const [aspect,width,height]of [['16:9',640,360],['9:16',360,640]])for(const mode of ['kaleid','centerFold','negative','trail','iris','liquidWindow']){
    const frames=Array.from({length:45},(_,i)=>({sinceCut:i/30,setup:{...settings,mode:mode==='negative'||mode==='trail'||mode==='iris'?'subject':mode,trail:mode==='trail',trailAxis:'x',trailDirection:1,surfaceBurst:mode==='negative',negativeBurstFrames:12,negativeWindowCount:2,surfacePose:0},values:{}}));
    if(mode==='iris')for(let i=15;i<45;i++){frames[i].sinceCut=(i-15)/30;frames[i].previous=true;frames[i].setup.transition='iris';}
    timeline={duration:1.5,assets:{fixture:{kind:'image',files:['fixture.png']}},frames};
    const media=mode==='iris'?{assets:[asset('old'),asset('green')],slots:[{start:0,end:.5,asset:'old',fixed:true},{start:.5,end:1.5,asset:'green',fixed:true}]}:{assets:[fixture],slots:[{start:0,end:1.5,asset:'fixture',fixed:true}]};
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
    const render=await createTemplateMovie(canvas,{},null,{template:'material-mix',seed:17,media,mediaFiles:{fixture:'png',old:'png',green:'png'},output:{aspect}},{gpu});
    const time=mode==='iris'?19/30:.1;await render(time);const first=pixels(canvas).toDataURL();await render(1);await render(time);if(first!==pixels(canvas).toDataURL())throw Error(`${gpu}:${aspect}:${mode} seek changed the picture`);
    const data=pixels(canvas).getContext('2d').getImageData(0,0,width,height).data;
    if(['kaleid','centerFold','iris'].includes(mode))for(const [x,y]of [[2,2],[width-3,2],[2,height-3],[width-3,height-3]]){
     const i=(y*width+x)*4;
     if(mode==='iris'?(data[i+1]<140||data[i]>80):(data[i]>240&&data[i+1]<10&&data[i+2]>240))throw Error(`${aspect}:${mode} missed a viewport corner`);
    }
    rows.push({gpu,aspect,width,height,mode,png:first});render.dispose();
   }}finally{window.fetch=originalFetch;}
   return rows;
  },gpu);
  rows.push(...result);await page.close();
 }
 assert.equal(rows.length,40);
 for(const row of rows){fs.writeFileSync(`${root}/${row.gpu?'gpu':'cpu'}-${row.mode??'subject'}-${row.width}x${row.height}.png`,Buffer.from(row.png.split(',')[1],'base64'));delete row.png;}
 fs.writeFileSync(root+'/verified.json',JSON.stringify(rows,null,2));
 console.log('Native aspect/focal geometry, single subjects, radial coverage, windows, negatives, trails and iris seek checks passed on both paths.');
}finally{await browser.close();}
