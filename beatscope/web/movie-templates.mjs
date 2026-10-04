export const MOVIE_TEMPLATES=Object.freeze([
 {id:'voxel',name:'VOXEL INTERFERENCE',nameZh:'体素干扰',version:'voxel-phrase-2'},
 {id:'material-mix',name:'PRISMATIC ECHO',nameZh:'棱镜残像',version:'prismatic-echo-4'},
]);
export const materialTemplate=id=>MOVIE_TEMPLATES.some(t=>t.id===id&&id.startsWith('material-'));
