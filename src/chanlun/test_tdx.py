import time
from pytdx.exhq import TdxExHq_API

def debug_server():
    ip = "118.89.69.202"
    port = 7727
    client = TdxExHq_API(raise_exception=False, auto_retry=True)
    
    print(f"正在深度探测服务器: {ip}:{port} ...")
    if client.connect(ip, port, time_out=5):
        # 1. 尝试获取市场列表（这一步报错说明大包被拦截）
        mar = client.get_markets()
        print("市场列表获取成功，服务器响应正常。",mar)
        quote = client.get_instrument_quote(10, "USDCNH")
        
        if quote:
            print("✅ 连接成功，已找到 USDCNH 代码，服务器可用！")
            print(quote)
        else:
        
            print("❌ 扫描完毕：该服务器所有市场均未找到 USDCNH 代码。")
        client.disconnect()
    else:
        print("❌ 无法建立连接，请检查安全组 7727 端口。")

if __name__ == "__main__":
    debug_server()