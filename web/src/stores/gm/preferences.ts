import {ref,onUnmounted} from 'vue'
import {api,ApiError,uncertainMessage} from '../../api'
export type GmPreference={name:string,kind:string,pvf_sha256:string,version:number,payload:Record<string,any>|null}
export function useGmPreferences(kind:'catalog-filter'|'appearance'|'layout',pvf:()=>string|undefined){
 const items=ref<GmPreference[]>([]),loading=ref(false),saving=ref(false),error=ref(''),conflict=ref(false)
 let generation=0
 async function load(){const current=++generation;loading.value=true;error.value='';try{const result=await api('/ui-preferences?kind='+kind);if(current!==generation)return;if(pvf()&&result.pvf_sha256!==pvf())throw new Error('PVF 已变化，请刷新物品索引后再读取方案。');items.value=result.items;conflict.value=false}catch(e){if(current===generation)error.value=uncertainMessage(e)}finally{if(current===generation)loading.value=false}}
 function fail(e:unknown){conflict.value=e instanceof ApiError&&e.status===409;error.value=uncertainMessage(e)+(conflict.value?'。请先点击刷新方案，核对后再保存；当前内容没有覆盖远端。':'')}
 async function save(name:string,payload:Record<string,any>){if(saving.value||conflict.value||!pvf())return false;saving.value=true;error.value='';try{const known=items.value.find(row=>row.name===name);const baseline=known||await api('/ui-preferences/'+kind+'/'+encodeURIComponent(name));if(!known&&baseline.payload)throw new ApiError('同名方案已在其他页面创建',409);const result=await api('/ui-preferences/'+kind+'/'+encodeURIComponent(name),'PUT',{pvf_sha256:pvf(),expected_version:baseline.version,payload});items.value=[result,...items.value.filter(row=>row.name!==name)];return true}catch(e){fail(e);return false}finally{saving.value=false}}
 async function remove(row:GmPreference){if(saving.value||conflict.value)return;saving.value=true;error.value='';try{await api('/ui-preferences/'+kind+'/'+encodeURIComponent(row.name),'DELETE',{pvf_sha256:row.pvf_sha256,expected_version:row.version});items.value=items.value.filter(item=>item.name!==row.name)}catch(e){fail(e)}finally{saving.value=false}}
 onUnmounted(()=>generation++)
 return {items,loading,saving,error,conflict,load,save,remove}
}
