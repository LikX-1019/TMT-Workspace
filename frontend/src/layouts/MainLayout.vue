<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

function signOut(): void {
  auth.signOut()
  void router.push({ name: 'login' })
}
</script>

<template>
  <el-container class="workspace-shell">
    <el-aside width="248px" class="workspace-aside">
      <div class="brand">
        <span class="brand-mark">TMT</span>
        <span class="brand-name">Workspace</span>
      </div>
      <el-menu :default-active="route.path" router class="workspace-menu">
        <el-menu-item index="/">首页</el-menu-item>
        <el-menu-item index="/profile">个人中心</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="workspace-header" height="64px">
        <div />
        <el-dropdown>
          <span class="operator">账号</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="signOut">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="workspace-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

