import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/inspect' },
  {
    path: '/inspect',
    name: 'inspect',
    component: () => import('../views/InspectView.vue'),
    meta: { title: '图片巡检' }
  },
  {
    path: '/monitor',
    name: 'monitor',
    component: () => import('../views/MonitorView.vue'),
    meta: { title: '实时监控' }
  },
  {
    path: '/help',
    name: 'help',
    component: () => import('../views/HelpView.vue'),
    meta: { title: '使用说明' }
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
