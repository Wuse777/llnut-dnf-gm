import {ref} from 'vue'
export class ApiError extends Error{constructor(message:string,public status:number,public detail?:unknown){super(message)}}
export let csrf=''
export function setCsrf(value:string){csrf=value}
export const requests=ref<{method:string,path:string,status:number|string,ms:number}[]>([])
export function validationMessage(detail:unknown){
 if(typeof detail==='string')return detail
 const names:Record<string,string>={gold:'金币附件',reason:'操作原因',delta:'变更金额',quantity:'物品数量',uid:'账号 UID',charac_no:'收件角色',name:'模板名称',message:'邮件文字'}
 if(Array.isArray(detail))return detail.map(d=>{const field=d.loc?.filter((s:unknown)=>s!=='body').map((s:string)=>names[s]||s).join(' / ')||'参数';return field+'：'+(d.type==='int_type'?'请填写整数':d.type==='string_too_short'?'内容不能为空':d.type==='greater_than_equal'?'数值过小':d.type==='less_than_equal'?'数值过大':'格式或范围不正确')}).join('；')
 return '请求参数不正确'
}
export async function api(path:string,method='GET',data?:unknown):Promise<any>{
 const start=performance.now();let status:number|string='连接失败 / 结果未知'
 try{
 const r=await fetch('/dnf-gm/api/v1'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':csrf})},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(10000)})
 status=r.status
 const d=await r.json().catch(()=>({detail:'响应格式异常'}))
 if(!r.ok)throw new ApiError(validationMessage(d.detail),r.status,d.detail)
 return d
 }finally{requests.value=[{method,path,status,ms:Math.round(performance.now()-start)},...requests.value].slice(0,40)}
}
export function uncertainMessage(e:unknown){return e instanceof Error?e.message:'请求失败，写操作请按原编号查询结果，不要重新提交'}
