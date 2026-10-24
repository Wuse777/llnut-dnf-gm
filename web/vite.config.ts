import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({base:'/dnf-gm/',plugins:[vue()],server:{proxy:{'/dnf-gm/api':'http://127.0.0.1:8765'}}})
