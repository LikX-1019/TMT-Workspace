<template>
  <section class="page-heading">
    <h1>个人中心</h1>
    <p>账号信息与安全设置将在后续阶段接入。</p>
    <div v-if="auth.currentUser" class="identity-summary">
      <p>姓名：{{ auth.currentUser.name }}（{{ auth.currentUser.username }}）</p>
      <p>角色：{{ auth.currentUser.roles.length ? auth.currentUser.roles.join('、') : '未分配' }}</p>
      <p>权限数量：{{ auth.currentUser.permissions.length }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

// Phase 2A: /auth/me now carries roles and effective permission codes.
// Display only — visible menu or labels never count as authorization.
const auth = useAuthStore()
</script>
