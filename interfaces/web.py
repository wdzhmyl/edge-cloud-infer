"""交互层：Gradio 网页 Demo（演示智慧工地安全巡检 · 端云协同）。

含三个页面：
- 「实时监控」：解耦的摄像头监控——前端可搜索/选择摄像头（本地 / 手机 / 网络 RTSP），
  服务端逐帧边缘检测 + 危险区预警，支持主动截屏与异常自动截屏存证。
- 「图片巡检」：单张图片上传分析（云端/兜底报告）。
- 「使用说明」：简要操作指引。
"""

import os
import sys
import base64
import json
import tempfile
import threading
import time
from collections import Counter

import numpy as np

import cv2
import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from pipeline.collab import analyze_image
from core.edge_infer import infer, check_danger_zone
from core.cloud_reason import generate_report
from utils.visualize import draw_detections
from utils.camera import CameraManager

EXAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
_EXAMPLE_FILES = [
    os.path.join(EXAMPLE_DIR, "bus.jpg"),
    os.path.join(EXAMPLE_DIR, "zidane.jpg"),
]
EXAMPLES = [p for p in _EXAMPLE_FILES if os.path.exists(p)]

ARCH_IMG = os.path.join(EXAMPLE_DIR, "architecture.png")

HEADER = "# 智慧工地安全巡检平台（端云协同）"

USAGE = """## 使用说明

### 实时监控
1. 选「本机摄像头」：点「刷新」列出本机/已连接的摄像头（如手机 USB 摄像头、外接摄像头），在下拉框选择设备后点「开启监控」即可采集（选「默认摄像头」则用系统默认）
2. 手机/外接摄像头若未出现在列表，请确认已连接并被系统识别，再点「刷新」
3. 选「网络摄像头」：安装 IP 摄像头 App（如 IP Webcam / DroidCam），将地址（如 `http://手机IP:8080/video` 或 `rtsp://...`）填入地址框并点「开启监控」
4. 检测到危险作业区闯入时自动截屏存证（3秒防抖），也可随时点击「主动截屏」
5. 点「停止监控」仅释放摄像头，画面区域保留，可再次点「开启监控」重新采集

### 图片巡检
上传一张工地现场图片，点击「开始巡检」，系统将输出带检测框的标注图和施工安全巡检报告。

### 危险作业区规则
画面右侧默认圈定一块危险作业区，作业人员或工程车辆进入该区域即被标记为闯入违规。
区域可在 `config/settings.py` 的 `DANGER_ZONE` 中调整，或设 `ENABLE_DANGER_ZONE=False` 关闭。

### 云端大模型配置
将 `.env.example` 复制为 `.env`，填入移动云 / 九天大模型的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 后重启服务即可启用云端智能研判，无需改动代码。

### 识别能力
边缘端可识别：作业人员、非机动车、摩托车、通勤车辆、通勤班车、工程运输车、现场信号灯、消防栓、警示标识等，并对危险作业区闯入做实时规则化预警。
"""

CSS = """
.gradio-container { max-width: 1280px !important; margin: auto !important; }
.gr-button-primary { font-weight: 600; }
footer { visibility: hidden; }
#header { margin-bottom: 4px; }
#frame_b64, #cam_list_json, #dets_json { display: none !important; }
"""

# 把 Gradio Image 组件工具栏图标的英文 title/aria-label 替换为中文悬浮提示。
# 注意：gr.HTML 用 v-html 渲染，不会执行 <script>，故改为经 demo.load(js=...) 执行。
_TOOLTIP_JS = """
() => {
  if (window.__tooltipInstalled) return;
  window.__tooltipInstalled = true;
  const map = [
    {re: /upload/i, zh: "上传图片"},
    {re: /webcam|camera/i, zh: "使用摄像头拍照"},
    {re: /clipboard|paste/i, zh: "从剪贴板粘贴图片"}
  ];
  function localize() {
    document.querySelectorAll('button[title], button[aria-label], [role="button"][title]').forEach(function(el){
      const text = (el.getAttribute('title') || el.getAttribute('aria-label') || '');
      if (/[\\u4e00-\\u9fa5]/.test(text)) return;
      for (const item of map) {
        if (item.re.test(text)) {
          el.setAttribute('title', item.zh);
          el.setAttribute('aria-label', item.zh);
          break;
        }
      }
    });
  }
  localize();
  const obs = new MutationObserver(localize);
  obs.observe(document.body, {childList: true, subtree: true});
}
"""

# ===== 实时监控：解耦摄像头 + 状态（线程安全）=====
_MONITOR_DIR = tempfile.mkdtemp(prefix="eci_monitor_")
_FRAME_PATH = os.path.join(_MONITOR_DIR, "frame.jpg")
_OUT_PATH = os.path.join(_MONITOR_DIR, "out.jpg")
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

cam_mgr = CameraManager()
_lock = threading.Lock()
_state_rt = {
    "monitoring": False,
    "webcam": False,
    "annotated": None,
    "raw": None,
    "alert": "未开启监控",
    "detections": [],
    "intrusions": [],
}
shot_log = []


def build_summary(detections, intrusions=None):
    if not detections:
        return "未检测到目标。"
    cnt = Counter(d["label_zh"] for d in detections)
    lines = "\n".join(f"- **{k}**：{v} 个" for k, v in cnt.items())
    if intrusions:
        lines += (f"\n\n**危险作业区闯入 {len(intrusions)} 起**（"
                  + "、".join(d["label_zh"] for d in intrusions) + "），请立即核查！")
    return lines


def build_shot_md():
    if not shot_log:
        return "#### 截图记录\n暂无截图"
    lines = ["#### 截图记录"] + [
        f"- [{tag}] {ts} · {note}" for _, tag, ts, note in shot_log[-12:][::-1]
    ]
    return "\n".join(lines)


def start_monitor(net_url, src_mode, cam_select=None):
    """开启监控：本机摄像头 → 浏览器采集推流；网络摄像头 → 按地址打开视频流。
    实际采集由前端 JS(window.__startWebcam)接管；此处仅置位状态标志。"""
    webcam = (src_mode == "本机摄像头")
    with _lock:
        _state_rt["webcam"] = webcam
    if webcam:
        # 浏览器端采集本机摄像头，无需服务器侧 cv2.VideoCapture；仅置位监控标志，
        # 真正的逐帧推理由前端把帧(base64)写入 frame_b64、触发 process_frame 处理。
        _state_rt["monitoring"] = True
        return (
            "已开启本机摄像头监控（浏览器实时采集，边缘端逐帧检测 / 危险区预警）",
            gr.update(), gr.update(),
        )
    # 网络摄像头：直接用地址打开
    url = (net_url or "").strip()
    if not url:
        return ("请先在「网络摄像头地址」里填入 RTSP / HTTP 视频流地址", gr.update(), gr.update())
    ok = cam_mgr.open(url)
    if not ok:
        return (
            f"打开失败：{url}（请确认地址可用；手机请先开 IP 摄像头 App 并填对地址）",
            gr.update(), gr.update(),
        )
    with _lock:
        _state_rt["monitoring"] = True
    return (
        f"已开启网络摄像头监控：{url}",
        gr.update(), gr.update(),
    )


def stop_monitor():
    with _lock:
        _state_rt["monitoring"] = False
        _state_rt["webcam"] = False
        _state_rt["raw"] = None  # 清空当前帧，避免停止后仍能截到旧画面
    cam_mgr.release()
    # 仅清状态与清空右侧画面（回到初始空白态），不隐藏组件，避免组件反复挂载导致卡死。
    return "已停止监控，可重新点击「开启监控」使用摄像头", gr.update(), gr.update(value=None)


def switch_source(mode):
    """按“摄像头来源”切换显示：本机摄像头 → 显示 cam_html/webcam_img/摄像头选择；网络摄像头 → 显示 live_img/网址框。
    切换时重置监控状态并释放摄像头,避免来源残留。"""
    webcam = (mode == "本机摄像头")
    with _lock:
        _state_rt["webcam"] = webcam
        _state_rt["monitoring"] = False
        _state_rt["raw"] = None
    cam_mgr.release()
    return (
        gr.update(visible=not webcam),  # live_img
        gr.update(visible=False),       # webcam_img 已改用原生 video 显示，始终隐藏
        gr.update(visible=webcam),      # cam_html（video+覆盖层）仅本机模式可见
        gr.update(visible=not webcam),  # net_url 仅网络模式可见
        gr.update(visible=webcam),      # cam_select 仅本机模式可见
        gr.update(visible=webcam),      # refresh_cam_btn 仅本机模式可见
    )


def update_cam_choices(devices_json):
    """根据前端 enumerateDevices 返回的 JSON 更新摄像头下拉框选项（label/value 元组，默认值为空串）。"""
    import json
    try:
        devices = json.loads(devices_json or "[]")
    except Exception:
        devices = []
    if not devices:
        return gr.update(choices=[("默认摄像头", "")], value="")
    choices = [("默认摄像头", "")] + [
        (d.get("label", "未命名摄像头"), d.get("value", "")) for d in devices
    ]
    return gr.update(choices=choices, value="")


def save_screenshot(mark=True, auto=False):
    with _lock:
        raw = _state_rt["raw"]
        dets = _state_rt["detections"]
        intr = _state_rt["intrusions"]
        monitoring = _state_rt["monitoring"]
    if raw is None:
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
    p = save_screenshot(mark=True, auto=False)
    if p is None:
        return "画面尚未就绪，请先开启摄像头"
    return f"已主动截屏：{os.path.basename(p)}"


def make_report_rt():
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


# 记录上次 UI 输出，内容不变则不重绘：彻底消除状态行每秒跳动
_last_ui = {"img": None}
# 浏览器摄像头模式下的自动截屏防抖计时（与服务器模式的 last_auto 分开）
_last_auto_w = 0.0


def refresh_ui():
    # 仅网络摄像头模式需要把最新标注帧推到 live_img；本机模式画面由原生 video + 覆盖层呈现，这里跳过。
    with _lock:
        monitoring = _state_rt["monitoring"]
        webcam_mode = _state_rt["webcam"]
        annotated = _state_rt["annotated"]
    if monitoring and annotated is not None and not webcam_mode:
        img_out = annotated if annotated is not _last_ui["img"] else gr.skip()
        _last_ui["img"] = annotated
    else:
        img_out = gr.skip()
    return img_out


def processing_loop():
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
        with _lock:
            _state_rt["annotated"] = annotated
            _state_rt["raw"] = frame.copy()
            _state_rt["detections"] = detections
            _state_rt["intrusions"] = intrusions
        now = time.time()
        if intrusions and now - last_auto > 3:
            save_screenshot(mark=True, auto=True)
            last_auto = now
        time.sleep(0.03)


threading.Thread(target=processing_loop, daemon=True).start()


def process_frame(b64):
    """自定义本机摄像头采集：前端把选定摄像头的帧以 base64(JPEG) 写入 frame_b64，这里解码做边缘检测。
    不再整图回显（主画面用原生 video 顺滑播放），而是把归一化检测框坐标写入 dets_json，由前端画到覆盖层 canvas。
    首帧到达时自动置为监控中（即使未点「开启监控」也能截屏/报告）。"""
    if not b64:
        return gr.skip(), gr.skip()
    try:
        data = base64.b64decode(b64)
        arr = np.frombuffer(data, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return gr.skip(), gr.skip()
    if bgr is None:
        return gr.skip(), gr.skip()
    with _lock:
        first = not _state_rt["monitoring"]
        _state_rt["webcam"] = True
    detections, _ = infer(bgr)
    h, w = bgr.shape[:2]
    intrusions, _ = check_danger_zone(detections, (w, h))
    cv2.imwrite(_FRAME_PATH, bgr)
    draw_detections(_FRAME_PATH, detections, _OUT_PATH)
    annotated = cv2.cvtColor(cv2.imread(_OUT_PATH), cv2.COLOR_BGR2RGB)
    with _lock:
        # 始终保存当前帧与检测结果，使「主动截屏」随时可用（截屏为带框画面）
        _state_rt["raw"] = bgr.copy()
        _state_rt["detections"] = detections
        _state_rt["intrusions"] = intrusions
        _state_rt["annotated"] = annotated
        _state_rt["monitoring"] = True
    # 危险区闯入自动截屏（3 秒防抖）
    if intrusions:
        now = time.time()
        if now - _last_auto_w > 3:
            save_screenshot(mark=True, auto=True)
            _last_auto_w = now
    # 归一化检测框 → dets_json，供前端覆盖层 canvas 绘制（避免整图重刷导致闪烁/加载）
    boxes = []
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        boxes.append([x1 / w, y1 / h, x2 / w, y2 / h, d.get("label_zh", ""), bool(d.get("in_zone"))])
    zone = None
    if settings.ENABLE_DANGER_ZONE:
        zx1, zy1, zx2, zy2 = settings.DANGER_ZONE
        zone = [zx1, zy1, zx2, zy2]
    payload = json.dumps({
        "w": w, "h": h, "zone": zone,
        "zone_label": getattr(settings, "DANGER_ZONE_LABEL", "危险作业区"),
        "dets": boxes,
    })
    status = "已开启本机摄像头监控（浏览器实时采集，边缘端逐帧检测 / 危险区预警）" if first else gr.skip()
    return payload, status


def analyze(image):
    if image is None:
        return None, "请先上传图片，或点击示例图试用。", "等待输入..."
    try:
        out_path, report, detections, intrusions = analyze_image(image)
    except Exception as e:
        from core import fallback_report
        try:
            detections, _ = infer(image)
            intrusions = []
        except Exception:
            detections, intrusions = [], []
        report = fallback_report.build_fallback_report(detections, intrusions=intrusions, note=f"\n\n（推理异常，已回退本地兜底：{e}）")
        return None, report, build_summary(detections, intrusions)
    return out_path, report, build_summary(detections, intrusions)


theme = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="cyan",
    neutral_hue="slate",
)

with gr.Blocks(title="智慧工地安全巡检平台", theme=theme, css=CSS) as demo:
    gr.Markdown(HEADER, elem_id="header")
    with gr.Tabs():
        with gr.Tab("实时监控"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1, min_width=300):
                    src_mode = gr.Radio(
                        choices=["本机摄像头", "网络摄像头"],
                        value="本机摄像头",
                        show_label=False,
                        interactive=True,
                    )
                    with gr.Row():
                        cam_select = gr.Dropdown(
                            label="选择摄像头",
                            choices=["默认摄像头"],
                            value="默认摄像头",
                            visible=True,
                            scale=4,
                        )
                        refresh_cam_btn = gr.Button("刷新", size="sm", scale=1, visible=True)
                    net_url = gr.Textbox(
                        label="网络摄像头地址（手机 / RTSP / HTTP 视频流）",
                        placeholder="如 rtsp://... 或 http://手机IP:8080/video",
                        visible=False,
                    )
                    with gr.Row():
                        start_btn = gr.Button("开启监控", variant="primary", scale=2)
                        stop_btn = gr.Button("停止监控", scale=1)
                    shot_btn = gr.Button("主动截屏", variant="secondary")
                    status_md = gr.Markdown(
                        "本机摄像头：先点「刷新」列出可用设备，选择后点「开启监控」即采集（选「默认摄像头」用系统默认）；"
                        "网络摄像头：填地址后点「开启监控」。"
                    )
                with gr.Column(scale=2, min_width=500):
                    live_img = gr.Image(
                        label="网络摄像头实时画面（边缘端逐帧检测 / 危险区预警）", type="numpy", height=560,
                        visible=False,
                    )
                    # 自定义本机摄像头：固定高度浅色容器，未开启时居中显示"摄像头未开启"；
                    # 播放时视频按原比例居中，cam_overlay 覆盖层精确对齐视频渲染区域画检测框。
                    cam_html = gr.HTML(
                        '<div id="cam_outer" style="position:relative;width:100%;max-width:760px;margin:0 auto;'
                        'height:460px;background:#f5f7fa;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">'
                        '<div id="cam_placeholder" style="position:absolute;inset:0;display:flex;align-items:center;'
                        'justify-content:center;color:#94a3b8;font-size:18px;letter-spacing:2px;">摄像头未开启</div>'
                        '<video id="cam_video" autoplay playsinline muted '
                        'style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);max-width:100%;max-height:100%;background:#f5f7fa;"></video>'
                        '<canvas id="cam_overlay" style="position:absolute;left:0;top:0;pointer-events:none;"></canvas>'
                        '</div>'
                        '<canvas id="cam_canvas" style="display:none;"></canvas>',
                        visible=True,
                    )
                    webcam_img = gr.Image(
                        label="本机摄像头实时检测（边缘端逐帧检测 / 危险区预警）",
                        type="numpy", height=560, interactive=False, visible=False,
                    )
                    # 隐藏传输/绘制框（CSS 隐藏但保持渲染，确保 .change 触发）：
                    # frame_b64=抽帧送后端；cam_list_json=设备列表回传；dets_json=检测框坐标回传画布
                    frame_b64 = gr.Textbox(visible=True, elem_id="frame_b64")
                    cam_list_json = gr.Textbox(visible=True, elem_id="cam_list_json")
                    dets_json = gr.Textbox(visible=True, elem_id="dets_json")
            # 前端 JS：摄像头逻辑全部内联进事件 js 回调（Gradio 的 js= 保证执行）。主画面用原生 video 顺滑播放，
            # 检测框由覆盖层 canvas 绘制：frame_b64.change 的 js 用“上一轮”坐标先画、再回传 b64 给后端，
            # 从而不整图重刷，消除“一直加载/闪烁”。
            _START_WEBCAM_JS = """
            (net_url, src_mode, cam_select) => {
              if (src_mode !== "本机摄像头") return [net_url, src_mode, cam_select];
              function setBox(id,val){var e=document.querySelector('#'+id+' input, #'+id+' textarea');if(e){e.value=val;e.dispatchEvent(new Event('input',{bubbles:true}));}}
              function clearOverlay(){var ov=document.getElementById('cam_overlay'); if(ov&&ov.width){ov.getContext('2d').clearRect(0,0,ov.width,ov.height);}}
              if(!window.__drawBoxes){
                window.__drawBoxes=function(payload){
                  try{
                    var data=JSON.parse(payload||"{}");
                    var dets=data.dets||[], zone=data.zone||null;
                    var canvas=document.getElementById('cam_overlay'), video=document.getElementById('cam_video'), outer=document.getElementById('cam_outer');
                    if(!canvas||!video||!outer||!video.videoWidth) return;
                    var vw=video.videoWidth, vh=video.videoHeight;
                    var cw=outer.clientWidth, ch=outer.clientHeight;
                    var scale=Math.min(cw/vw, ch/vh);
                    var rw=Math.round(vw*scale), rh=Math.round(vh*scale);
                    var ox=Math.round((cw-rw)/2), oy=Math.round((ch-rh)/2);
                    canvas.style.left=ox+'px'; canvas.style.top=oy+'px'; canvas.style.width=rw+'px'; canvas.style.height=rh+'px';
                    if(canvas.width!==vw){canvas.width=vw;canvas.height=vh;}
                    var ctx=canvas.getContext('2d'), W=vw, H=vh;
                    ctx.clearRect(0,0,W,H);
                    var fs=Math.max(12,W/45), lw=Math.max(2,W/240);
                    if(zone){
                      ctx.save(); ctx.strokeStyle="#f59e0b"; ctx.lineWidth=lw; ctx.setLineDash([8,6]);
                      ctx.strokeRect(zone[0]*W,zone[1]*H,(zone[2]-zone[0])*W,(zone[3]-zone[1])*H);
                      ctx.setLineDash([]); ctx.fillStyle="#f59e0b"; ctx.font=fs+"px sans-serif";
                      ctx.fillText(data.zone_label||"危险作业区", zone[0]*W+2, Math.max(fs, zone[1]*H-6));
                      ctx.restore();
                    }
                    dets.forEach(function(d){
                      var x1=d[0]*W,y1=d[1]*H,x2=d[2]*W,y2=d[3]*H, col=d[5]?"#ff3b30":"#16a34a";
                      ctx.strokeStyle=col; ctx.lineWidth=lw; ctx.strokeRect(x1,y1,x2-x1,y2-y1);
                      var label=(d[5]?"⚠闯入 ":"")+d[4];
                      ctx.font=fs+"px sans-serif"; var tw=ctx.measureText(label).width+6;
                      var ly=Math.max(0,y1-(fs+6));
                      ctx.fillStyle=col; ctx.fillRect(x1,ly,tw,fs+6);
                      ctx.fillStyle="#fff"; ctx.fillText(label,x1+3,ly+fs);
                    });
                  }catch(e){}
                };
              }
              if (window.__webcamStream){window.__webcamStream.getTracks().forEach(function(t){t.stop();});window.__webcamStream=null;}
              if (window.__webcamTimer){clearInterval(window.__webcamTimer);window.__webcamTimer=null;}
              clearOverlay();
              var dev=(cam_select&&cam_select!==""&&cam_select!=="默认摄像头")?cam_select:null;
              var constraint=dev?{video:{deviceId:{exact:dev}}}:{video:true};
              function onStream(stream){
                window.__webcamStream=stream; setBox('frame_b64','');
                var ph=document.getElementById('cam_placeholder'); if(ph) ph.style.display='none';
                var video=document.getElementById('cam_video'); if(video){video.srcObject=stream;video.play();}
                window.__webcamTimer=setInterval(function(){
                  var v=document.getElementById('cam_video'); var c=document.getElementById('cam_canvas');
                  if(!v||!v.videoWidth) return;
                  var maxW=640, sc=Math.min(1,maxW/v.videoWidth);
                  c.width=Math.round(v.videoWidth*sc); c.height=Math.round(v.videoHeight*sc);
                  var ctx=c.getContext('2d'); ctx.drawImage(v,0,0,c.width,c.height);
                  setBox('frame_b64', c.toDataURL('image/jpeg',0.6).split(',')[1]);
                },400);
              }
              navigator.mediaDevices.getUserMedia(constraint).then(onStream).catch(function(err){
                if(dev){navigator.mediaDevices.getUserMedia({video:true}).then(onStream).catch(function(e2){console.error("摄像头开启失败:",e2);});}
                else{console.error("摄像头开启失败:",err);}
              });
              return [net_url, src_mode, cam_select];
            }
            """
            _DRAW_JS = """
            (b64) => {
              var el=document.querySelector('#dets_json input, #dets_json textarea');
              if(el && window.__drawBoxes) window.__drawBoxes(el.value);
              return b64;
            }
            """
            _STOP_WEBCAM_JS = """
            () => {
              if(window.__webcamStream){window.__webcamStream.getTracks().forEach(function(t){t.stop();});window.__webcamStream=null;}
              if(window.__webcamTimer){clearInterval(window.__webcamTimer);window.__webcamTimer=null;}
              var video=document.getElementById('cam_video'); if(video) video.srcObject=null;
              var ov=document.getElementById('cam_overlay'); if(ov&&ov.width){ov.getContext('2d').clearRect(0,0,ov.width,ov.height);}
              var ph=document.getElementById('cam_placeholder'); if(ph) ph.style.display='flex';
              var e=document.querySelector('#frame_b64 input, #frame_b64 textarea'); if(e){e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));}
            }
            """
            _SWITCH_WEBCAM_JS = """
            (mode) => {
              if(mode!=="本机摄像头"){
                if(window.__webcamStream){window.__webcamStream.getTracks().forEach(function(t){t.stop();});window.__webcamStream=null;}
                if(window.__webcamTimer){clearInterval(window.__webcamTimer);window.__webcamTimer=null;}
                var video=document.getElementById('cam_video'); if(video) video.srcObject=null;
                var ov=document.getElementById('cam_overlay'); if(ov&&ov.width){ov.getContext('2d').clearRect(0,0,ov.width,ov.height);}
                var ph=document.getElementById('cam_placeholder'); if(ph) ph.style.display='flex';
                var e=document.querySelector('#frame_b64 input, #frame_b64 textarea'); if(e){e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));}
              }
              return mode;
            }
            """
            _REFRESH_CAM_JS = """
            () => {
              (async function(){
                try{await navigator.mediaDevices.getUserMedia({video:true});}catch(e){}
                var devices=await navigator.mediaDevices.enumerateDevices();
                var vds=devices.filter(function(d){return d.kind==='videoinput';}).map(function(d){return {label:d.label||'未命名摄像头',value:d.deviceId};});
                var el=document.querySelector('#cam_list_json input, #cam_list_json textarea');
                if(el){el.value=JSON.stringify(vds);el.dispatchEvent(new Event('input',{bubbles:true}));}
              })();
            }
            """
            start_btn.click(start_monitor, [net_url, src_mode, cam_select], [status_md, live_img, webcam_img], js=_START_WEBCAM_JS)
            stop_btn.click(stop_monitor, None, [status_md, live_img, webcam_img], js=_STOP_WEBCAM_JS)
            shot_btn.click(manual_shot, None, [status_md])
            src_mode.change(switch_source, [src_mode], [live_img, webcam_img, cam_html, net_url, cam_select, refresh_cam_btn], js=_SWITCH_WEBCAM_JS)
            refresh_cam_btn.click(None, None, None, js=_REFRESH_CAM_JS)
            # 帧经 frame_b64 回传后端检测；其 js(_DRAW_JS)先用上一轮坐标画框再回传 b64，输出到 dets_json 供下一轮绘制。
            # show_progress="hidden"：关掉高频事件自带的速度/进度指示，消除状态区“转圈+0.0s”闪烁与高度跳动。
            frame_b64.change(process_frame, frame_b64, [dets_json, status_md], js=_DRAW_JS, show_progress="hidden")
            cam_list_json.change(update_cam_choices, cam_list_json, cam_select)
            if hasattr(gr, "Timer"):
                # 仅网络摄像头模式的实时画面刷新；show_progress="hidden" 避免定时器进度闪烁。
                ui_timer = gr.Timer(1.0)
                ui_timer.tick(refresh_ui, None, [live_img], show_progress="hidden")

        with gr.Tab("图片巡检"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1):
                    img = gr.Image(label="上传工地图片", type="numpy", height=420)
                    with gr.Row():
                        btn = gr.Button("开始巡检", variant="primary", scale=3)
                        clear_btn = gr.ClearButton(img, value="清空", scale=1)
                    if EXAMPLES:
                        gr.Examples(examples=EXAMPLES, inputs=img, label="或一键试用示例")
                with gr.Column(scale=1):
                    out_img = gr.Image(label="巡检结果（检测框 / 危险区）", type="filepath", height=420)
                    gr.Markdown("### 巡检概览")
                    summary = gr.Markdown("等待巡检...")
            gr.Markdown("### 施工安全巡检报告")
            report = gr.Markdown("上传图片并点击「开始巡检」后，将在此生成报告。")
            btn.click(analyze, [img], [out_img, report, summary])

        with gr.Tab("使用说明"):
            if os.path.exists(ARCH_IMG):
                gr.Image(value=ARCH_IMG, label="端云协同施工安全巡检架构", interactive=False, height=420)
            gr.Markdown(USAGE)

    # 页面加载时执行前端 JS：把 Image 组件图标的英文悬浮提示本地化为中文（须经 load 的 js，v-html 不执行 script）
    def _noop():
        return None

    demo.load(_noop, None, None, js=_TOOLTIP_JS)


if __name__ == "__main__":
    try:
        from core.edge_infer import get_model
        get_model()
    except Exception:
        pass

    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("GRADIO_PORT", "7860")),
        share=os.getenv("GRADIO_SHARE", "false").lower() == "true",
    )
