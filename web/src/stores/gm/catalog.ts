import {defineStore} from 'pinia'
import {onScopeDispose,ref} from 'vue'
import {onApiReadInvalidation} from '../../api'
import {createReadQuery} from '../../readQuery'
export type CatalogState={filters:Record<string,any>,page:number,comparison:any[],pvf:string}
export const useGmCatalogStore=defineStore('gm-catalog',()=>{
 const contexts=ref<Record<string,CatalogState>>({}),pvf=ref(''),sessionVersion=ref(0)
 const reads=createReadQuery({ttlMs:30000,maxEntries:12,resultPartition:(value,partition)=>{
  const [,policy]=JSON.parse(partition)
  return JSON.stringify([value?.metadata?.pvf_sha256||'',policy])
 }})
 let metadataTicket=0,appliedTicket=0
 async function read(path:string,options:{signal?:AbortSignal,force?:boolean,pvf?:string,revision?:number}={}){
  const ticket=++metadataTicket,identity=sessionVersion.value
  const result=await reads.get<any>(path,{signal:options.signal,force:options.force,partition:JSON.stringify([pvf.value||options.pvf||'',options.revision??0])})
  if(identity!==sessionVersion.value)throw new DOMException('物品查询所属会话已结束','AbortError')
  if(ticket>=appliedTicket){appliedTicket=ticket;pvf.value=result.metadata?.pvf_sha256||''}
  return result
 }
 function clear(){sessionVersion.value++;contexts.value={};pvf.value='';reads.clear();reads.cancel()}
 const unsubscribe=onApiReadInvalidation(event=>{if(event.reason!=='mutation'){sessionVersion.value++;contexts.value={};pvf.value='';appliedTicket=++metadataTicket}})
 onScopeDispose(()=>{unsubscribe();reads.dispose()})
 return {contexts,pvf,sessionVersion,read,clear}
})
