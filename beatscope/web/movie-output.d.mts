export type MovieOutput = {aspect:'1:1'|'16:9'|'9:16';resolution:720|1080;width:number;height:number;fps:number};
export function movieOutput(aspect?:string,resolution?:number,preview?:boolean):MovieOutput;
