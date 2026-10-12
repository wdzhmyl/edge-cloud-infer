"""交互层：FastAPI 后端（前后端分离架构）。

- 本文件提供 REST API + MJPEG 视频流，供 Vue3 前端（frontend/）调用；
- 原 Gradio 网页（interfaces/web.py）保留为旧版演示入口，互不影响；
- 核心逻辑全部复用 pipeline/ 与 core/，本层只做 HTTP 协议适配。

启动：
    uvicorn interfaces.api:app --host 0.0.0.0 --port 8000
接口文档（自动生成）：
    http://localhost:8000/docs
"""
import base64
import os
import tempfile

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from pipeline.collab import analyze_image
from core import monitor_service as ms
from core.edge_infer import infer

app = FastAPI(title="智慧工地安全巡检平台 API", version="2.0.0")

# 前端 Vite 开发服务器（localhost:5173）跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODE = "云端大模型研判（多模态）" if settings.LLM_API_KEY else "本地离线兜底（未配置 API Key）"


@app.get("/api/health")
def health():
    """健康检查：确认服务可用，并告知当前运行模式（云端/兜底）。"""
    return {"status": "ok", "mode": MODE, "model": settings.LLM_MODEL}


@app.post("/api/inspect")
async def inspect(file: UploadFile = File(...)):
    """图片巡检：上传图片 → YOLO 检测 + 危险区判定 → 云端研判报告。

    返回：{report, summary, counts, intrusion_count, intrusion_labels, image(标注图 base64)}
    """
    suffix = os.path.splitext(file.filename or "upload.jpg")[1] or ".jpg"
    in_path = tempfile.mktemp(suffix=suffix)
    with open(in_path, "wb") as f:
        f.write(await file.read())

    try:
        out_path, report, detections, intrusions = analyze_image(in_path)
    except Exception as e:
        # 与旧版 Gradio 一致：推理异常时降级到本地兜底报告
        from core import fallback_report
        try:
            detections, _ = infer(in_path)
            intrusions = []
        except Exception:
            detections, intrusions = [], []
        report = fallback_report.build_fallback_report(
            detections, intrusions=intrusions, note=f"\n\n（推理异常，已回退本地兜底：{e}）"
        )
        out_path = None

    image_b64 = ""
    if out_path and os.path.exists(out_path):
        with open(out_path, "rb") as f:
            image_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

    from collections import Counter
    counts = dict(Counter(d["label_zh"] for d in detections))
    return {
        "report": report,
        "summary": ms.build_summary(detections, intrusions),
        "counts": counts,
        "intrusion_count": len(intrusions),
        "intrusion_labels": [d["label_zh"] for d in intrusions],
        "image": image_b64,
    }


# ===== 实时监控 =====

@app.get("/api/cameras")
def cameras():
    """搜索摄像头：本地设备 + 已添加的网络源，返回下拉选项与默认值。"""
    choices, value = ms.discover()
    if not choices:
        return {"choices": [], "value": None, "message": "未找到可用摄像头"}
    return {"choices": choices, "value": value, "message": f"发现 {len(choices)} 个摄像头"}


class NetCamIn(BaseModel):
    url: str


@app.post("/api/cameras/net")
def add_net_cam(body: NetCamIn):
    """添加网络/手机摄像头（RTSP 或 http 视频流）。"""
    choices, value, message = ms.add_network(body.url)
    return {"choices": choices or [], "value": value, "message": message}


class StartIn(BaseModel):
    source: str


@app.post("/api/monitor/start")
def monitor_start(body: StartIn):
    """开启监控（source 形如 local:0 或 net:http://...）。"""
    return {"message": ms.start(body.source), "monitoring": True}


@app.post("/api/monitor/stop")
def monitor_stop():
    """停止监控。"""
    return {"message": ms.stop(), "monitoring": False}


@app.get("/api/monitor/stream")
def monitor_stream():
    """MJPEG 实时视频流（前端 <img src> 直接播放）。"""
    return StreamingResponse(
        ms.stream_gen(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/monitor/state")
def monitor_state():
    """轮询实时状态：告警文本、检测计数、闯入数、截图数。"""
    return ms.get_state()


@app.post("/api/monitor/screenshot")
def monitor_screenshot():
    """主动截屏存证（标注检测框 + 危险区）。"""
    message, items = ms.manual_shot()
    return {"message": message, "gallery": items}


@app.get("/api/monitor/report")
def monitor_report():
    """对当前监控帧生成云端研判报告。"""
    return {"report": ms.make_report()}


@app.get("/api/monitor/gallery")
def monitor_gallery():
    """截图记录列表（最新在前）。"""
    return {"items": ms.gallery()}


@app.get("/api/screenshots/{name}")
def screenshot_file(name: str):
    """读取截图文件（画廊展示用）。已做路径穿越防护。"""
    safe = os.path.basename(name)
    path = os.path.join(ms.SCREENSHOT_DIR, safe)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"detail": "截图不存在"})
    return FileResponse(path, media_type="image/jpeg")


# ===== 前端构建产物托管（可选）=====
# `cd frontend && npm run build` 生成 dist 后，FastAPI 可直接伺服整个前端，
# 生产环境只需运行 uvicorn 一个进程。
_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
