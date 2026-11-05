// One keyboard owner for nested dialogs. Never let Escape in an item drawer
// close an underlying reward confirmation or character editor as well.
const stack:symbol[]=[]
let previousOverflow=''
export function pushDialog(id:symbol){
 if(!stack.length){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden'}
 stack.push(id)
 return stack.length
}
export function topDialog(id:symbol){return stack.at(-1)===id}
export function removeDialog(id:symbol){
 const index=stack.indexOf(id);if(index>=0)stack.splice(index,1)
 if(!stack.length)document.body.style.overflow=previousOverflow
}
