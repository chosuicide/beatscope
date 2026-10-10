export function movieOutput(aspect='1:1', resolution=1080, preview=false) {
 if(!['1:1','16:9','9:16'].includes(aspect)||![720,1080].includes(resolution))throw Error('Invalid output format');
 const short=preview?540:resolution,long=preview?960:resolution===720?1280:1920;
 const [width,height]=aspect==='16:9'?[long,short]:aspect==='9:16'?[short,long]:[short,short];
 return {aspect,resolution,width,height,fps:30};
}
