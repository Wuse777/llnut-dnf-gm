import {defineStore} from 'pinia'
import {ref} from 'vue'
export type CatalogState={filters:Record<string,any>,page:number,comparison:any[],pvf:string}
export const useGmCatalogStore=defineStore('gm-catalog',()=>{const contexts=ref<Record<string,CatalogState>>({});function clear(){contexts.value={}}return {contexts,clear}})
