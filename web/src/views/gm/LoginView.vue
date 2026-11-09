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
 <div class="gm-login">
  <div class="gm-login-story"><SystemLogo class="gm-login-mark"/><span class="gm-eyebrow">DNF · GAME MASTER</span><h1>每一次操作，<br>都有清晰的落点。</h1><p>从玩家出发，连接角色、道具和运营。<br>欢迎回到你的 GM 工作台。</p><div class="gm-login-grid"><span>玩家与角色</span><span>奖励与邮件</span><span>外观与道具</span><span>维护与审计</span></div></div>
  <NCard class="gm-login-form" :bordered="false"><span class="gm-eyebrow">WORKSPACE ACCESS</span><h2>登录工作台</h2><p class="muted gm-login-description">使用现有管理员账号继续</p><NForm @submit.prevent="login"><NFormItem label="管理员账号"><NInput v-model:value="gm.username" autocomplete="username" /></NFormItem><NFormItem label="密码"><NInput v-model:value="gm.password" type="password" show-password-on="click" autocomplete="current-password" /></NFormItem><NFormItem v-if="gm.totpRequired" label="动态验证码"><NInput v-model:value="gm.code" inputmode="numeric" autocomplete="one-time-code" /></NFormItem><NAlert v-if="gm.error" type="error" class="mb-16px">{{ gm.error }}</NAlert><NButton type="primary" attr-type="submit" block size="large" :loading="gm.busy" :disabled="gm.initializing">进入工作台</NButton></NForm><small class="muted gm-login-footer">DNF GM · 基于 SoybeanAdmin</small></NCard>
 </div>
</template>

