#!/usr/bin/env bash
# 重启 Serenity/chanlun web app（端口 9900）。
#
# 用法：
#   bash restart_app.sh          # 重启
#   bash restart_app.sh stop     # 只停
#   bash restart_app.sh status   # 只看状态
#
# 设计要点（都是之前踩过的坑）：
#   - 按「监听端口的 PID」精确杀，绝不用 `pkill -f app.py`
#     （那个模式会匹配到执行 pkill 的 shell 自身，把自己杀掉 → exit 144）。
#   - 用 setsid + </dev/null 完全脱离父 shell，父 shell 退出也不会带走 app
#     （所以不管是终端里跑还是 agent 跑，都不会被回收）。
#   - 等端口真正 UP/释放，而不是 sleep 猜时间。

set -u

APP_DIR="/root/chanlun-pro/web/chanlun_chart"
PY="/root/chanlun/tion/envs/chanlun/bin/python3.10"
PORT="9900"
LOG="${APP_DIR}/app.out"

cd "$APP_DIR" || { echo "❌ 找不到目录 $APP_DIR"; exit 1; }

port_pid() {
    # 只返回监听 $PORT 的进程 PID（可能为空）
    ss -ltnp 2>/dev/null | grep ":${PORT}" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2
}

stop_app() {
    local pid; pid="$(port_pid)"
    if [ -z "$pid" ]; then
        echo "ℹ️  端口 ${PORT} 无进程，无需停止"
        return 0
    fi
    echo "⏹  停止旧进程 PID=$pid ..."
    kill "$pid" 2>/dev/null
    # 最多等 8s 优雅退出
    for _ in $(seq 1 16); do
        ss -ltn 2>/dev/null | grep -q ":${PORT}" || { echo "✅ 已停止"; return 0; }
        sleep 0.5
    done
    echo "⚠️  优雅退出超时，强制 kill -9 $pid"
    kill -9 "$pid" 2>/dev/null
    for _ in $(seq 1 10); do
        ss -ltn 2>/dev/null | grep -q ":${PORT}" || { echo "✅ 已强制停止"; return 0; }
        sleep 0.5
    done
    echo "❌ 端口 ${PORT} 仍被占用，请手动检查"; return 1
}

start_app() {
    echo "▶️  启动 app（日志 → $LOG）..."
    # setsid 新会话 + </dev/null 断开 stdin + 后台，彻底脱离当前 shell
    setsid "$PY" app.py >"$LOG" 2>&1 </dev/null &
    # 等端口 UP（最多 ~40s）
    for _ in $(seq 1 80); do
        if ss -ltn 2>/dev/null | grep -q ":${PORT}"; then
            echo "✅ app 已启动，端口 ${PORT} LISTENING（PID=$(port_pid)）"
            return 0
        fi
        sleep 0.5
    done
    echo "❌ 启动超时，端口 ${PORT} 未监听。最近日志："
    tail -20 "$LOG"
    return 1
}

case "${1:-restart}" in
    stop)   stop_app ;;
    status)
        pid="$(port_pid)"
        if [ -n "$pid" ]; then echo "✅ 运行中 PID=$pid 端口=${PORT}"; else echo "⏹  未运行"; fi
        ;;
    restart|start)
        stop_app && start_app
        ;;
    *)
        echo "用法: bash restart_app.sh [restart|stop|status]"; exit 2 ;;
esac
