<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit(): Promise<void> {
  loading.value = true

  try {
    await auth.signIn(form)
    await router.push({ name: 'home' })
  } catch {
    // 统一通用失败提示，不区分用户名不存在与密码错误。
    ElMessage.error('用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <form class="login-panel" @submit.prevent="submit">
      <p class="login-brand">TMT Workspace</p>
      <h1>登录</h1>
      <el-input v-model="form.username" autocomplete="username" placeholder="用户名" size="large" />
      <el-input
        v-model="form.password"
        type="password"
        autocomplete="current-password"
        placeholder="密码"
        size="large"
        show-password
      />
      <el-button type="primary" size="large" native-type="submit" :loading="loading">登录</el-button>
    </form>
  </main>
</template>
