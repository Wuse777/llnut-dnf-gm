import {validationMessage} from './api'
export type FieldErrors=Record<string,string>
export class FormValidationError extends Error {
 constructor(public fields:FieldErrors){super(`请检查标红的 ${Object.keys(fields).length} 项内容，再重试。`)}
}
export function assertValid(fields:FieldErrors){if(Object.keys(fields).length)throw new FormValidationError(fields)}
export function itemErrors(items:any[],prefix:string):FieldErrors{
 const errors:FieldErrors={}
 if(!items.length||items.length>20)errors[prefix+'-items']='请添加1至20条附件，再继续操作。'
 items.forEach((item,index)=>{if(!Number.isInteger(item.quantity)||item.quantity<1||item.quantity>1000000||(item.stack_limit&&item.quantity>item.stack_limit)||(item.category==='equipment'&&item.quantity!==1))errors[prefix+'-quantity-'+index]='请核对物品 #'+item.id+' 的数量和堆叠上限（1–'+(item.category==='equipment'?1:item.stack_limit||1000000)+'）。'})
 return errors
}
export function operationErrors(data:{action:string,account:any,delta:number,reason:string,message:string,roleValid:boolean,items:any[],gold?:number}):FieldErrors{
 const errors:FieldErrors={}
 if(!data.account)errors['mail-recipient']='请先查找并选择收件账号。'
 if(data.action==='currency'&&(!Number.isInteger(data.delta)||!data.delta||Math.abs(data.delta)>1000000000))errors['operation-delta']='变更金额必须为非零整数，绝对值不超过10亿。'
 if(data.action==='mail'){
  if(data.account&&!data.roleValid)errors['mail-role']='请选择当前账号下未删除的收件角色。'
  const gold=data.gold??0
  if(!Number.isInteger(gold)||gold<0||gold>1000000000)errors['mail-gold']='金币必须为0至1,000,000,000的整数；0表示不附带金币。'
  if(data.items.length||!Number.isInteger(gold)||gold<=0)Object.assign(errors,itemErrors(data.items,'mail'))
  if(data.message.length>60)errors['mail-message']='邮件文字不能超过60个字符。'
 }
 if(!data.reason.trim())errors['operation-reason']='请填写操作原因，不能只填空格。'
 else if(data.reason.trim().length>200)errors['operation-reason']='操作原因不能超过200个字符。'
 return errors
}
export function giftErrors(name:string,items:any[]):FieldErrors{
 const errors:FieldErrors={}
 if(!name.trim())errors['gift-name']='请填写模板名称。'
 else if(name.trim().length>80)errors['gift-name']='模板名称不能超过80个字符。'
 return {...errors,...itemErrors(items,'gift')}
}

// Only map structured server-validation locations; never guess business errors
// (e.g. stale balances) from substrings or weaken server-side validation.
export function serverFieldErrors(detail:unknown,scope:string):FieldErrors{
 const errors:FieldErrors={}
 if(!Array.isArray(detail)||!['gift','operation'].includes(scope))return errors
 for(const issue of detail){
  const loc=issue.loc?.filter((x:unknown)=>x!=='body')??[]
  const map:Record<string,string>=scope==='gift'?{name:'gift-name',items:'gift-items'}:scope==='operation'?{reason:'operation-reason',delta:'operation-delta',uid:'mail-recipient',charac_no:'mail-role',items:'mail-items',message:'mail-message',gold:'mail-gold'}:{}
  let key=map[loc[0]]
  if(loc[0]==='items'&&Number.isInteger(loc[1])&&loc[2]==='quantity')key=(scope==='gift'?'gift':'mail')+'-quantity-'+loc[1]
  if(key)errors[key]=validationMessage([issue])
 }
 return errors
}
