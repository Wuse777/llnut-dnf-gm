import {defineStore} from 'pinia'
import {ref} from 'vue'
import {api} from '../../api'
export type PlayerWorkspace={uid:number,account:any,roles:any[],selectedRole:number,tab:string,page:number}
export const useGmPlayersStore=defineStore('gm-players',()=>{
 const workspaces=ref<Record<number,PlayerWorkspace>>({})
 async function open(uid:number,selectedRole=0){
  if(!Number.isSafeInteger(uid)||uid<1||uid>2147483647)throw new Error('玩家UID无效')
  const [account,characters]=await Promise.all([api('/accounts/'+uid),api('/characters?uid='+uid)])
  if(selectedRole&&!characters.items.some((role:any)=>role.charac_no===selectedRole)){const detail=await api('/characters/'+selectedRole);if(detail.character?.uid!==uid||detail.character?.delete_flag)throw new Error('所选角色不属于当前账号或已删除');characters.items.push(detail.character)}
  const previous=workspaces.value[uid]
  const workspace={uid,account,roles:characters.items,selectedRole,tab:previous?.tab??'roles',page:previous?.page??1}
  workspaces.value[uid]=workspace;return workspace
 }
 function clear(){workspaces.value={}}
 return {workspaces,open,clear}
})
