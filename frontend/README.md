# 智慧工地安全巡检平台 · 前端（Vue3）

前后端分离架构的前端部分。后端为 `../interfaces/api.py`（FastAPI，端口 8000）。

## 环境要求

- Node.js **18+**（Vite 6 要求）

## 开发模式

```bash
npm install
npm run dev
```

浏览器访问 http://localhost:5173 （Vite 已配置 `/api` 代理到 `http://localhost:8000`）。

## 生产构建

```bash
npm run build
```

生成 `dist/` 后，FastAPI 会自动托管该目录——此时只需运行后端 `uvicorn interfaces.api:app` 一个进程，
访问 http://localhost:8000 即为完整前端。
