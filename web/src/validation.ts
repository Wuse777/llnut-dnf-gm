import {validationMessage} from './api'
export type FieldErrors=Record<string,string>
export class FormValidationError extends Error {
 constructor(public fields:FieldErrors){super(`请检查标红的 ${Object.keys(fields).length} 项内容，再重试。`)}
}
export function assertValid(fields:FieldErrors){if(Object.keys(fields).length)throw new FormValidationError(fields)}
export function itemErrors(items:any[],prefix:string):FieldErrors{
 const errors:FieldErrors={}
 if(!items.length||items.length>20)errors[prefix+'-items']='请添加1至20条附件，再继续操作。'
 items.forEach((item,index)=>{if(!Number.isInteger(item.quantity)||item.quantity<1||item.quantity>2147483647)errors[prefix+'-quantity-'+index]='物品 #'+item.id+' 的数量须为正整数（邮件数量字段范围：1–2147483647），不受PVF堆叠上限限制。'})
 return errors
}
export function mailTextErrors(title:string,message:string,prefix:string):FieldErrors{
 const errors:FieldErrors={}
 if(Array.from(title).length>40||/[\p{C}]/u.test(title))errors[prefix+'-title']='标题须为最多40个字符的单行文字，不含控制字符。'
 else if(new TextEncoder().encode(title?title+'\n'+message:message).length>255)errors[prefix+'-title']='标题与正文合计超过255个UTF-8字节，请缩短文字。'
 return errors
}
export function operationErrors(data:{action:string,account:any,delta:number,reason:string,message:string,mailTitle?:string,roleValid:boolean,items:any[],gold?:number,currencyRewards?:Record<string,number>}):FieldErrors{
 const errors:FieldErrors={}
 if(!data.account)errors['mail-recipient']='请先查找并选择收件账号。'
 if(data.action==='currency'&&(!Number.isInteger(data.delta)||!data.delta||Math.abs(data.delta)>1000000000))errors['operation-delta']='变更金额必须为非零整数，绝对值不超过10亿。'
 if(['mail','reward'].includes(data.action)){
  const amounts=data.currencyRewards||{},hasCurrency=Object.values(amounts).some(v=>v>0)
  Object.assign(errors,currencyRewardErrors(amounts,'mail'))
  if(data.account&&!data.roleValid&&(data.items.length||!!data.gold||!hasCurrency))errors['mail-role']='请选择当前账号下未删除的收件角色。'
  const gold=data.gold??0
  if(!Number.isInteger(gold)||gold<0||gold>1000000000)errors['mail-gold']='金币必须为0至1,000,000,000的整数；0表示不附带金币。'
  if(data.items.length||!Number.isInteger(gold)||(gold<=0&&!hasCurrency))Object.assign(errors,itemErrors(data.items,'mail'))
  Object.assign(errors,mailTextErrors(data.mailTitle||'',data.message,'mail'))
  if(data.message.length>60)errors['mail-message']='邮件文字不能超过60个字符。'
 }
 if(!data.reason.trim())errors['operation-reason']='请填写操作原因，不能只填空格。'
 else if(data.reason.trim().length>200)errors['operation-reason']='操作原因不能超过200个字符。'
 return errors
}
export function currencyRewardErrors(amounts:Record<string,number>,prefix:string):FieldErrors{
 const errors:FieldErrors={}
 for(const [key,value] of Object.entries(amounts))if(!Number.isInteger(value)||value<0||value>1000000000)errors[prefix+'-reward-'+key]='账号货币须为0至10亿的整数。'
 return errors
}
export function giftErrors(name:string,items:any[],gold=0,message='GM rewards',amounts:Record<string,number>={},title=''):FieldErrors{
 const errors:FieldErrors={}
 if(!name.trim())errors['gift-name']='请填写模板名称。'
 else if(name.trim().length>80)errors['gift-name']='模板名称不能超过80个字符。'
 if(!Number.isInteger(gold)||gold<0||gold>1000000000)errors['gift-gold']='金币附件须为0至10亿的整数。'
 if(message.length>60)errors['gift-message']='邮件文字不能超过60个字符。'
 return {...errors,...mailTextErrors(title,message,'gift'),...currencyRewardErrors(amounts,'gift'),...(items.length||(gold<=0&&!Object.values(amounts).some(v=>v>0))?itemErrors(items,'gift'):{})}
}

// Only map structured server-validation locations; never guess business errors
// (e.g. stale balances) from substrings or weaken server-side validation.
export function serverFieldErrors(detail:unknown,scope:string):FieldErrors{
 const errors:FieldErrors={}
 if(!Array.isArray(detail)||!['gift','operation'].includes(scope))return errors
 for(const issue of detail){
  const loc=issue.loc?.filter((x:unknown)=>x!=='body')??[]
  const map:Record<string,string>=scope==='gift'?{name:'gift-name',items:'gift-items',gold:'gift-gold',message:'gift-message',mail_title:'gift-title'}:scope==='operation'?{reason:'operation-reason',delta:'operation-delta',uid:'mail-recipient',charac_no:'mail-role',items:'mail-items',message:'mail-message',gold:'mail-gold',mail_title:'mail-title'}:{}
  let key=map[loc[0]]
  if(loc[0]==='items'&&Number.isInteger(loc[1])&&loc[2]==='quantity')key=(scope==='gift'?'gift':'mail')+'-quantity-'+loc[1]
  if(loc[0]==='currency_rewards'&&['cera','cera_point','mileage'].includes(loc[1]))key=(scope==='gift'?'gift':'mail')+'-reward-'+loc[1]
  if(key)errors[key]=validationMessage([issue])
 }
 return errors
}
