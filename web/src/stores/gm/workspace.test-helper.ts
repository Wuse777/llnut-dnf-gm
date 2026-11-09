import {vi} from 'vitest'
import {mount} from '@vue/test-utils'
import {createPinia,setActivePinia,disposePinia} from 'pinia'
import {defineComponent,h} from 'vue'
vi.mock('@/router',()=>({router:{push:vi.fn(),replace:vi.fn()}}))
import {useGmWorkspace} from './useGmWorkspace'
export function workspaceFixture(){
 const calls:{path:string,method:string,body:any}[]=[]
 const fetcher=vi.fn(async(url:any,options:any={})=>{const path=String(url).replace('/dnf-gm/api/v1',''),body=options.body?JSON.parse(options.body):null;calls.push({path,method:options.method||'GET',body});let data:any={}
 if(path==='/auth/methods')data={totp_required:false}
 else if(path==='/auth/me'||path==='/auth/login')data={csrf:'session-fixture'}
 else if(path==='/overview')data={counts:{},server:{fresh:false}}
 else if(/^\/accounts\/\d+$/.test(path))data={uid:Number(path.split('/').pop()),accountname:'player-'+path.split('/').pop(),cera:100,cera_point:0,mileage:0}
 else if(path.startsWith('/characters?uid=')){const uid=Number(path.split('=')[1]);data={items:[{uid,charac_no:uid*10,charac_name:'角色'+uid,lev:1,delete_flag:0}]}}
 else if(path==='/operations/preview')data={operation_id:'a'.repeat(32),write_enabled:true,preview:{...body,target:{uid:body.uid,accountname:'player-'+body.uid,character:body.charac_no?{charac_no:body.charac_no,charac_name:'角色'}:null},rewards:{items:body.items},gold:body.gold}}
 else if(path.endsWith('/confirm'))data={operation_id:'a'.repeat(32),status:'committed',action:'mail',result:{gold:5,postal_ids:[1]},state:'database_delivered_not_claimed'}
 else if(path.startsWith('/operations/'))data={operation_id:path.split('/').pop(),action:'mail',status:'committed',result:{gold:5},preview:{target:{uid:3}}}
 else if(path.startsWith('/catalog?'))data={metadata:{pvf_sha256:'a'.repeat(64)},total:1,items:[{id:1000,name:'测试材料',category:'material',allowed:1,sendable:true,pvf_sha256:'a'.repeat(64)}]}
 else if(path.startsWith('/ui-preferences?'))data={pvf_sha256:'a'.repeat(64),items:[]}
 return new Response(JSON.stringify(data))})
 vi.stubGlobal('fetch',fetcher)
 const pinia=createPinia();setActivePinia(pinia)
 let gm!:ReturnType<typeof useGmWorkspace>
 const wrapper=mount(defineComponent({setup(){gm=useGmWorkspace();return ()=>h('div')}}),{global:{plugins:[pinia]}})
 async function target(uid=3,character=0){gm.tab='accounts';await gm.setTarget(uid,character);gm.action='currency';gm.reason='测试原因'}
 function cleanup(){wrapper.unmount();disposePinia(pinia)}
 return {gm,calls,fetcher,pinia,wrapper,target,cleanup}
}
