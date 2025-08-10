import sys
import os

# 将 cl_app 的父目录添加到Python路径中，以便将其作为包导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'web/chanlun_chart')))

from cl_app.news_vector_api import _get_product_info

def test_product_info():
    test_cases = ['EURUSD', 'gbpusd', 'FE.USDJPY', 'AU', 'QS.AUL8', 'CZ.IC2509', 'UNKNOWN']
    
    for case in test_cases:
        info = _get_product_info(case)
        print(f"--- Testing: {case} ---")
        print(info)
        print("\n")

if __name__ == "__main__":
    test_product_info()