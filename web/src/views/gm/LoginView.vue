<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useGmWorkspace } from '@/stores/gm/useGmWorkspace';
const gm = useGmWorkspace();
const route = useRoute(); const router = useRouter();
const redirect = computed(() => { const value = String(route.query.redirect || '/home'); return value.startsWith('/') && !value.startsWith('//') ? value : '/home'; });
async function login() { await gm.login(); if (gm.logged) await router.replace(redirect.value); }
</script>
<template>
 <main class="gm-login">
  <div class="gm-login-shell">
   <section class="gm-login-story" aria-label="DNF GM 工作台">
    <div class="gm-login-brand"><SystemLogo class="gm-login-mark"/><span>DNF <strong>GM</strong><small>GAME MASTER WORKSPACE</small></span></div>
    <div class="gm-login-welcome"><span class="gm-eyebrow">WELCOME BACK TO ARAD</span><h1>欢迎回到阿拉德</h1><p>从角色查询到奖励发放，<br>让日常管理更清晰。</p></div>
    <div class="gm-login-grid"><span><SvgIcon icon="lucide:users-round"/>玩家与角色</span><span><SvgIcon icon="lucide:gift"/>奖励与邮件</span><span><SvgIcon icon="lucide:swords"/>外观与道具</span><span><SvgIcon icon="lucide:shield-check"/>维护与审计</span></div>
   </section>
   <NCard class="gm-login-form" :bordered="false">
    <div class="gm-login-mobile-brand"><SystemLogo/><span>DNF <strong>GM</strong></span></div>
    <span class="gm-eyebrow">ADMINISTRATOR ACCESS</span><h2>登录工作台</h2><p class="muted gm-login-description">使用管理员账号，继续你的管理工作</p>
    <NForm @submit.prevent="login">
     <NFormItem label="管理员账号"><NInput v-model:value="gm.username" size="large" placeholder="请输入管理员账号" autocomplete="username" /></NFormItem>
     <NFormItem label="密码"><NInput v-model:value="gm.password" size="large" type="password" placeholder="请输入密码" show-password-on="click" autocomplete="current-password" /></NFormItem>
     <NFormItem v-if="gm.totpRequired" label="动态验证码"><NInput v-model:value="gm.code" size="large" inputmode="numeric" autocomplete="one-time-code" /></NFormItem>
     <NAlert v-if="gm.error" type="error" class="mb-16px">{{ gm.error }}</NAlert>
     <NButton type="primary" attr-type="submit" block size="large" :loading="gm.busy" :disabled="gm.initializing">进入工作台</NButton>
    </NForm><small class="muted gm-login-footer">DNF GM · 基于 SoybeanAdmin</small>
   </NCard>
  </div>
 </main>
</template>

