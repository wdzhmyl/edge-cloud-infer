import axios from 'axios'

// 开发环境经 Vite 代理转发到 FastAPI（:8000）；生产由 FastAPI 直接伺服
const api = axios.create({ baseURL: '/api', timeout: 120000 })

export const getHealth = () => api.get('/health')

export const inspect = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/inspect', fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export const getCameras = () => api.get('/cameras')

export const addNetCam = (url) => api.post('/cameras/net', { url })

export const startMonitor = (source) => api.post('/monitor/start', { source })

export const stopMonitor = () => api.post('/monitor/stop')

export const getState = () => api.get('/monitor/state')

export const screenshot = () => api.post('/monitor/screenshot')

export const getReport = () => api.get('/monitor/report')

export const getGallery = () => api.get('/monitor/gallery')

// MJPEG 流地址（<img> 标签 src 直接播放）
export const streamUrl = '/api/monitor/stream'

// 截图文件地址
export const shotUrl = (name) => `/api/screenshots/${name}`
