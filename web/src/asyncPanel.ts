import {defineAsyncComponent,defineComponent,h,type Component} from 'vue'

const PanelLoading=defineComponent({setup:()=>()=>h('p',{class:'panel-loading',role:'status'},[h('span',{class:'spinner','aria-hidden':'true'}),'正在载入工作区…'])})
const PanelError=defineComponent({setup:()=>()=>h('div',{class:'submit-error',role:'alert'},[
 h('p','工作区资源载入失败，请刷新页面后重新打开。尚未提交的草稿会在刷新后清空。'),
 h('button',{type:'button',onClick:()=>window.location.reload()},'刷新页面')
])})

/** Load a workspace only when it is opened; keep network failure visible. */
export function asyncPanel<T extends Component>(loader:()=>Promise<{default:T}>){
 return defineAsyncComponent({loader,loadingComponent:PanelLoading,errorComponent:PanelError,delay:120,timeout:20000})
}
