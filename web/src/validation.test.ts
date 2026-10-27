import {it,expect} from 'vitest'
import {operationErrors,giftErrors,itemErrors,serverFieldErrors,assertValid,FormValidationError} from './validation'
it('honors the effective maintenance trial cap without claiming client verification',()=>{
 const item={id:7,category:'material',stack_limit:1000,indexed_stack_limit:0,quantity_limit_source:'maintenance-trial',quantity:1000}
 expect(itemErrors([item],'mail')).toEqual({})
 expect(itemErrors([{...item,quantity:1001}],'mail')['mail-quantity-0']).toContain('1–1000')
})
it('only an explicit unlimited maintenance trial can exceed the ordinary ceiling',()=>{
 const item={id:7,category:'material',stack_limit:2147483647,quantity_limit_source:'maintenance-trial',quantity_unlimited:true,quantity:2147483647}
 expect(itemErrors([item],'mail')).toEqual({})
 expect(itemErrors([{...item,quantity:2147483648}],'mail')['mail-quantity-0']).toBeTruthy()
 expect(itemErrors([{...item,quantity_unlimited:false,quantity:1000001}],'mail')['mail-quantity-0']).toBeTruthy()
})
it('collects every missing operation field rather than stopping at the first',()=>{
 const errors=operationErrors({action:'mail',account:null,delta:1,reason:'  ',message:'GM',roleValid:false,items:[]})
 expect(Object.keys(errors)).toEqual(['mail-recipient','mail-items','operation-reason'])
 expect(()=>assertValid(errors)).toThrow(FormValidationError)
})
it('shows role and quantity problems alongside mail fields',()=>{
 const errors=operationErrors({action:'mail',account:{uid:1},delta:1,reason:'test',message:'',roleValid:false,items:[{id:5,quantity:4,category:'material',stack_limit:3}]})
 expect(errors['mail-role']).toContain('收件角色');expect(errors['mail-quantity-0']).toContain('数量和堆叠上限')
 expect(errors['operation-reason']).toBeUndefined()
})
it('flags name and attachments for gift creation, including equipment quantity',()=>{
 expect(Object.keys(giftErrors('',[]))).toEqual(['gift-name','gift-items'])
 expect(itemErrors([{id:1,quantity:2,category:'equipment'}],'gift')['gift-quantity-0']).toContain('1–1')
 expect(itemErrors([{id:1,quantity:1,category:'equipment'}],'gift')).toEqual({})
})
it('maps structured server errors to fields but never guesses plain business errors',()=>{
 expect(serverFieldErrors([{loc:['body','reason'],type:'string_too_short'}],'operation')['operation-reason']).toContain('操作原因')
 expect(serverFieldErrors([{loc:['body','items',1,'quantity'],type:'int_type'}],'gift')['gift-quantity-1']).toContain('请填写整数')
 expect(serverFieldErrors('余额不足','operation')).toEqual({})
})
it('validates mail gold independently of items and preserves template item requirements',()=>{
 const base={action:'mail',account:{uid:3},roleValid:true,items:[],delta:1,reason:'test',message:'GM'}
 expect(operationErrors({...base,gold:1000})).toEqual({})
 expect(operationErrors({...base,gold:0})['mail-items']).toBeTruthy()
 expect(operationErrors({...base,gold:1.2})['mail-gold']).toBeTruthy()
 expect(operationErrors({...base,gold:1000000001})['mail-gold']).toBeTruthy()
 expect(giftErrors('template',[])['gift-items']).toBeTruthy()
 expect(serverFieldErrors([{loc:['body','gold'],type:'less_than_equal'}],'operation')['mail-gold']).toContain('金币附件')
})
