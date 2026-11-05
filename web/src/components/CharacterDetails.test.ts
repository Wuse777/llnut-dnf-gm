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
async function listView(w:any){await w.findAll('button').find((b:any)=>b.text()==='列表视图')!.trigger('click');await flushPromises()}
it('loads protected detail GET and displays correct account, gold and snapshot semantics',async()=>{
 const {w,calls}=setup();await flushPromises();expect(calls).toEqual(['GET /dnf-gm/api/v1/characters/4']);expect(w.text()).toContain('150,460');expect(w.text()).toContain('剑魂');expect(w.text()).toContain('12,345');expect(w.text()).toContain('所属账号在线；不代表当前角色在线');expect(w.text()).toContain('不含仓库金币');expect(w.find('[role=dialog]').exists()).toBe(true);w.unmount()
})
it('switches attributes/equipment/backpack and supports type/name/id filtering',async()=>{
 const {w,calls}=setup();await flushPromises();await tab(w,'属性存档');expect(w.text()).toContain('14,000');expect(w.text()).toContain('力量、智力');await tab(w,'穿戴装备');await listView(w);expect(w.text()).toContain('测试装备');expect(w.text()).toContain('强化 +7');await tab(w,'背包道具');expect(w.text()).toContain('野草莓');expect(w.text()).toContain('55');await w.find('[aria-label="筛选角色物品"]').setValue('999999');expect(w.text()).not.toContain('野草莓');expect(w.text()).toContain('未知物品 #999999');await w.find('[aria-label="筛选角色物品"]').setValue('');await w.find('[aria-label="角色物品类型"]').setValue('2');expect(w.text()).toContain('野草莓');expect(w.text()).not.toContain('未知物品 #999999');expect(calls.length).toBe(1);w.unmount()
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
 const d=fixture();d.backpack.items=Array.from({length:35},(_,i)=>item(i+100,'物品'+i,2));const {w}=setup(d);await flushPromises();await tab(w,'背包道具');await listView(w);expect(w.findAll('tbody tr').length).toBe(30);await w.findAll('button').find(b=>b.text()==='下一页物品')!.trigger('click');expect(w.findAll('tbody tr').length).toBe(5);await w.find('[aria-label="筛选角色物品"]').setValue('物品0');expect(w.findAll('tbody tr').length).toBe(1);expect(w.text()).toContain('第 1 / 1 页');w.unmount()
})
it('supports closing while loading and restores focus to trigger',async()=>{
 const trigger=document.createElement('button');document.body.appendChild(trigger);trigger.focus();vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})));const w=mount(CharacterDetails,{props:{characNo:4},attachTo:document.body});await flushPromises();await w.find('[aria-label="关闭对话框"]').trigger('click');expect(w.emitted('close')).toHaveLength(1);w.unmount();expect(document.activeElement).toBe(trigger)
})

it('arrow keys move selected role-inspector tab and focus',async()=>{
 const {w}=setup();await flushPromises();const tab=w.find('[role=tab][aria-selected=true]');await tab.trigger('keydown',{key:'ArrowRight'});await flushPromises();expect(w.find('[role=tab][aria-selected=true]').text()).toBe('属性存档');expect(document.activeElement).toBe(w.find('[role=tab][aria-selected=true]').element);w.unmount()
})


it('shows distinct role and shared warehouses, separate gold and raw capacity',async()=>{
 const d:any=fixture();d.warehouse={state:'ok',slot_count:152,capacity_raw:9,owner_uid:3,charac_no:4,items:[item(8388,'角色仓库材料',3,456)]};d.account_warehouse={state:'ok',slot_count:56,capacity_raw:7,owner_uid:3,gold:4000000000,gold_state:'ok',stored_at:'2026-11-04T01:02:03',items:[item(10000,'账号仓库装备',1)]}
 const {w,calls}=setup(d);await flushPromises();await tab(w,'角色仓库');await listView(w);expect(w.text()).toContain('角色仓库材料');expect(w.text()).toContain('456');expect(w.find('tbody').text()).not.toContain('账号仓库装备');expect(w.text()).toContain('不据此推断实际已开放格数')
 await tab(w,'账号仓库');expect(w.text()).toContain('账号仓库装备');expect(w.text()).toContain('4,000,000,000');expect(w.text()).not.toContain('150,460');expect(w.text()).toContain('同一账号下角色共享');expect(w.text()).toContain('所属 UID：3');expect(calls).toEqual(['GET /dnf-gm/api/v1/characters/4']);w.unmount()
})

it('does not invent empty warehouse or zero gold for missing records or older responses',async()=>{
 const {w}=setup();await flushPromises();await tab(w,'账号仓库');expect(w.text()).toContain('未返回此容器记录');expect(w.text()).toContain('无金币存档记录，不能视为0');expect(w.text()).not.toContain('没有非空物品');w.unmount()
})

it('shows warehouse decode failure separately from known stored gold',async()=>{
 const d:any=fixture();d.account_warehouse={state:'invalid',message:'存档格式异常，不代表空容器',items:[],slot_count:null,owner_uid:3,capacity_raw:7,gold:0,gold_state:'ok',stored_at:'0000-00-00 00:00:00'}
 const {w}=setup(d);await flushPromises();await tab(w,'账号仓库');expect(w.text()).toContain('不代表空容器');expect(w.text()).toContain('独立存档，不包含角色携带金币');expect(w.text()).toContain('未记录');expect(w.text()).not.toContain('没有非空物品');expect(w.find('.character-facts dd').text()).toContain('0');w.unmount()
})

it('resets filters when switching between warehouses',async()=>{
 const d:any=fixture();d.warehouse={state:'ok',slot_count:152,items:[item(8388,'角色材料',3)]};d.account_warehouse={state:'ok',slot_count:56,items:[item(10000,'共享装备',1)]};const {w}=setup(d);await flushPromises();await tab(w,'角色仓库');await listView(w);await w.find('[aria-label="筛选角色物品"]').setValue('找不到');expect(w.text()).toContain('没有匹配的物品');await tab(w,'账号仓库');expect(w.text()).toContain('共享装备');expect(w.findAll('tbody tr')).toHaveLength(1);w.unmount()
})
it('keeps maintenance inside its tabpanel and marks old snapshots instead of silently reloading',async()=>{
 const d=fixture();vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(d))))
 const w=mount(CharacterDetails,{props:{characNo:4},global:{stubs:{InventoryEditor:{name:'InventoryEditor',emits:['pending','changed'],template:'<div>维护测试入口</div>'}}},attachTo:document.body})
 await flushPromises();await tab(w,'穿戴装备');await listView(w);await w.find('.character-items button').trigger('click');await flushPromises()
 const editor=w.findComponent({name:'InventoryEditor'});expect(editor.exists()).toBe(true);expect(editor.element.closest('[role=tabpanel]')?.id).toBe('character-section-manage')
 editor.vm.$emit('pending',true);await flushPromises();await tab(w,'基本信息');expect(w.findAll('button').find(b=>b.text()==='刷新角色存档')!.attributes('disabled')).toBeDefined()
 editor.vm.$emit('changed');editor.vm.$emit('pending',false);await flushPromises();expect(w.text()).toContain('下方角色资料仍是旧快照');expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1)
 await w.findAll('button').find(b=>b.text()==='刷新角色存档')!.trigger('click');await flushPromises();expect(w.text()).not.toContain('下方角色资料仍是旧快照');w.unmount()
})
it('opens a directly requested maintenance tab on first mount',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(fixture()))))
 const w=mount(CharacterDetails,{props:{characNo:4,initialSection:'manage'},global:{stubs:{InventoryEditor:{template:'<div>初始维护入口</div>'}}}})
 await flushPromises();expect(w.find('#character-section-manage').text()).toContain('初始维护入口');expect(w.find('[role=tab][aria-selected=true]').text()).toBe('装备维护');w.unmount()
})

it('keeps role shortcuts and mail/activity queries bound to the current identity',async()=>{
 const calls:string[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string)=>{calls.push(url);const result=url.includes('/mail-center?')?{items:[],has_more:false}:url.includes('/activity?')?{items:[],next_before:null,note:'按角色关联'}:fixture();return new Response(JSON.stringify(result))}))
 const w=mount(CharacterDetails,{props:{characNo:4},attachTo:document.body})
 try{await flushPromises();await w.findAll('button').find(b=>b.text()==='给此角色发奖励')!.trigger('click');expect(w.emitted('action')?.[0]).toEqual([{action:'mail',uid:3,charac_no:4}]);await tab(w,'角色邮件');expect(calls.at(-1)).toContain('/mail-center?uid=3&charac_no=4');expect(w.get('[aria-label="邮件角色编号"]').attributes('disabled')).toBeDefined();await tab(w,'管理记录');expect(calls.at(-1)).toContain('/characters/4/activity?before=0');expect(w.text()).toContain('已到记录末尾')}finally{w.unmount()}
})

it('groups navigation and gives diagnostic panels unique IDs without fake missing-container errors',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(fixture()))))
 const w=mount(CharacterDetails,{props:{characNo:4},global:{stubs:{CharacterActivity:{template:'<div>管理记录内容</div>'},CharacterQuests:{template:'<div>任务查询内容</div>'},CharacterRename:{template:'<div>改名入口</div>'},CharacterRescue:{template:'<div>救援入口</div>'}}}})
 try{await flushPromises();expect(w.findAll('.detail-tab-group')).toHaveLength(4);expect(w.findAll('optgroup')).toHaveLength(4)
 for(const [label,id] of [['任务检索与修复','quests'],['角色改名','rename'],['位置救援','rescue']]){await tab(w,label);expect(w.findAll('#character-section-'+id)).toHaveLength(1);expect(w.text()).not.toContain('未返回此容器记录')}
 await w.get('#character-tab-rescue').trigger('keydown',{key:'End'});await flushPromises();expect(w.get('#character-tab-activity').attributes('aria-selected')).toBe('true')
 }finally{w.unmount()}
})

it('uses compact category navigation, remembers each category and keeps keyboard navigation across groups',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(fixture()))));const w=mount(CharacterDetails,{attachTo:document.body,global:{stubs:{CharacterActivity:{template:'<div>管理记录内容</div>'}}},props:{characNo:4}});try{await flushPromises()
 const category=(name:string)=>w.findAll('.detail-categories button').find(b=>b.text().startsWith(name))!
 expect(w.findAll('.detail-tab-group').filter(g=>g.isVisible())).toHaveLength(1)
 await category('装备与仓储').trigger('click');await flushPromises();expect(w.get('#character-tab-equipment').attributes('aria-selected')).toBe('true')
 await tab(w,'背包道具');await category('角色资料').trigger('click');await flushPromises();expect(w.get('#character-tab-basic').attributes('aria-selected')).toBe('true')
 await category('装备与仓储').trigger('click');await flushPromises();expect(w.get('#character-tab-backpack').attributes('aria-selected')).toBe('true')
 expect(w.findAll('.detail-tab-group').filter(g=>g.isVisible())).toHaveLength(1)
 await w.get('#character-tab-backpack').trigger('keydown',{key:'End'});await flushPromises();expect(category('邮件与记录').attributes('aria-pressed')).toBe('true');expect(w.get('#character-tab-activity').attributes('aria-selected')).toBe('true')
 }finally{w.unmount()}
})
