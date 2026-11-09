/** Loopback-only synthetic UI verification. Screenshots do not contain real players or game evidence. */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve, sep, extname } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('../web/dist/', import.meta.url));
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (req.method !== 'GET' || !url.pathname.startsWith('/dnf-gm/')) throw Error('outside fixture');
    const path = resolve(root, decodeURIComponent(url.pathname.slice('/dnf-gm/'.length) || 'index.html'));
    if (!path.startsWith(root.endsWith(sep) ? root : root + sep)) throw Error('outside fixture');
    const filename = extname(path) ? path : resolve(root, 'index.html');
    const contents = await readFile(filename);
    res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp' })[extname(filename)] || 'application/octet-stream' });
    res.end(contents);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
const output = process.env.DNF_GM_BROWSER_OUTPUT || 'outputs/workspace-redesign-synthetic';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage(), calls = [], errors = [];
const mobileRewardFirstViewports = [];
page.on('pageerror', e => errors.push(e.message));
const uid = 900001, characNo = 900011, pvf = 'a'.repeat(64);
const account = { uid, accountname: '合成测试账号', cera: 1050, cera_point: 0, mileage: 0, login_status: 0, channel: 0, online: { login_status: 0, channel: 0 } };
const character = { uid, charac_no: characNo, charac_name: '合成测试剑魂', lev: 60, delete_flag: 0, job: 0, grow_type: 1, max_fatigue: 156, fatigue: 78, last_play_time: '2026-11-09 12:00:00' };
const names = ['合成 · 裂创心灵之刃', '合成 · 远古记忆长剑', '合成 · 神秘的魔力结晶', '合成 · 复活药剂', '合成 · 强化保护券', '合成 · 精炼时空石', '合成 · 勇者之心护肩', '合成 · 黄金小晶块'];
const items = names.map((name, i) => ({ id: 990001 + i, name, category: i < 2 || i === 6 ? 'equipment' : 'material', type_name: i < 2 ? '装备' : '材料', part_name: i < 2 ? '武器' : i === 6 ? '头肩' : '', rarity_name: ['神器', '史诗', '稀有', '高级'][i % 4], level: 60, single_item: i < 2, quantity: 1, sendable: true, policy_state: i === 1 ? 'verified' : 'trial', policy_reason: '合成 UI 夹具；未实际投递', pvf_sha256: pvf, usable_jobs: [{ name: '鬼剑士' }], base_attributes: [{ tag: 'physical_attack', label: '物理攻击力', values: [520] }, { tag: 'strength', label: '力量', values: [35] }] }));
const stored = items.map((item, slot) => ({ ...item, slot, slot_label: slot === 0 ? '武器' : '', type: 1, enhancement: slot === 0 ? 12 : 0, forge: 0, durability: 33, amplify_type: 0, amplify_value: 0, orb_id: 0, sealed_raw: 0, empty: false }));
const overview = { character, account, profession: { name: '剑魂', base_name: '鬼剑士', note: '合成名称' }, account_online: { login_status: 0, channel: 0 }, play_state: { fatigue: 78, last_play_time: character.last_play_time }, wealth: { state: 'ok', gold: 12345678, revival_coin_raw: 3 }, attributes: [], collected_at: Date.now() / 1000, catalog_state: 'ok', snapshot_note: '合成浏览器快照，非真实玩家', equipment: { state: 'ok', slot_count: 12, items: stored.slice(0, 3) }, backpack_summary: { state: 'ok', occupied_slots: 24, slot_count: 120, items: stored.slice(2), has_more: true }, support_summary: { state: 'ok', open_count: 1, in_progress_count: 1, items: [{ case_id: 'c'.repeat(32), title: '合成 · 玩家反馈背包位置异常', status: 'open', scope: 'character' }] }, mail_summary: { state: 'ok', checked_attachments: 32, unclaimed_marker: 2, scope: 'recent_200_attachments', client_verified: false } };
const workbench = { checked_at: Date.now() / 1000, sections: [{ key: 'support', label: '玩家问题', items: [{ id: 'c'.repeat(32), title: '合成 · 背包道具异常待排查', uid, charac_no: characNo, status: 'open', path: '/players/support' }] }, { key: 'operations', label: '奖励提交待核对', items: [{ id: 'b'.repeat(32), title: '合成 · 奖励提交结果待核对', target_uid: uid, status: 'uncertain', path: '/system/audit' }] }, { key: 'batches', label: '批量奖励', items: [] }, { key: 'schedules', label: '今日计划与异常', items: [] }], management_backup: { state: 'ok' }, game_backup: { worker: { configured: false } }, task_health: { state: 'unknown' }, note: '合成 UI 快照，不代表真实任务、客户端领取或备份恢复验证。' };
const caseId = 'c'.repeat(32), campaignId = 'd'.repeat(32), backupId = 'e'.repeat(32);
const supportCase = {case_id:caseId,uid,charac_no:characNo,title:'合成 · 奖励未到账',category:'mail',description:'玩家反馈未看到物品；合成界面验收数据。',status:'open',revision:1,compensation_count:0,target:{accountname:account.accountname,character},updated_at:Date.now()/1000};
const campaign = {id:campaignId,name:'合成 · 秋日回归补给',status:'active',activated:1,revision:1,definition:{name:'合成 · 秋日回归补给',description:'固定礼包版本与去重对象的合成示例',dedupe:'account',targets:{mode:'filtered',tags_all:['回归'],min_level:40,max_level:60,job:null},template_id:7,template_version:2},reward:{},claims:{subjects:25,accounts:25},totals:[{metric:'cera',amount:'2500'}],links:[],job_draft:{campaign_id:campaignId,targets:{mode:'filtered'},reward:{},account_reward_mode:'once_per_account',reason:'合成活动'},note:'合成数据；数据库提交不等于领取'};
const backup = {run_id:backupId,backup_id:backupId,action:'backup',state:'succeeded',reason:'合成 · 每周玩家存档恢复点',window_id:'f'.repeat(32),created_at:Date.now()/1000-7200,finished_at:Date.now()/1000-7000,related_runs:[],result:{synthetic:true,artifact_sha256:'1'.repeat(64)}};
backup.evidence={artifact_sha256:'1'.repeat(64),backup:{...backup},copy:{latest_attempt:{action:'copy',state:'failed',finished_at:Date.now()/1000-6000},verified_run:null},rehearse:{latest_attempt:null,verified_run:null}};
await context.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url());
  if (url.origin !== origin) { errors.push(`Unexpected external request ${url.origin}`); return route.abort(); }
  if (!url.pathname.startsWith('/dnf-gm/api/v1/')) return route.continue();
  const path = url.pathname.split('/api/v1')[1]; calls.push({ path, method: req.method() });
  let data, status = 200;
  if (req.method() === 'POST' && path === '/players/visit') data = { ok: true };
  else if (req.method() !== 'GET') { errors.push(`Unexpected mutation ${path}`); status = 500; data = { detail: 'Unexpected synthetic mutation' }; }
  else if (path === '/auth/methods') data = { totp_required: false };
  else if (path === '/auth/me') data = { csrf: 'synthetic', username: 'admin' };
  else if (path === '/ui-preferences/layout/default') data = { payload: null, version: 0, pvf_sha256: pvf };
  else if (path === '/overview') data = { counts: { accounts: 1, characters: 1, online_accounts: 0 }, server: { fresh: true, core_ok: true, services: {} }, enabled_writes: [] };
  else if (path === '/workbench') data = workbench;
  else if (path === '/players/collections') data = { items: [], total: 0, page_size: 12 };
  else if (path === '/catalog') data = { items, metadata: { pvf_sha256: pvf }, facets: {}, total: items.length };
  else if (path === '/accounts') data = { items: [account] };
  else if (path === `/accounts/${uid}`) data = { ...account, characters: [character] };
  else if (path === `/accounts/${uid}/preference`) data = { notes: '', tags: [], version: 0 };
  else if (path === '/characters') data = { items: [character] };
  else if (path === `/characters/${characNo}/overview`) data = overview;
  else if (path === `/characters/${characNo}`) data = { ...overview, backpack: { state: 'ok', slot_count: 120, items: stored }, warehouse: { state: 'ok', slot_count: 0, items: [] } };
  else if (path === '/support/cases') data = {items:[supportCase],has_more:false,page:1};
  else if (path === `/support/cases/${caseId}`) data = {case:supportCase,events:[],links:[],events_has_more:false,links_has_more:false};
  else if (path === `/support/profiles/${uid}`) data = {uid,revision:0,notes:'',tags:['回归'],target:{uid,accountname:account.accountname}};
  else if (path === '/mail-center') data = {items:[],has_more:false};
  else if (path === '/campaigns/audience-schema') data = {character_dates:{available:true,note:'角色存档日期'},returning:{note:'仅离线'},account_registration:{available:false}};
  else if (path === '/campaigns') data = {items:[campaign],has_more:false};
  else if (path === `/campaigns/${campaignId}`) data = campaign;
  else if (path === `/game-backups/${backupId}`) data = backup;
  else if (path === '/game-backups') data = {items:[backup],worker:{configured:true,copy_configured:false,rehearsal_configured:false},has_more:false};
  else { errors.push(`Unexpected API ${path}`); status = 500; data = { detail: `Unexpected synthetic route ${path}` }; }
  await route.fulfill({ status, json: data });
});
async function visit(path) { await page.goto(`${origin}/dnf-gm${path}`); await page.locator('.gm-page.gm-workspace').waitFor(); }
async function screenshot(name) {
  await page.mouse.move(0, 0);
  await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Viewport overflow: ${name}`);
  await page.screenshot({ path: `${output}/${name}.png` });
}
async function assertMobileRewardFirstViewport(name) {
  await page.locator('.picker-item').first().waitFor();
  assert.equal(await page.locator('.mail-workbench-frame').getAttribute('data-pane'), 'items', `${name}: empty draft must open on items`);
  assert.equal(await page.locator('.recipient-summary').count(), 1, `${name}: one target identity row`);
  assert.equal(await page.locator('.recipient-context').count(), 0, `${name}: full target selector is collapsed`);
  assert.equal(await page.locator('.player-shortcuts').count(), 0, `${name}: no repeated target card`);
  const summary = await page.locator('.recipient-summary').boundingBox();
  assert(summary && summary.height <= 40, `${name}: target summary must remain one compact row`);
  const viewport = page.viewportSize(), boxes = {};
  for (const [key, locator] of [
    ['search', page.getByRole('textbox', { name: '物品搜索', exact: true })],
    ['firstItem', page.locator('.picker-item').first()],
    ['firstAddButton', page.locator('.picker-item').first().getByRole('button', { name: '加入清单', exact: true })]
  ]) {
    assert.equal(await locator.isVisible(), true, `${name}: ${key} must be visible`);
    const box = await locator.boundingBox();
    assert(box && box.x >= 0 && box.x + box.width <= viewport.width && box.y >= 48 && box.y + box.height <= viewport.height,
      `${name}: ${key} must fit fully in the initial ${viewport.width}×${viewport.height} viewport; got ${JSON.stringify(box)}`);
    boxes[key] = box;
  }
  mobileRewardFirstViewports.push({ name, viewport, summary, ...boxes });
}
try {
  await visit('/home'); await page.getByRole('heading', { name: '统一待办' }).waitFor(); await screenshot('desktop-home');
  await visit('/items/catalog'); await page.locator('.picker-item').first().waitFor();
  assert.equal(await page.locator('.picker-card-grid--list').count(), 1);
  const row = page.locator('.picker-item').first(); assert.equal(Math.round((await row.boundingBox()).height), 56);
  assert.equal(await row.getByRole('button', { name: '加入清单', exact: true }).count(), 1);
  await screenshot('desktop-catalog');
  await row.getByRole('button', { name: /查看物品详情/ }).hover(); await page.locator('.item-hover-facts').first().waitFor({ state: 'visible' }); await page.screenshot({ path: `${output}/desktop-item-hover.png` });
  await row.getByRole('button', { name: /查看物品详情/ }).click(); await page.getByRole('dialog', { name: `物品详情 · #${items[0].id}`, exact: true }).waitFor(); await screenshot('desktop-item-detail'); await page.keyboard.press('Escape');
  await visit(`/characters/${characNo}`); await page.locator('[data-testid=character-overview]').waitFor();
  assert.equal(calls.some(c => c.path === `/characters/${characNo}`), false, 'Full character must remain lazy');
  await screenshot('desktop-character');
  await page.getByRole('button', { name: '全部装备 →', exact: true }).click(); await page.getByText('正在按需读取此页的完整存档…').waitFor({ state: 'hidden' });
  assert(calls.some(c => c.path === `/characters/${characNo}`));
  await page.setViewportSize({ width: 390, height: 844 });
  await visit(`/characters/${characNo}`); await page.locator('[data-testid=character-overview]').waitFor();
  assert.equal(await page.locator('[data-tab-id]').count(), 0, 'Phone must not mount workspace tabs');
  assert.equal(await page.locator('.gm-mobile-route-title').textContent(), '角色工作区'); await screenshot('mobile-character');
  await visit('/items/catalog'); await page.locator('.picker-item').first().waitFor();
  assert.equal(Math.round((await page.locator('.picker-item').first().boundingBox()).height), 58); await screenshot('mobile-catalog');
  await visit(`/rewards/compose?uid=${uid}&charac_no=${characNo}`); await page.getByRole('button', { name: '更换目标', exact: true }).waitFor();
  await assertMobileRewardFirstViewport('mobile-reward');
  await screenshot('mobile-reward');
  await page.getByRole('button', { name: /奖励与预览/ }).click();
  await page.locator('#mail-gold').fill('19'); await page.locator('#operation-reason').fill('合成 · 保留未提交草稿');
  await page.reload(); await page.locator('.recipient-summary').waitFor();
  assert.equal(await page.locator('.mail-workbench-frame').getAttribute('data-pane'), 'draft', 'Reload must preserve a nonempty mobile reward draft');
  assert.equal(await page.locator('#mail-gold').inputValue(), '19');
  assert.equal(await page.locator('#operation-reason').inputValue(), '合成 · 保留未提交草稿');
  await screenshot('mobile-reward-restored-draft');
  await page.getByRole('button', { name: '更换目标', exact: true }).click();
  await page.getByRole('combobox', { name: '收件角色', exact: true }).waitFor();
  assert.equal(await page.locator('#mail-gold').inputValue(), '19', 'Opening recipient selector must retain draft');
  await page.getByRole('button', { name: '收起搜索', exact: true }).click();
  await page.locator('#mail-gold').fill('0'); await page.locator('#operation-reason').fill('');
  await visit('/home'); await page.getByRole('heading', { name: '统一待办' }).waitFor(); await screenshot('mobile-home');
  await page.getByRole('button', { name: '主题模式', exact: true }).click(); await page.locator('html.dark').waitFor(); await screenshot('mobile-home-dark');
  const matrix=[];
  for (const [device,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
    await page.setViewportSize({width,height});
    for (const scheme of ['light','dark']) {
      await visit('/home');await page.getByRole('heading',{name:'统一待办'}).waitFor();
      for(let n=0;n<3&&await page.locator('html').evaluate(el=>el.classList.contains('dark'))!==(scheme==='dark');n++)await page.getByRole('button',{name:'主题模式',exact:true}).click();
      await screenshot(`${device}-home-${scheme}`);
      const colors=await page.evaluate(()=>({dark:document.documentElement.classList.contains('dark'),card:getComputedStyle(document.querySelector('.home-search-card')).backgroundColor,input:getComputedStyle(document.querySelector('.home-player-search .n-input')).backgroundColor,primary:getComputedStyle(document.querySelector('.home-player-search .n-button')).color,primaryBackground:getComputedStyle(document.querySelector('.home-player-search .n-button')).backgroundColor,header:getComputedStyle(document.querySelector('.shadow-header')).backgroundColor}));
      assert.equal(colors.dark,scheme==='dark');assert.equal(colors.card,scheme==='dark'?'rgb(38, 42, 38)':'rgb(255, 254, 251)');assert.equal(colors.input,colors.card);matrix.push({device,scheme,colors});
      for(const [name,path,ready] of [
        ['catalog','/items/catalog','.picker-item'],['character',`/characters/${characNo}`,'[data-testid=character-overview]'],
        ['reward',`/rewards/compose?uid=${uid}&charac_no=${characNo}`,'.picker-item'],
        ['campaign',`/rewards/campaigns?campaign_id=${campaignId}`,'.campaigns'],
        ['backups',`/system/game-backups?run_id=${backupId}`,'[aria-label="游戏备份请求详情"]'],
        ['investigation',`/players/support?uid=${uid}&case_id=${caseId}`,'[aria-label="问题详情"]']]) {
        await visit(path);await page.locator(ready).first().waitFor();
        if(name==='reward'&&device==='mobile')await assertMobileRewardFirstViewport(`${device}-${name}-${scheme}`);
        if(name==='campaign')await page.getByRole('button',{name:'准备本活动批量发放',exact:true}).waitFor();
        if(name==='investigation'){await page.getByRole('button',{name:'开始场景排查',exact:true}).click();await page.getByRole('region',{name:'玩家场景排查'}).waitFor();await page.getByRole('button',{name:'装备异常',exact:true}).click();await page.getByText('当前角色存档',{exact:true}).waitFor();await page.getByText(character.charac_name,{exact:false}).first().waitFor();await page.locator('.investigation').scrollIntoViewIfNeeded();if(width>800){const buttons=await page.locator('.investigation-tabs>button').all();const tops=await Promise.all(buttons.map(b=>b.boundingBox().then(r=>r.y)));assert(Math.max(...tops)-Math.min(...tops)<2,'Desktop investigation scenes must stay in one row')}assert.equal(await page.locator('.investigation-check').first().evaluate(el=>getComputedStyle(el).flexDirection),'row');}
        await screenshot(`${device}-${name}-${scheme}`);
      }
    }
  }
  assert.deepEqual(errors, []);
  const mutations = calls.filter(c => c.method !== 'GET'); assert(mutations.every(c => c.path === '/players/visit' && c.method === 'POST'));
  const report = { ok: true, synthetic: true, production_contact: false, game_mutations: false, read_only_ui_plus_visit_preferences: true, desktop_mobile: true, lazy_character_detail: true, compact_picker_rows: true, mobile_reward_nonempty_draft_restored: true, mobileRewardFirstViewports, no_viewport_overflow: true, matrix, errors, calls };
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); console.log(JSON.stringify({...report,calls:undefined,request_count:calls.length}));
} catch (error) { await page.screenshot({ path: `${output}/failure.png` }); console.error(JSON.stringify({ errors, calls, url: page.url(), body: (await page.locator('body').innerText()).slice(0, 12000) })); throw error; } finally { await browser.close(); await new Promise(r => server.close(r)); }
