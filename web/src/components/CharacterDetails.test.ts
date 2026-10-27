// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import CharacterDetails from './CharacterDetails.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
function fixture(){return {character:{charac_no:4,uid:3,charac_name:'测试测试',lev:27,delete_flag:0,job:0,grow_type:1,guild_id:0,exp:0,fatigue:0,max_fatigue:156},account:{uid:3,accountname:'gm'},profession:{name:'剑魂',base_name:'鬼剑士',note:'名称来自当前PVF'},account_online:{login_status:1,channel:3011},play_state:{exp:12345,fatigue:20,used_fatigue:7,last_play_time:'2026-10-24 07:00:00'},wealth:{state:'ok',gold:150460,revival_coin_raw:3},attributes:[{key:'maxHP',label:'最大 HP 存档值',value:14000}],collected_at:1792828800,catalog_state:'ok',snapshot_note:'数据库存档快照，不是在线实时战斗面板',read_only:true,equipment:{state:'ok',slot_count:12,items:[item(10000,'测试装备',1)]},backpack:{state:'ok',slot_count:249,items:[item(1000,'野草莓',2,55),item(999999,'未知物品 #999999',4,2)]}}}
function item(id:number,name:string,type:number,quantity=1){return {slot:id,slot_label:'武器',id,name,type,type_name:type===1?'装备':type===2?'消耗品':'任务材料',quantity,level:1,enhancement:type===1?7:null,forge:0,durability:33,amplify_type:0,amplify_value:0,orb_id:0,sealed_raw:0}}
function setup(data:any=fixture()){
 const calls:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any)=>{calls.push((opts?.method??'GET')+' '+url);return new Response(JSON.stringify(data))}))
 const w=mount(CharacterDetails,{props:{characNo:4},attachTo:document.body});return {w,calls}
}
async function tab(w:any,text:string){const b=w.findAll('[role=tab]').find((b:any)=>b.text().startsWith(text));await b!.trigger('click');await flushPromises()}
it('loads protected detail GET and displays correct account, gold and snapshot semantics',async()=>{
 const {w,calls}=setup();await flushPromises();expect(calls).toEqual(['GET /dnf-gm/api/v1/characters/4']);expect(w.text()).toContain('150,460');expect(w.text()).toContain('剑魂');expect(w.text()).toContain('12,345');expect(w.text()).toContain('所属账号在线；不代表当前角色在线');expect(w.text()).toContain('不含仓库金币');expect(w.find('[role=dialog]').exists()).toBe(true);w.unmount()
})
it('switches attributes/equipment/backpack and supports type/name/id filtering',async()=>{
 const {w,calls}=setup();await flushPromises();await tab(w,'属性存档');expect(w.text()).toContain('14,000');expect(w.text()).toContain('力量、智力');await tab(w,'穿戴装备');expect(w.text()).toContain('测试装备');expect(w.text()).toContain('强化 +7');await tab(w,'背包道具');expect(w.text()).toContain('野草莓');expect(w.text()).toContain('55');await w.find('[aria-label="筛选角色物品"]').setValue('999999');expect(w.text()).not.toContain('野草莓');expect(w.text()).toContain('未知物品 #999999');await w.find('[aria-label="筛选角色物品"]').setValue('');await w.find('[aria-label="角色物品类型"]').setValue('2');expect(w.text()).toContain('野草莓');expect(w.text()).not.toContain('未知物品 #999999');expect(calls.length).toBe(1);w.unmount()
})
it('shows missing gold as unknown and distinguishes malformed from empty inventory',async()=>{
 const d=fixture();d.wealth={state:'missing',gold:null,revival_coin_raw:null} as any;d.backpack={state:'invalid',message:'压缩数据异常，不代表空背包',slot_count:null,items:[]} as any;const {w}=setup(d);await flushPromises();expect(w.text()).toContain('金币存档缺失，不能视为0');await tab(w,'背包道具');expect(w.text()).toContain('不代表空背包');expect(w.text()).not.toContain('没有非空物品');w.unmount()
})
it('renders missing PVF, deleted state and untrusted names as plain text',async()=>{
 const d=fixture();d.character.charac_name='<img src=x onerror=alert(1)>';d.character.delete_flag=1;d.catalog_state='mismatch';const {w}=setup(d);await flushPromises();expect(w.find('img').exists()).toBe(false);expect(w.text()).toContain('<img src=x');expect(w.text()).toContain('已删除（仅查看存档）');expect(w.text()).toContain('版本不匹配');w.unmount()
})
it('shows request errors inside dialog, retries GET only and never retains old character',async()=>{
 const {w,calls}=setup();await flushPromises();vi.mocked(fetch).mockImplementationOnce(async()=>new Response('{"detail":"角色不存在"}',{status:404}));await w.setProps({characNo:999});await flushPromises();expect(w.text()).toContain('角色不存在');expect(w.text()).not.toContain('150,460');const retry=w.findAll('button').find(b=>b.text()==='重试查询')!;await retry.trigger('click');await flushPromises();expect(calls.every(p=>p.startsWith('GET '))).toBe(true);expect(w.text()).toContain('150,460');w.unmount()
})
it('ignores response from older role when user changes role while loading',async()=>{
 let resolveOld:(v:Response)=>void=()=>{};vi.stubGlobal('fetch',vi.fn((url)=>url.toString().endsWith('/4')?new Promise<Response>(r=>resolveOld=r):Promise.resolve(new Response(JSON.stringify({...fixture(),character:{...fixture().character,charac_name:'新角色'}})))));const w=mount(CharacterDetails,{props:{characNo:4}});await w.setProps({characNo:5});await flushPromises();resolveOld(new Response(JSON.stringify(fixture())));await flushPromises();expect(w.text()).toContain('新角色');expect(w.text()).not.toContain('测试测试');w.unmount()
})
it('paginates within container and resets page after filtering',async()=>{
 const d=fixture();d.backpack.items=Array.from({length:35},(_,i)=>item(i+100,'物品'+i,2));const {w}=setup(d);await flushPromises();await tab(w,'背包道具');expect(w.findAll('tbody tr').length).toBe(30);await w.findAll('button').find(b=>b.text()==='下一页物品')!.trigger('click');expect(w.findAll('tbody tr').length).toBe(5);await w.find('[aria-label="筛选角色物品"]').setValue('物品0');expect(w.findAll('tbody tr').length).toBe(1);expect(w.text()).toContain('第 1 / 1 页');w.unmount()
})
it('supports closing while loading and restores focus to trigger',async()=>{
 const trigger=document.createElement('button');document.body.appendChild(trigger);trigger.focus();vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})));const w=mount(CharacterDetails,{props:{characNo:4},attachTo:document.body});await flushPromises();await w.find('[aria-label="关闭对话框"]').trigger('click');expect(w.emitted('close')).toHaveLength(1);w.unmount();expect(document.activeElement).toBe(trigger)
})

it('arrow keys move selected role-inspector tab and focus',async()=>{
 const {w}=setup();await flushPromises();const tab=w.find('[role=tab][aria-selected=true]');await tab.trigger('keydown',{key:'ArrowRight'});await flushPromises();expect(w.find('[role=tab][aria-selected=true]').text()).toBe('属性存档');expect(document.activeElement).toBe(w.find('[role=tab][aria-selected=true]').element);w.unmount()
})
