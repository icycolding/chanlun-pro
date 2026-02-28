import pathlib
import sys

# 将项目中的 src 目录，添加到 sys.path 中
src_path = pathlib.Path(__file__).parent.parent / ".." / "src"
sys.path.append(str(src_path))
web_server_path = pathlib.Path(__file__).parent
sys.path.append(str(web_server_path))


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

import logging
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.wsgi import WSGIContainer

# 禁用Tornado访问日志
logging.getLogger('tornado.access').setLevel(logging.WARNING)

import chanlun.encodefix  # Fix Windows print 乱码问题  # noqa: F401
from chanlun import config

try:
    from cl_app import create_app
except Exception as e:
    print(e)
    traceback.print_exc()

    if is_wpf_launcher is False:
        input("出现异常，按回车键退出")

if __name__ == "__main__":
    try:
        app = create_app()
        # 支持通过参数或环境变量自定义端口
        port = 9901
        nobrowser = False
        try:
            # 优先读取环境变量 WEB_PORT
            import os
            env_port = os.getenv("WEB_PORT")
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

        s = HTTPServer(WSGIContainer(app))
        s.bind(port, config.WEB_HOST)

        print("启动成功")
        s.start(1)

        if not nobrowser:
            webbrowser.open(f"http://127.0.0.1:{port}")
        IOLoop.instance().start()

    except Exception as e:
        print(e)
        traceback.print_exc()

        if is_wpf_launcher is False:
            input("出现异常，按回车键退出")
        if is_wpf_launcher is False:
            input("出现异常，按回车键退出")

