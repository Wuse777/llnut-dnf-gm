// @vitest-environment happy-dom
import {it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import GameImage from './GameImage.vue'
const image={state:'ready',url:'/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'+'b'.repeat(64)+'.png',note:'已解析，未验收'}
it('uses authenticated same-origin image endpoint with lazy loading',()=>{
 const w=mount(GameImage,{props:{image,label:'测试道具'}})
 expect(w.find('img').attributes()).toMatchObject({src:image.url,alt:'测试道具',loading:'lazy',decoding:'async'});w.unmount()
})
it('rejects external, data, traversal and status URLs',()=>{
 for(const url of ['https://attacker.test/a.png','//attacker.test/a.png','data:image/svg+xml,bad','/dnf-gm/api/v1/assets/status','/dnf-gm/api/v1/assets/../../bad.png',image.url+'?redirect=bad']){
  const w=mount(GameImage,{props:{image:{...image,url},label:'测试'}});expect(w.find('img').exists()).toBe(false);expect(w.text()).toBe('无图');w.unmount()
 }
})
it('shows explicit fallback for absent assets and never inserts markup from names',()=>{
 const w=mount(GameImage,{props:{label:'<img src=x>',portrait:true}})
 expect(w.find('img').exists()).toBe(false);expect(w.find('[role=img]').attributes('aria-label')).toContain('未安装图片包');expect(w.text()).toBe('头像');w.unmount()
})
it('failed load becomes explicit fallback and resets on asset change',async()=>{
 const w=mount(GameImage,{props:{image,label:'测试'}});await w.find('img').trigger('error');expect(w.find('img').exists()).toBe(false);expect(w.attributes('title')).toContain('读取失败')
 await w.setProps({image:{...image,url:image.url.replace(/b/g,'c')}});expect(w.find('img').exists()).toBe(true);w.unmount()
})
it('keeps a small client icon at its integer source dimensions instead of stretching it',()=>{
 const w=mount(GameImage,{props:{image:{...image,width:28,height:28},label:'像素图标'}})
 expect(w.get('img').attributes('style')).toContain('width: 28px');expect(w.get('img').attributes('style')).toContain('height: 28px');w.unmount()
})
it('colors an explicitly supplied quality label and keeps absent raw metadata neutral',async()=>{
 const w=mount(GameImage,{props:{image,label:'测试',rarityName:'史诗'}})
 expect(w.classes()).toContain('quality-epic');expect(w.attributes('title')).toContain('史诗')
 await w.setProps({rarityName:undefined});expect(w.classes().some(c=>c.startsWith('quality-'))).toBe(false);w.unmount()
})
it('groups an explicit PVF number without inventing a quality name',()=>{
 const w=mount(GameImage,{props:{image,label:'测试',rarity:4}})
 expect(w.classes()).toContain('quality-raw-4');expect(w.attributes('title')).toContain('PVF 品级 4');expect(w.attributes('title')).not.toContain('史诗');w.unmount()
})
