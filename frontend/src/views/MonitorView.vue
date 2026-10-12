<template>
  <div class="monitor-view">
    <el-card>
      <template #header><span>摄像头选择</span></template>
      <div class="controls">
        <el-button :icon="Search" @click="doDiscover" :loading="discovering">
          搜索摄像头
        </el-button>
        <el-select
          v-model="selected"
          placeholder="选择摄像头（本地 / 手机 / 网络）"
          class="source-select"
        >
          <el-option
            v-for="c in choices"
            :key="c.value"
            :label="c.label"
            :value="c.value"
          />
        </el-select>
        <el-input
          v-model="netUrl"
          placeholder="网络/手机摄像头地址，如 http://手机IP:8080/video 或 rtsp://..."
          class="net-input"
          @keyup.enter="doAddNet"
        />
        <el-button @click="doAddNet">添加</el-button>
        <el-button
          type="primary"
          :disabled="!selected"
          :loading="starting"
          @click="doStart"
        >
          开启监控
        </el-button>
        <el-button type="danger" :disabled="!monitoring" @click="doStop">
          停止监控
        </el-button>
      </div>
      <div class="tip">
        手机摄像头：安装 IP Webcam / DroidCam 后，将地址粘贴到输入框点击「添加」即可。
      </div>
    </el-card>

    <el-row :gutter="16" class="main-row">
      <el-col :span="16">
        <el-card>
          <template #header><span>实时画面（边缘端逐帧检测 / 危险区预警）</span></template>
          <div class="stream-box">
            <img v-if="monitoring" :src="streamSrc" class="stream" alt="实时监控画面" />
            <el-empty v-else description="监控未开启" :image-size="120" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header><span>告警与操作</span></template>
          <el-alert
            :title="alert || '未开启监控'"
            :type="intrusionCount > 0 ? 'error' : 'info'"
            show-icon
            :closable="false"
            class="alert"
          />
          <div class="counts">
            <el-tag
              v-for="(v, k) in counts"
              :key="k"
              size="default"
              class="count-tag"
            >
              {{ k }}：{{ v }}
            </el-tag>
          </div>
          <div class="ops">
            <el-button :icon="Camera" :disabled="!monitoring" @click="doShot">
              主动截屏
            </el-button>
            <el-button
              type="success"
              :icon="Document"
              :disabled="!monitoring"
              :loading="reporting"
              @click="doReport"
            >
              生成云端研判报告
            </el-button>
          </div>
        </el-card>

        <el-card class="gallery-card">
          <template #header><span>截图与告警记录</span></template>
          <div class="gallery">
            <div v-for="item in gallery" :key="item.name" class="shot">
              <el-image :src="shotUrl(item.name)" fit="cover" class="shot-img" />
              <div class="shot-meta">[{{ item.tag }}] {{ item.ts }} · {{ item.note }}</div>
            </div>
            <el-empty v-if="!gallery.length" description="暂无截图" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="reportVisible" title="云端研判报告" width="60%">
      <div class="report pre-wrap">{{ reportText }}</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Camera, Document } from '@element-plus/icons-vue'
import {
  getCameras,
  addNetCam,
  startMonitor,
  stopMonitor,
  getState,
  screenshot,
  getReport,
  getGallery,
  streamUrl,
  shotUrl
} from '../api'

const choices = ref([])
const selected = ref('')
const netUrl = ref('')
const discovering = ref(false)
const starting = ref(false)
const reporting = ref(false)
const monitoring = ref(false)
const alert = ref('未开启监控')
const counts = ref({})
const intrusionCount = ref(0)
const gallery = ref([])
const reportVisible = ref(false)
const reportText = ref('')
const streamKey = ref(0)

// MJPEG 流地址（加 key 防缓存，重新开监控时刷新）
const streamSrc = computed(() => `${streamUrl}?t=${streamKey.value}`)

let timer = null

async function refreshState() {
  try {
    const { data } = await getState()
    monitoring.value = data.monitoring
    alert.value = data.alert
    counts.value = data.counts
    intrusionCount.value = data.intrusion_count
  } catch {
    /* 后端短暂不可用时静默 */
  }
}

async function refreshGallery() {
  try {
    const { data } = await getGallery()
    gallery.value = data.items
  } catch {
    /* ignore */
  }
}

async function doDiscover() {
  discovering.value = true
  try {
    const { data } = await getCameras()
    choices.value = data.choices
    selected.value = data.value || ''
    ElMessage.success(data.message)
  } catch (e) {
    ElMessage.error('搜索失败：' + (e.response?.data?.detail || e.message))
  } finally {
    discovering.value = false
  }
}

async function doAddNet() {
  if (!netUrl.value.trim()) {
    ElMessage.warning('请输入摄像头地址')
    return
  }
  try {
    const { data } = await addNetCam(netUrl.value.trim())
    choices.value = data.choices
    selected.value = data.value || selected.value
    ElMessage.success(data.message)
  } catch (e) {
    ElMessage.error('添加失败：' + (e.response?.data?.detail || e.message))
  }
}

async function doStart() {
  if (!selected.value) {
    ElMessage.warning('请先选择摄像头')
    return
  }
  starting.value = true
  try {
    const { data } = await startMonitor(selected.value)
    ElMessage.success(data.message)
    monitoring.value = true
    streamKey.value = Date.now()
    await refreshState()
  } catch (e) {
    ElMessage.error('开启失败：' + (e.response?.data?.detail || e.message))
  } finally {
    starting.value = false
  }
}

async function doStop() {
  try {
    await stopMonitor()
    monitoring.value = false
    ElMessage.success('已停止监控')
    await refreshState()
  } catch (e) {
    ElMessage.error('停止失败：' + (e.response?.data?.detail || e.message))
  }
}

async function doShot() {
  try {
    const { data } = await screenshot()
    ElMessage.success(data.message)
    gallery.value = data.gallery
  } catch (e) {
    ElMessage.error('截屏失败：' + (e.response?.data?.detail || e.message))
  }
}

async function doReport() {
  reporting.value = true
  try {
    const { data } = await getReport()
    reportText.value = data.report
    reportVisible.value = true
  } catch (e) {
    ElMessage.error('报告生成失败：' + (e.response?.data?.detail || e.message))
  } finally {
    reporting.value = false
  }
}

onMounted(() => {
  refreshState()
  refreshGallery()
  // 1 秒轮询状态，5 秒轮询画廊
  timer = setInterval(() => {
    refreshState()
    refreshGallery()
  }, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.source-select {
  width: 220px;
}
.net-input {
  width: 320px;
}
.tip {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}
.main-row {
  margin-top: 16px;
}
.stream-box {
  height: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
  border-radius: 4px;
}
.stream {
  max-width: 100%;
  max-height: 480px;
}
.alert {
  margin-bottom: 12px;
}
.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.ops {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.gallery-card {
  margin-top: 16px;
}
.gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.shot {
  width: 120px;
}
.shot-img {
  width: 120px;
  height: 90px;
  border-radius: 4px;
}
.shot-meta {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
  word-break: break-all;
}
.report {
  font-size: 14px;
  line-height: 1.8;
}
.pre-wrap {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
