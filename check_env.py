"""
检查当前环境是否OK
"""

import os
import sys
import telnetlib

import pymysql
import redis
import pathlib
import re


def check_env():
    # 检查 Python 版本
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    print(f"当前Python版本：{version}")
    allow_version = ["3.8", "3.9", "3.10", "3.11"]
    if version not in allow_version:
        print(f"当前Python不在支持的列表中：{allow_version}")
        return

    # 检查 环境变量是否设置正确
    try:
        from chanlun import cl_interface
    except:
        print("无法导入 chanlun 模块，环境变量未设置或设置错误")
        print(f"当前的环境变量如下：{sys.path}")
        print(f"需要当 PYTHONPATH 环境变量设置为 {os.getcwd()}\src 目录")
        return

    # 检查 环境变量是否设置正确
    try:
        from chanlun import config
    except:
        print(
            "无法导入 config , 请在 src/chanlun 目录， 复制 config.py.demo 文件粘贴为 config.py"
        )
        return

    # 检查代理是否设置
    if config.PROXY_HOST != "":
        try:
            telnetlib.Telnet(config.PROXY_HOST, config.PROXY_PORT)
        except:
            print("当前设置的 VPN 代理不可用，如不使用数字货币行情，可忽略")

    # 检查 Redis
    try:
        r = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PWD,
            decode_responses=True,
        )
        r.ping()
        print("Redis 连接正常")
    except Exception as e:
        print(f"Redis 连接异常：{e}")

    # 检查 MySQL
    try:
        conn = pymysql.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PWD,
            database=config.DB_DATABASE,
            charset="utf8mb4",
        )
        conn.close()
        print("MySQL 连接正常")
    except Exception as e:
        print(f"MySQL 连接异常：{e}")

    # 检查 TA-Lib 是否安装
    try:
        import talib

        print("TA-Lib 安装正常")
    except Exception as e:
        print(f"TA-Lib 安装异常：{e}")
        print("请参考 https://github.com/TA-Lib/ta-lib-python 进行安装")

    # 检查 数据目录是否存在
    data_path = pathlib.Path("data")
    if data_path.exists() is False:
        print("data 目录不存在，请创建")
    else:
        print("data 目录存在")

    print("环境检查完成")


if __name__ == "__main__":
    check_env()