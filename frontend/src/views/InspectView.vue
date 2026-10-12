<template>
  <div class="inspect-view">
    <el-card>
      <template #header>
        <span>上传工地图片进行巡检</span>
      </template>

      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept="image/*"
        :on-change="onFileChange"
        class="uploader"
      >
        <div v-if="!previewUrl" class="upload-placeholder">
          <el-icon :size="48"><UploadFilled /></el-icon>
          <div class="upload-text">拖拽图片到此处，或点击选择</div>
        </div>
        <img v-else :src="previewUrl" class="preview" alt="待巡检图片" />
      </el-upload>

      <div class="actions">
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          :disabled="!file"
          @click="runInspect"
        >
          开始巡检
        </el-button>
        <el-button v-if="file" size="large" @click="clearFile">清除</el-button>
      </div>
    </el-card>

    <div v-if="result" class="result">
      <el-row :gutter="16">
        <el-col :span="12">
          <el-card>
            <template #header><span>巡检结果（检测框 / 危险区）</span></template>
            <el-image
              v-if="result.image"
              :src="result.image"
              fit="contain"
              class="result-img"
            />
            <el-empty v-else description="标注图生成失败（已降级为文字报告）" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card>
            <template #header><span>巡检概览</span></template>
            <div class="counts">
              <el-tag
                v-for="(v, k) in result.counts"
                :key="k"
                size="large"
                class="count-tag"
              >
                {{ k }}：{{ v }}
              </el-tag>
              <span v-if="!Object.keys(result.counts).length" class="muted">未检测到目标</span>
            </div>
            <el-alert
              v-if="result.intrusion_count > 0"
              :title="`危险作业区闯入 ${result.intrusion_count} 起：${result.intrusion_labels.join('、')}`"
              type="error"
              show-icon
              :closable="false"
              class="intrusion-alert"
            />
            <div class="summary pre-wrap">{{ result.summary }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="report-card">
        <template #header><span>施工安全巡检报告</span></template>
        <div class="report pre-wrap">{{ result.report }}</div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { inspect } from '../api'

const file = ref(null)
const previewUrl = ref('')
const loading = ref(false)
const result = ref(null)

function onFileChange(uploadFile) {
  file.value = uploadFile.raw
  previewUrl.value = URL.createObjectURL(uploadFile.raw)
  result.value = null
}

function clearFile() {
  file.value = null
  previewUrl.value = ''
  result.value = null
}

async function runInspect() {
  if (!file.value) return
  loading.value = true
  try {
    const { data } = await inspect(file.value)
    result.value = data
  } catch (e) {
    ElMessage.error('巡检失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.uploader :deep(.el-upload) {
  width: 100%;
}
.uploader :deep(.el-upload-dragger) {
  width: 100%;
  padding: 24px;
}
.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #94a3b8;
}
.upload-text {
  margin-top: 8px;
  font-size: 14px;
}
.preview {
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
}
.actions {
  margin-top: 16px;
  text-align: center;
}
.result {
  margin-top: 16px;
}
.result-img {
  width: 100%;
  max-height: 420px;
}
.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.muted {
  color: #94a3b8;
}
.intrusion-alert {
  margin-top: 12px;
}
.summary {
  margin-top: 12px;
  font-size: 14px;
  color: #334155;
}
.report-card {
  margin-top: 16px;
}
.report {
  font-size: 14px;
  line-height: 1.8;
  color: #1f2937;
}
.pre-wrap {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
