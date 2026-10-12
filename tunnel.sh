#!/usr/bin/env bash
# 隧道守护脚本
# 1) 确保 Gradio 服务在运行（借助 run.sh 的后台模式）
# 2) 通过 SSH 反向隧道把本地 7860 暴露为公网网址（优先 pinggy，免费 60 分钟；
#    不可达时退回 serveo）。无需下载任何二进制。
# 3) 隧道断线自动重连；当前公网网址实时写入 tunnel_url.txt
#
# 用法：
#   ./tunnel.sh          # 前台运行（Ctrl+C 退出）
#   ./tunnel.sh -d       # 后台运行（日志 tunnel.log，网址 tunnel_url.txt）
#
# 说明：本沙箱屏蔽了 PyPI/HuggingFace 导致 Gradio 自带 share 无法生成，
#       故用免下载的 SSH 隧道作为公网访问通道。若 pinggy/serveo 均不可达，
#       请改用 IDE 的端口转发（PORTS）或本地 ssh -L 7860:localhost:7860。

GPORT="${GRADIO_PORT:-7860}"
LOG="$(pwd)/tunnel.log"
URLFILE="$(pwd)/tunnel_url.txt"

cd "$(dirname "$0")"

# ---- 1. 确保 Gradio 服务运行 ----
if ! pgrep -f "interfaces/web.py" >/dev/null 2>&1; then
    echo ">>> Gradio 未运行，启动中..."
    DAEMON=1 ./run.sh -d
    sleep 8
fi

# ---- 2. 隧道循环（断线自动重连）----
echo ">>> 启动公网隧道守护（断线自动重连），端口 $GPORT"

run_tunnel() {
    : > "$URLFILE"   # 仅在启动时清空一次；重连期间保留旧网址，避免空窗
    while true; do
        pkill -f "a.pinggy.io" 2>/dev/null || true
        pkill -f "serveo.net" 2>/dev/null || true
        sleep 1
        # 用 tee 管道保证输出可靠落盘（不依赖 ssh 的 stdout 缓冲）
        ( ssh -p 443 -o StrictHostKeyChecking=no \
              -o UserKnownHostsFile=/dev/null \
              -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
              -T -R0:127.0.0.1:"${GPORT}" a.pinggy.io 2>&1 | tee -a "$LOG" ) &
        SSHPID=$!
        # pinggy 免费版每次重连都会换子域名，故持续把日志里“最新出现”的网址写入
        # tunnel_url.txt，确保文件始终指向当前生效地址，避免你拿到失效旧网址。
        ( while kill -0 "$SSHPID" 2>/dev/null; do
              u=$(grep -oE "https://[a-zA-Z0-9._-]+\.(pinggy-free\.link|pinggy\.net|serveousercontent\.com)" "$LOG" | tail -1)
              if [ -n "$u" ] && [ "$(cat "$URLFILE" 2>/dev/null)" != "$u" ]; then
                  echo "$u" > "$URLFILE"
                  echo "[$(date '+%F %T')] 公网网址: $u"
              fi
              sleep 3
          done ) &
        WATCHER=$!
        # 阻塞直到 ssh 退出（即隧道断开）
        wait "$SSHPID" 2>/dev/null
        kill "$WATCHER" 2>/dev/null
        echo "[$(date '+%F %T')] 隧道断开，3 秒后重连..."
        sleep 3
    done
}

if [ "${1:-}" = "-d" ]; then
    export GPORT LOG URLFILE
    nohup "$0" --run >> "$LOG" 2>&1 &
    echo ">>> 已在后台启动隧道守护, PID=$!, 网址见 $URLFILE"
    exit 0
elif [ "${1:-}" = "--run" ]; then
    run_tunnel
else
    run_tunnel
fi
