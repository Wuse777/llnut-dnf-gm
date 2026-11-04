import {ref,watch,onMounted,onUnmounted,type Ref} from 'vue'
import {api,ApiError} from './api'
const KEY='dnf-gm.pending-operation'
export function readPendingOperation(){try{const id=sessionStorage.getItem(KEY)||'';return /^[a-f0-9]{32}$/.test(id)?id:''}catch{return ''}}
/** Recover response-loss by GET only, never confirm or create a replacement. */
export function usePendingOperation(id:Ref<string>,active:Ref<boolean>,busy:Ref<boolean>,resolved:(value:any)=>void){
 const status=ref(''),lastChecked=ref(0)
 let timer:ReturnType<typeof setTimeout>|undefined,stopped=false,inflight=false
 watch(id,value=>{try{if(value)sessionStorage.setItem(KEY,value);else sessionStorage.removeItem(KEY)}catch{};status.value='';lastChecked.value=0},{flush:'sync'})
 async function tick(){
  if(stopped)return
  if(id.value&&active.value&&!busy.value&&!document.hidden&&!inflight){
   const current=id.value;inflight=true
   try{const result=await api('/operations/'+current);if(!stopped&&id.value===current){lastChecked.value=Date.now();if(result.status==='committed'){resolved(result);id.value='';status.value='已查明：数据库提交成功。'}else status.value='服务器尚未报告提交成功；继续查询原编号，不重发。'}}
   catch(e){if(!stopped&&id.value===current){lastChecked.value=Date.now();status.value=e instanceof ApiError&&e.status===401?'会话已过期，重新登录后继续核对原操作。':'暂时无法确认结果，将继续只读查询。'}}
   finally{inflight=false}
  }
  if(!stopped)timer=setTimeout(tick,5000)
 }
 onMounted(()=>{timer=setTimeout(tick,5000)})
 onUnmounted(()=>{stopped=true;clearTimeout(timer)})
 return {pendingStatus:status,pendingChecked:lastChecked}
}
