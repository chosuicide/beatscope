export const MOVIE_TEMPLATES=Object.freeze([
 {id:'voxel',name:'VOXEL INTERFERENCE',nameZh:'体素干扰',version:'voxel-phrase-2'},
 {id:'material-mix',name:'PRISMATIC ECHO I',nameZh:'棱镜残像 I',version:'prismatic-echo-5'},
 {id:'material-mix-2',name:'PRISMATIC ECHO II',nameZh:'棱镜残像 II',version:'prismatic-echo-ii-1'},
 {id:'paint',name:'PASTEL BLOOM',nameZh:'粉彩花信',version:'pastel-bloom-2'},
]);
export const materialTemplate=id=>MOVIE_TEMPLATES.some(t=>t.id===id&&id.startsWith('material-'));
export const mediaTemplate=id=>materialTemplate(id)||id==='paint';
