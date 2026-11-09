import {computed,ref} from 'vue'
// One confirmation surface across reward, native, inventory and maintenance domains.
const owner=ref('')
export function useGmConfirmation(){
 function acquire(identity:string){if(owner.value&&owner.value!==identity)return false;owner.value=identity;return true}
 function release(identity:string){if(owner.value===identity)owner.value=''}
 return {owner,locked:computed(()=>!!owner.value),acquire,release}
}
