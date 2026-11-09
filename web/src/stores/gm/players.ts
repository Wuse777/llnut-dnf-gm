import {defineStore} from 'pinia'
import {ref,onScopeDispose} from 'vue'
import {createReadQuery} from '../../readQuery'
export type PlayerWorkspace={uid:number,account:any,roles:any[],selectedRole:number,tab:string,page:number}
export const useGmPlayersStore=defineStore('gm-players',()=>{
 const workspaces=ref<Record<number,PlayerWorkspace>>({})
 const reads=createReadQuery()
 let generation=0
 async function open(uid:number,selectedRole=0,signal?:AbortSignal){
  if(!Number.isSafeInteger(uid)||uid<1||uid>2147483647)throw new Error('玩家UID无效')
  const current=generation
  const [account,characters]=await Promise.all([reads.get<any>('/accounts/'+uid,{signal}),reads.get<any>('/characters?uid='+uid,{signal})])
  if(selectedRole&&!characters.items.some((role:any)=>role.charac_no===selectedRole)){const detail=await reads.get<any>('/characters/'+selectedRole,{signal});if(detail.character?.uid!==uid||detail.character?.delete_flag)throw new Error('所选角色不属于当前账号或已删除');characters.items.push(detail.character)}
  if(current!==generation||signal?.aborted)throw new DOMException('目标读取已取消','AbortError')
  const previous=workspaces.value[uid]
  const workspace={uid,account,roles:characters.items,selectedRole,tab:previous?.tab??'roles',page:previous?.page??1}
  workspaces.value[uid]=workspace;return workspace
 }
 function clear(){generation++;reads.clear();workspaces.value={}}
 onScopeDispose(()=>reads.dispose())
 return {workspaces,open,clear}
})
