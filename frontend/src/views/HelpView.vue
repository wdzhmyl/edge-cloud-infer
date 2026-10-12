<template>
  <div class="help-view">
    <el-card>
      <template #header><span>使用说明</span></template>

      <h3>实时监控</h3>
      <ol>
        <li>点击「搜索摄像头」自动发现本机摄像头；</li>
        <li>
          手机摄像头：安装 IP 摄像头 App（如 IP Webcam / DroidCam），将地址（如
          <code>http://手机IP:8080/video</code> 或 <code>rtsp://...</code>）粘贴到输入框并点击「添加」；
        </li>
        <li>在下拉框选择摄像头，点击「开启监控」开始逐帧检测；</li>
        <li>检测到危险作业区闯入时自动截屏存证（3 秒防抖），也可随时点击「主动截屏」；</li>
        <li>点击「生成云端研判报告」获取当前画面的施工安全分析。</li>
      </ol>

      <h3>图片巡检</h3>
      <p>上传一张工地现场图片，点击「开始巡检」，系统将输出带检测框的标注图和施工安全巡检报告。</p>

      <h3>危险作业区规则</h3>
      <p>
        画面右侧默认圈定一块危险作业区，作业人员或工程车辆进入该区域即被标记为闯入违规。
        区域可在 <code>config/settings.py</code> 的 <code>DANGER_ZONE</code> 中调整，或设
        <code>ENABLE_DANGER_ZONE=False</code> 关闭。
      </p>

      <h3>云端大模型配置</h3>
      <p>
        将 <code>.env.example</code> 复制为 <code>.env</code>，填入
        <code>LLM_BASE_URL</code>、<code>LLM_API_KEY</code>、<code>LLM_MODEL</code>
        后重启后端即可启用云端智能研判，无需改动代码。未配置时自动使用本地兜底报告。
      </p>

      <h3>识别能力</h3>
      <p>
        边缘端可识别：作业人员、非机动车、摩托车、通勤车辆、通勤班车、工程运输车、现场信号灯、消防栓、警示标识等，
        并对危险作业区闯入做实时规则化预警。
      </p>

      <h3>架构说明（v2.0 前后端分离）</h3>
      <ul>
        <li>后端：<code>interfaces/api.py</code>（FastAPI，端口 8000），接口前缀 <code>/api</code>，文档见 <code>/docs</code>；</li>
        <li>前端：<code>frontend/</code>（Vue3 + Vite，端口 5173），开发时经 Vite 代理访问后端；</li>
        <li>核心逻辑：<code>pipeline/collab.py</code> 与 <code>core/</code> 未被改动，旧版 Gradio 网页（<code>interfaces/web.py</code>）仍可独立运行。</li>
      </ul>
    </el-card>
  </div>
</template>

<script setup>
</script>

<style scoped>
.help-view {
  line-height: 1.8;
}
h3 {
  color: #1f2937;
  margin: 16px 0 8px;
}
code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
</style>
