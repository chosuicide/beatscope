import assert from 'node:assert/strict';import{createFrameEncoder}from'../beatscope/web/mv-encode.mjs';
const canvas={width:1080,height:1080};let closedFrames=0,posted=0;
globalThis.VideoFrame=class{close(){closedFrames++;}};
globalThis.fetch=async()=>{posted++;return{ok:true};};
// A reported supported hardware configuration can still fail at driver startup.
globalThis.VideoEncoder=class{
 static async isConfigSupported(){return{supported:true};}
 constructor(callbacks){this.callbacks=callbacks;this.state='unconfigured';this.encodeQueueSize=0;}
 configure(config){this.config=config;this.state='configured';}
 encode(){if(this.config.hardwareAcceleration!=='prefer-hardware')this.callbacks.output({byteLength:3,copyTo:a=>a.set([0,0,1])});}
 async flush(){if(this.config.hardwareAcceleration==='prefer-hardware'){this.state='closed';this.callbacks.error(Error('Driver initialization failed'));throw Error('Driver initialization failed');}}
 close(){this.state='closed';}
};
const encoder=await createFrameEncoder({canvas});assert.equal(encoder.hardwareAcceleration,'no-preference');assert.equal(posted,0,'Probe chunks must never enter the movie');await encoder.encode(0);assert.equal(await encoder.finish(),1);assert.equal(posted,1);assert.equal(closedFrames,5);
VideoEncoder.isConfigSupported=async()=>({supported:false});assert.equal(await createFrameEncoder({canvas}),null);
delete globalThis.VideoEncoder;assert.equal(await createFrameEncoder({canvas}),null);
console.log('Driver initialization failure, unsupported API and probe isolation passed.');
