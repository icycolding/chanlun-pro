#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_generate_ai_market_summary函数快速测试脚本

专注于核心功能验证，避免长时间运行
"""

import sys
import os
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/src')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chanlun_chart.settings')

try:
    import django
    django.setup()
except:
    pass

from web.chanlun_chart.cl_app.news_vector_api import _generate_ai_market_summary
import logging
import time
import signal
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("测试超时")

class QuickMarketSummaryTester:
    """快速市场摘要测试器"""
    
    def __init__(self):
        self.test_results = []
        self.total_tests = 0
        self.passed_tests = 0
        
    def log_test_result(self, test_name: str, passed: bool, message: str = "", execution_time: float = 0):
        """记录测试结果"""
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
            
        time_info = f" ({execution_time:.2f}s)" if execution_time > 0 else ""
        print(f"{status} {test_name}: {message}{time_info}")
        
    def create_simple_economic_data(self):
        """创建简单的经济数据"""
        return [
            {
                'ds_mnemonic': 'CHCPI',
                'indicator_name': '中国消费者价格指数',
                'latest_value': 102.5,
                'previous_value': 102.1,
                'previous_year_value': 100.8,
                'yoy_change_pct': 1.7,
                'units': '指数',
                'year': 2024
            },
            {
                'ds_mnemonic': 'USCPI',
                'indicator_name': '美国消费者价格指数',
                'latest_value': 103.2,
                'previous_value': 103.0,
                'previous_year_value': 100.5,
                'yoy_change_pct': 2.7,
                'units': '指数',
                'year': 2024
            }
        ]
        
    def create_simple_news_data(self):
        """创建简单的新闻数据"""
        return [
            {
                'title': '美联储维持利率不变',
                'content': '美联储决定维持联邦基金利率在5.25%-5.50%区间不变，符合市场预期。',
                'published_at': datetime.now().isoformat(),
                'source': '美联储官网',
                'importance_score': 0.95
            },
            {
                'title': '中国12月CPI数据公布',
                'content': '国家统计局公布12月CPI同比上涨1.7%，通胀压力温和。',
                'published_at': datetime.now().isoformat(),
                'source': '国家统计局',
                'importance_score': 0.85
            }
        ]
        
    def test_with_timeout(self, test_name, test_func, timeout_seconds=30):
        """带超时的测试执行"""
        # 设置信号处理器
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        try:
            start_time = time.time()
            result = test_func()
            execution_time = time.time() - start_time
            signal.alarm(0)  # 取消超时
            return result, execution_time
        except TimeoutError:
            signal.alarm(0)
            self.log_test_result(test_name, False, f"测试超时({timeout_seconds}秒)")
            return None, timeout_seconds
        except Exception as e:
            signal.alarm(0)
            execution_time = time.time() - start_time
            self.log_test_result(test_name, False, f"异常: {str(e)}", execution_time)
            return None, execution_time
            
    def test_basic_functionality(self):
        """测试基本功能"""
        print("\n=== 测试基本功能 ===")
        
        def run_basic_test():
            return _generate_ai_market_summary(
                economic_data_list=self.create_simple_economic_data(),
                news_list=self.create_simple_news_data(),
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['macro_analyst', 'economic_data_analyst']
            )
            
        result, execution_time = self.test_with_timeout("基本功能测试", run_basic_test, 30)
        
        if result and isinstance(result, str) and len(result) > 100:
            self.log_test_result("基本功能测试", True, "成功生成报告", execution_time)
        elif result is not None:
            self.log_test_result("基本功能测试", False, "报告生成异常", execution_time)
            
    def test_single_nodes(self):
        """测试单个节点"""
        print("\n=== 测试单个节点 ===")
        
        nodes_to_test = ['macro_analyst', 'economic_data_analyst', 'technical_analyst']
        
        for node in nodes_to_test:
            def run_single_node_test():
                return _generate_ai_market_summary(
                    economic_data_list=self.create_simple_economic_data(),
                    news_list=self.create_simple_news_data(),
                    current_market='a',
                    current_code='000001',
                    name='平安银行',
                    frequency='d',
                    selected_nodes=[node]
                )
                
            result, execution_time = self.test_with_timeout(f"单节点-{node}", run_single_node_test, 25)
            
            if result and isinstance(result, str) and len(result) > 50:
                self.log_test_result(f"单节点-{node}", True, "成功生成报告", execution_time)
            elif result is not None:
                self.log_test_result(f"单节点-{node}", False, "报告生成异常", execution_time)
                
    def test_different_markets(self):
        """测试不同市场"""
        print("\n=== 测试不同市场 ===")
        
        markets_to_test = [
            {'market': 'a', 'code': '000001', 'name': '平安银行'},
            {'market': 'hk', 'code': '00700', 'name': '腾讯控股'},
            {'market': 'us', 'code': 'AAPL', 'name': '苹果公司'}
        ]
        
        for market_info in markets_to_test:
            def run_market_test():
                return _generate_ai_market_summary(
                    economic_data_list=self.create_simple_economic_data(),
                    news_list=self.create_simple_news_data(),
                    current_market=market_info['market'],
                    current_code=market_info['code'],
                    name=market_info['name'],
                    frequency='d',
                    selected_nodes=['macro_analyst']
                )
                
            result, execution_time = self.test_with_timeout(
                f"市场测试-{market_info['market']}", 
                run_market_test, 
                25
            )
            
            if result and isinstance(result, str) and len(result) > 50:
                self.log_test_result(f"市场测试-{market_info['market']}", True, "成功生成报告", execution_time)
            elif result is not None:
                self.log_test_result(f"市场测试-{market_info['market']}", False, "报告生成异常", execution_time)
                
    def test_error_handling(self):
        """测试错误处理"""
        print("\n=== 测试错误处理 ===")
        
        # 测试空数据
        def run_empty_data_test():
            return _generate_ai_market_summary(
                economic_data_list=[],
                news_list=[],
                current_market='',
                current_code='',
                name='',
                frequency='d',
                selected_nodes=[]
            )
            
        result, execution_time = self.test_with_timeout("空数据测试", run_empty_data_test, 20)
        
        if result and isinstance(result, str):
            self.log_test_result("空数据测试", True, "成功处理空数据", execution_time)
        elif result is not None:
            self.log_test_result("空数据测试", False, "空数据处理异常", execution_time)
            
        # 测试无效节点
        def run_invalid_nodes_test():
            return _generate_ai_market_summary(
                economic_data_list=self.create_simple_economic_data(),
                news_list=self.create_simple_news_data(),
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['invalid_node']
            )
            
        result, execution_time = self.test_with_timeout("无效节点测试", run_invalid_nodes_test, 20)
        
        if result and isinstance(result, str):
            self.log_test_result("无效节点测试", True, "成功处理无效节点", execution_time)
        elif result is not None:
            self.log_test_result("无效节点测试", False, "无效节点处理异常", execution_time)
            
    def run_quick_tests(self):
        """运行快速测试"""
        print("🚀 开始运行_generate_ai_market_summary函数快速测试套件")
        print("=" * 60)
        
        # 运行各项测试
        self.test_basic_functionality()
        self.test_single_nodes()
        self.test_different_markets()
        self.test_error_handling()
        
        # 输出测试总结
        self.print_test_summary()
        
    def print_test_summary(self):
        """打印测试总结"""
        print("\n" + "=" * 60)
        print("📊 快速测试总结")
        print("=" * 60)
        
        print(f"总测试数: {self.total_tests}")
        print(f"通过测试: {self.passed_tests}")
        print(f"失败测试: {self.total_tests - self.passed_tests}")
        
        if self.total_tests > 0:
            pass_rate = (self.passed_tests / self.total_tests * 100)
            print(f"通过率: {pass_rate:.1f}%")
            
            if pass_rate >= 80:
                print("\n🎉 测试结果良好！")
                return True
            elif pass_rate >= 60:
                print("\n⚠️  测试结果一般，建议进一步检查")
                return False
            else:
                print("\n❌ 测试结果不佳，需要修复")
                return False
        else:
            print("\n❌ 没有执行任何测试")
            return False


def main():
    """主函数"""
    try:
        tester = QuickMarketSummaryTester()
        tester.run_quick_tests()
        
        # 根据测试结果返回适当的退出码
        success = tester.print_test_summary()
        return 0 if success else 1
            
    except Exception as e:
        print(f"❌ 快速测试执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)