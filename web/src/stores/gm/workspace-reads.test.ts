// @vitest-environment happy-dom
import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises} from '@vue/test-utils'
import {workspaceFixture} from './workspace.test-helper'

const cleanups:(()=>void)[]=[]
afterEach(()=>{cleanups.splice(0).forEach(cleanup=>cleanup());sessionStorage.clear();vi.unstubAllGlobals()})
const response=(value:unknown)=>new Response(JSON.stringify(value))
function deferred(){let resolve!:(response:Response)=>void;const promise=new Promise<Response>(done=>{resolve=done});return {promise,resolve}}
function fixture(){const value=workspaceFixture();cleanups.push(value.cleanup);return value}

it('replaces a slow list query when entering another page without locking the draft',async()=>{
 const {gm,fetcher}=fixture(),slow=deferred(),original=fetcher.getMockImplementation()!
 let oldSignal:AbortSignal|undefined
 fetcher.mockImplementation((url,options={})=>{
  const path=String(url)
  if(path.includes('/accounts?')){oldSignal=options.signal;return slow.promise}
  if(path.endsWith('/online?page=1'))return Promise.resolve(response({items:[{uid:9,accountname:'online-player'}]}))
  return original(url,options)
 })
 gm.tab='accounts';const old=gm.searchRows();await flushPromises()
 expect(gm.readBusy.list).toBe(true);expect(gm.busy).toBe(false)
 await gm.activate('online',false);await gm.searchAccounts()
 expect(oldSignal?.aborted).toBe(true);expect(gm.rows.map(row=>row.uid)).toEqual([9])
 slow.resolve(response({items:[{uid:1,accountname:'stale'}]}));await old
 expect(gm.rows.map(row=>row.uid)).toEqual([9]);expect(gm.readBusy.list).toBe(false)
})

it('shares identical concurrent overview reads and does not cache live server snapshots',async()=>{
 const {gm,fetcher}=fixture(),slow=deferred(),original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((url,options={})=>String(url).endsWith('/overview')?slow.promise:original(url,options))
 const first=gm.load(),second=gm.load();await flushPromises()
 expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith('/overview'))).toHaveLength(1)
 slow.resolve(response({counts:{accounts:8}}));await Promise.all([first,second]);expect(gm.overview.counts.accounts).toBe(8)
 await gm.load();expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith('/overview'))).toHaveLength(2)
})

it('blocks writes during target restoration and applies only the newest target',async()=>{
 const {gm,fetcher,target,calls}=fixture();await target(3,30)
 const slow=deferred(),original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((url,options={})=>String(url).endsWith('/accounts/4')?slow.promise:original(url,options))
 const old=gm.setTarget(4,40);await flushPromises()
 expect(gm.targetBusy).toBe(true);await gm.makePreview()
 expect(calls.filter(call=>call.path==='/operations/preview')).toHaveLength(0)
 expect(await gm.setTarget(5,50)).toBe(true)
 gm.mailGold=17
 slow.resolve(response({uid:4,accountname:'stale'}));expect(await old).toBe(false)
 expect(gm.account.uid).toBe(5);expect(gm.selectedRole).toBe(50);expect(gm.mailGold).toBe(17)
 expect(gm.players.workspaces[4]).toBeUndefined();expect(gm.targetBusy).toBe(false)
 gm.pendingId='a'.repeat(32);expect(await gm.setTarget(6,60)).toBe(false)
 expect(gm.account.uid).toBe(5);expect(gm.pendingId).toBe('a'.repeat(32))
})

it('does not restore a target or its player cache after logout',async()=>{
 const {gm,fetcher}=fixture(),slow=deferred(),original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((url,options={})=>String(url).endsWith('/accounts/3')?slow.promise:original(url,options))
 const opened=gm.setTarget(3,30);await flushPromises();gm.clearSession()
 slow.resolve(response({uid:3,accountname:'stale'}));expect(await opened).toBe(false)
 expect(gm.account).toBeNull();expect(gm.players.workspaces).toEqual({});expect(gm.targetBusy).toBe(false)
})

it('ignores a slow balance refresh after switching the player',async()=>{
 const {gm,fetcher,target}=fixture();await target(3,30)
 const slow=deferred(),original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((url,options={})=>String(url).endsWith('/accounts/3')?slow.promise:original(url,options))
 const refresh=gm.refreshAccount();await flushPromises();expect(gm.busy).toBe(false)
 await gm.setTarget(4,40);slow.resolve(response({uid:3,accountname:'stale',cera:999}));await refresh
 expect(gm.account.uid).toBe(4);expect(gm.account.cera).toBe(100)
})

it('allows preview during an unrelated read and preserves the original pending ID across logout',async()=>{
 const {gm,fetcher,target,calls}=fixture();await target(3,30)
 const lookup=deferred(),commit=deferred(),original=fetcher.getMockImplementation()!
 fetcher.mockImplementation((url,options={})=>{
  if(String(url).endsWith('/operations/'+'b'.repeat(32)))return lookup.promise
  if(String(url).endsWith('/confirm'))return commit.promise
  return original(url,options)
 })
 const query=gm.inspectOperation('b'.repeat(32));await flushPromises();expect(gm.busy).toBe(false)
 await gm.makePreview();expect(gm.preview.operation_id).toBe('a'.repeat(32))
 const submitted=gm.confirmOperation();await flushPromises();expect(gm.pendingId).toBe('a'.repeat(32))
 gm.clearSession();commit.resolve(response({operation_id:'a'.repeat(32),status:'committed'}));await submitted
 lookup.resolve(response({operation_id:'b'.repeat(32),status:'committed'}));await query
 expect(gm.operationResult).toBeNull();expect(gm.lookedUp).toBeNull();expect(gm.pendingId).toBe('a'.repeat(32))
 expect(sessionStorage.getItem('dnf-gm.pending-operation')).toBe('a'.repeat(32))
 expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith('/confirm'))).toHaveLength(1)
 expect(calls.filter(call=>call.path==='/operations/preview')).toHaveLength(1)
})
