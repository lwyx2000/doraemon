<script setup lang="ts">
import AppLayout from './layouts/AppLayout.vue'
import { bootstrapSession } from './utils/api'

// 勾选过「自动登录」时，启动即静默换发新 access token：
// 首屏不会因为 24h token 过期闪一下 401，用户全程无需再输密码。
// 失败静默忽略，由真实业务请求的 401 兜底退回登录页。
bootstrapSession()
</script>

<template>
  <AppLayout />
</template>
