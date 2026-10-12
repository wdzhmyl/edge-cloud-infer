"""监控服务：摄像头调度 + 边缘端逐帧检测线程 + 危险区预警 + 截屏存证 + 云端研判。

从原 Gradio 交互层（interfaces/web.py）抽出的**无 UI 服务层**，供 FastAPI 接口调用。
摄像头管理本身在 utils/camera.py，本模块只负责"选哪个源、逐帧跑检测、维护状态"。

对外暴露的能力：
- discover() / add_network() / start() / stop()  摄像头选择与开关
- stream_gen()                                   MJPEG 视频流生成器（给 <img> 标签用）
- get_state() / gallery()                        前端轮询的实时状态与截图记录
- manual_shot() / make_report()                  截屏存证 / 云端研判报告
"""
import os
import tempfile
import threading
import time
from collections import Counter

import cv2

from config import settings
from core.edge_infer import infer, check_danger_zone
from core.cloud_reason import generate_report
from utils.visualize import draw_detections
from utils.camera import CameraManager

# 截图存证目录（与项目根同级，gitignore 已忽略）
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots"
)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

cam_mgr = CameraManager()
_lock = threading.Lock()
_state_rt = {
    "monitoring": False,
    "raw": None,        # 最新原始帧（BGR numpy）
    "annotated": None,  # 最新标注帧（RGB numpy）
    "frame_jpg": None,  # 最新标注帧的 JPEG 字节（MJPEG 流用）
    "detections": [],
    "intrusions": [],
    "alert": "未开启监控",
}
SOURCE_CHOICES = []  # [(value, label)]，如 ("local:0", "本地摄像头 0")
NET_SOURCES = []     # 用户添加的网络/手机摄像头地址
shot_log = []        # [(path, tag, ts, note)]，最新在末尾

_MONITOR_DIR = tempfile.mkdtemp(prefix="eci_monitor_")
_FRAME_PATH = os.path.join(_MONITOR_DIR, "frame.jpg")
_OUT_PATH = os.path.join(_MONITOR_DIR, "out.jpg")


def build_summary(detections, intrusions=None):
    """把推理结果整理成前端展示的概览文本（Markdown）。"""
    if not detections:
        return "未检测到目标。"
    cnt = Counter(d["label_zh"] for d in detections)
    lines = "\n".join(f"- **{k}**：{v} 个" for k, v in cnt.items())
    if intrusions:
        lines += (f"\n\n**危险作业区闯入 {len(intrusions)} 起**（"
                  + "、".join(d["label_zh"] for d in intrusions) + "），请立即核查！")
    return lines


def discover():
    """搜索本地摄像头 + 已添加的网络摄像头，返回 (choices, 默认值)。"""
    idxs = cam_mgr.discover()
    local = [(f"local:{i}", f"本地摄像头 {i}") for i in idxs]
    net = [(f"net:{u}", f"网络摄像头 {u}") for u in NET_SOURCES]
    SOURCE_CHOICES.clear()
    SOURCE_CHOICES.extend(local + net)
    if not SOURCE_CHOICES:
        return [], None
    choices = [{"value": v, "label": l} for v, l in SOURCE_CHOICES]
    return choices, SOURCE_CHOICES[0][0]


def add_network(url):
    """添加网络/手机摄像头地址，返回 (choices, 新选中值, 提示语)。"""
    url = (url or "").strip()
    if not url:
        return None, None, "请输入摄像头地址（如 http://手机IP:8080/video 或 rtsp://...）"
    if url not in NET_SOURCES:
        NET_SOURCES.append(url)
        local = [(v, l) for v, l in SOURCE_CHOICES if v.startswith("local:")]
        net = [(f"net:{u}", f"网络摄像头 {u}") for u in NET_SOURCES]
        SOURCE_CHOICES.clear()
        SOURCE_CHOICES.extend(local + net)
    choices = [{"value": v, "label": l} for v, l in SOURCE_CHOICES]
    return choices, f"net:{url}", f"已添加网络摄像头：{url}"


def start(value):
    """开启监控：按 value（local:N / net:URL）打开视频源并置位监控线程。"""
    if not value:
        return "请先搜索并选择摄像头"
    kind, _, arg = value.partition(":")
    ok = cam_mgr.open(int(arg) if kind == "local" else arg)
    if not ok:
        return f"打开失败：{value}（请确认设备或地址可用，手机需先开启 IP 摄像头 App）"
    with _lock:
        _state_rt["monitoring"] = True
    return f"已开启监控：{value}"


def stop():
    """停止监控并释放摄像头。"""
    with _lock:
        _state_rt["monitoring"] = False
    cam_mgr.release()
    return "已停止监控"


def save_screenshot(mark=True, auto=False):
    """保存当前帧为截图存证；返回文件路径（未开启监控返回 None）。"""
    with _lock:
        raw = _state_rt["raw"]
        dets = _state_rt["detections"]
        intr = _state_rt["intrusions"]
        monitoring = _state_rt["monitoring"]
    if raw is None or not monitoring:
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = "自动" if auto else "主动"
    note = "危险区闯入" if intr else "常规巡检"
    path = os.path.join(SCREENSHOT_DIR, f"{tag}_{ts}.jpg")
    if mark:
        tmp = os.path.join(_MONITOR_DIR, "shot_raw.jpg")
        cv2.imwrite(tmp, raw)
        draw_detections(tmp, dets, path)
    else:
        cv2.imwrite(path, raw)
    shot_log.append((path, tag, ts, note))
    return path


def manual_shot():
    """主动截屏，返回 (提示语, 画廊列表)。"""
    p = save_screenshot(mark=True, auto=False)
    if p is None:
        return "请先开启监控再截屏", gallery()
    return f"已主动截屏：{os.path.basename(p)}", gallery()


def make_report():
    """对当前监控帧生成云端研判报告（失败自动本地兜底）。"""
    with _lock:
        dets = _state_rt["detections"]
        intr = _state_rt["intrusions"]
        monitoring = _state_rt["monitoring"]
    if not monitoring:
        return "请先开启监控"
    try:
        return generate_report(dets, _FRAME_PATH, intrusions=intr)
    except Exception as e:
        from core import fallback_report
        return fallback_report.build_fallback_report(dets, intrusions=intr, note=f"\n\n（报告生成失败，已回退本地兜底：{e}）")


def get_state():
    """前端轮询用：监控状态 + 检测概览 + 闯入计数。"""
    with _lock:
        monitoring = _state_rt["monitoring"]
        alert = _state_rt["alert"]
        dets = _state_rt["detections"]
        intr = _state_rt["intrusions"]
    cnt = Counter(d["label_zh"] for d in dets)
    return {
        "monitoring": monitoring,
        "alert": alert,
        "detections": [
            {"label_zh": d["label_zh"], "conf": d["conf"], "in_zone": bool(d.get("in_zone", False))}
            for d in dets
        ],
        "counts": dict(cnt),
        "intrusion_count": len(intr),
        "intrusion_labels": [d["label_zh"] for d in intr],
        "shot_count": len(shot_log),
    }


def gallery():
    """截图记录（最新在前），供前端画廊展示。"""
    return [
        {"name": os.path.basename(p), "tag": tag, "ts": ts, "note": note}
        for (p, tag, ts, note) in shot_log[::-1]
    ]


def stream_gen():
    """MJPEG 视频流生成器：持续输出最新标注帧，停止监控时结束流。

    开启/关闭有几百毫秒竞态：未开启时最多等待 3 秒再结束，避免前端
    刚点"开启"就建流被立即断开。
    """
    waited = 0.0
    while True:
        with _lock:
            monitoring = _state_rt["monitoring"]
            jpg = _state_rt["frame_jpg"]
        if not monitoring:
            if waited >= 3.0:
                return
            waited += 0.1
            time.sleep(0.1)
            continue
        waited = 0.0
        if jpg is not None:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.05)


def processing_loop():
    """后台线程：监控开启时逐帧读摄像头 → YOLO 检测 → 危险区判定 → 标注 → 更新状态。"""
    last_auto = 0.0
    while True:
        with _lock:
            monitoring = _state_rt["monitoring"]
        if not monitoring:
            time.sleep(0.1)
            continue
        frame = cam_mgr.read()
        if frame is None:
            time.sleep(0.05)
            continue
        detections, _ = infer(frame)
        h, w = frame.shape[:2]
        intrusions, _ = check_danger_zone(detections, (w, h))
        cv2.imwrite(_FRAME_PATH, frame)
        draw_detections(_FRAME_PATH, detections, _OUT_PATH)
        annotated = cv2.cvtColor(cv2.imread(_OUT_PATH), cv2.COLOR_BGR2RGB)
        ok, buf = cv2.imencode(".jpg", annotated)
        alert = build_summary(detections, intrusions)
        with _lock:
            _state_rt["annotated"] = annotated
            _state_rt["raw"] = frame.copy()
            _state_rt["detections"] = detections
            _state_rt["intrusions"] = intrusions
            _state_rt["alert"] = alert
            if ok:
                _state_rt["frame_jpg"] = buf.tobytes()
        now = time.time()
        if intrusions and now - last_auto > 3:
            save_screenshot(mark=True, auto=True)
            last_auto = now
        time.sleep(0.03)


# 启动后台处理线程（守护线程，随进程退出）
threading.Thread(target=processing_loop, daemon=True).start()
