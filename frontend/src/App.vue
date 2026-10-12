<template>
  <div class="layout">
    <header class="header">
      <div class="title">
        <h1>智慧工地安全巡检平台</h1>
        <span class="subtitle">端云协同 · 边缘 YOLOv8 检测 + 云端大模型研判</span>
        <el-tag size="small" type="info" class="mode-tag">{{ mode }}</el-tag>
      </div>
      <el-menu
        :default-active="activeRoute"
        mode="horizontal"
        router
        class="nav"
      >
        <el-menu-item index="/inspect">图片巡检</el-menu-item>
        <el-menu-item index="/monitor">实时监控</el-menu-item>
        <el-menu-item index="/help">使用说明</el-menu-item>
      </el-menu>
    </header>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getHealth } from '../api'

const route = useRoute()
const activeRoute = ref(route.path)
const mode = ref('加载中...')

onMounted(async () => {
  try {
    const { data } = await getHealth()
    mode.value = `${data.mode}（模型：${data.model}）`
  } catch {
    mode.value = '后端未连接（请先启动 FastAPI）'
  }
})
</script>

<style scoped>
.layout {
  min-height: 100vh;
  background: #f5f7fa;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.title h1 {
  font-size: 18px;
  margin: 0;
  color: #1f2937;
}
.subtitle {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin: 2px 0;
}
.mode-tag {
  margin-top: 2px;
}
.nav {
  border-bottom: none;
}
.main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 20px;
}
.mode-badge {
  display: none;
}
</style>
