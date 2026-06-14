import pathlib
import sys
import traceback

# 将项目中的 src 目录，添加到 sys.path 中
src_path = pathlib.Path(__file__).parent.parent / ".." / "src"
sys.path.append(str(src_path))
web_server_path = pathlib.Path(__file__).parent
sys.path.append(str(web_server_path))
project_root = pathlib.Path(__file__).resolve().parents[2]

from startup_preflight import build_startup_checks, format_startup_report


is_wpf_launcher = False
try:
    # WPF 启动，每次 print 都 flush，并且将字符编码转为 GBK（避免乱码）
    if "wpf_launcher" in sys.argv:
        is_wpf_launcher = True

        class filter:
            def __init__(self, target):
                self.target = target

            def write(self, s):
                self.target.buffer.write(s.encode("gbk"))
                self.target.flush()

            def flush(self):
                self.target.flush()

            def close(self):
                self.target.close()

        sys.stdin = filter(sys.stdin)
        sys.stdout = filter(sys.stdout)
        sys.stderr = filter(sys.stderr)
except Exception:
    pass


def _pause_exit(message: str, exit_code: int = 1) -> None:
    if is_wpf_launcher is False:
        input(message)
    raise SystemExit(exit_code)


def _load_runtime_components():
    import logging
    import os
    import webbrowser

    from tornado.httpserver import HTTPServer
    from tornado.ioloop import IOLoop
    from tornado.wsgi import WSGIContainer

    import chanlun.encodefix  # noqa: F401
    from chanlun import config
    from cl_app import create_app

    logging.getLogger("tornado.access").setLevel(logging.WARNING)
    return {
        "HTTPServer": HTTPServer,
        "IOLoop": IOLoop,
        "WSGIContainer": WSGIContainer,
        "config": config,
        "create_app": create_app,
        "os": os,
        "webbrowser": webbrowser,
    }


if __name__ == "__main__":
    startup_report = build_startup_checks(project_root)
    print(format_startup_report(startup_report))
    if startup_report["ok"] is False:
        _pause_exit("启动前检查未通过，按回车键退出")

    try:
        runtime = _load_runtime_components()
        app = runtime["create_app"]()

        # 支持通过参数或环境变量自定义端口
        port = 8801
        nobrowser = False
        try:
            env_port = runtime["os"].getenv("WEB_PORT")
            if env_port and env_port.isdigit():
                port = int(env_port)
        except Exception:
            pass

        # 解析命令行参数：例如 `python app.py 9902 nobrowser`
        for arg in sys.argv[1:]:
            if isinstance(arg, str) and arg.isdigit():
                port = int(arg)
            elif arg == "nobrowser":
                nobrowser = True

        s = runtime["HTTPServer"](runtime["WSGIContainer"](app))
        s.bind(port, runtime["config"].WEB_HOST)

        print(f"启动成功，监听地址: http://{runtime['config'].WEB_HOST}:{port}")
        s.start(1)

        if not nobrowser:
            runtime["webbrowser"].open(f"http://127.0.0.1:{port}")
        runtime["IOLoop"].instance().start()
    except Exception as e:
        print(f"启动失败: {e}")
        traceback.print_exc()
        print("排查建议:")
        print("1. 先确认已执行: pip install -r requirements.txt")
        print("2. 确认 src/chanlun/config.py 已从 config.py.demo 复制并按服务器环境配置")
        print("3. 确认授权文件 pyarmor.rkey 已放到 src/pyarmor_runtime_005445/")
        print("4. 如需服务器后台运行，建议使用: python app.py nobrowser")
        _pause_exit("出现异常，按回车键退出")
