#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_generate_ai_market_summary函数综合测试脚本

此脚本测试各种边界情况、错误处理和性能表现
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
import json
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ComprehensiveMarketSummaryTester:
    """综合市场摘要测试器"""
    
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
            
        result = {
            'test_name': test_name,
            'status': status,
            'passed': passed,
            'message': message,
            'execution_time': execution_time,
            'timestamp': datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        time_info = f" ({execution_time:.2f}s)" if execution_time > 0 else ""
        print(f"{status} {test_name}: {message}{time_info}")
        
    def create_comprehensive_economic_data(self):
        """创建全面的经济数据"""
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
            },
            {
                'ds_mnemonic': 'CHGDP',
                'indicator_name': '中国国内生产总值',
                'latest_value': 126.0,
                'previous_value': 121.0,
                'previous_year_value': 114.4,
                'yoy_change_pct': 5.2,
                'units': '万亿元',
                'year': 2024
            },
            {
                'ds_mnemonic': 'USPMI',
                'indicator_name': '美国制造业PMI',
                'latest_value': 48.7,
                'previous_value': 49.1,
                'previous_year_value': 50.3,
                'yoy_change_pct': -3.2,
                'units': '指数',
                'year': 2024
            }
        ]
        
    def create_comprehensive_news_data(self):
        """创建全面的新闻数据"""
        return [
            {
                'title': '【🔥最新】美联储宣布维持利率不变，市场反应积极',
                'content': '美联储在最新的议息会议上决定维持联邦基金利率在5.25%-5.50%区间不变，符合市场预期。鲍威尔在新闻发布会上表示，通胀数据显示出积极信号，但仍需要更多时间来确认通胀回落趋势的可持续性。',
                'published_at': datetime.now().isoformat(),
                'source': '美联储官网',
                'importance_score': 0.95
            },
            {
                'title': '【⚡近期】中国12月CPI数据公布，通胀压力温和',
                'content': '国家统计局今日公布12月CPI同比上涨1.7%，环比持平。其中，食品价格同比下降0.8%，非食品价格同比上涨2.4%。核心CPI同比上涨0.6%，通胀压力整体温和。',
                'published_at': (datetime.now()).isoformat(),
                'source': '国家统计局',
                'importance_score': 0.85
            },
            {
                'title': '欧洲央行官员：密切关注通胀数据变化',
                'content': '欧洲央行执委会成员表示，央行将密切关注即将公布的通胀数据，并根据数据变化调整货币政策立场。市场预期欧央行可能在下次会议上讨论降息可能性。',
                'published_at': datetime.now().isoformat(),
                'source': '路透社',
                'importance_score': 0.75
            },
            {
                'title': '地缘政治紧张局势升级，避险情绪升温',
                'content': '中东地区地缘政治紧张局势进一步升级，投资者避险情绪明显升温。黄金价格创下新高，美债收益率下降，美元指数走强。',
                'published_at': datetime.now().isoformat(),
                'source': '彭博社',
                'importance_score': 0.80
            }
        ]
        
    def test_all_node_combinations(self):
        """测试所有节点组合"""
        print("\n=== 测试所有节点组合 ===")
        
        available_nodes = ['macro_analyst', 'economic_data_analyst', 'technical_analyst', 
                          'chanlun_expert', 'financial_analyst', 'geopolitical_analyst']
        
        # 测试单个节点
        for node in available_nodes:
            start_time = time.time()
            try:
                result = _generate_ai_market_summary(
                    economic_data_list=self.create_comprehensive_economic_data(),
                    news_list=self.create_comprehensive_news_data(),
                    current_market='a',
                    current_code='000001',
                    name='平安银行',
                    frequency='d',
                    selected_nodes=[node]
                )
                
                execution_time = time.time() - start_time
                
                if isinstance(result, str) and len(result) > 100 and not result.startswith("错误"):
                    self.log_test_result(f"单节点-{node}", True, "成功生成报告", execution_time)
                else:
                    self.log_test_result(f"单节点-{node}", False, "报告生成异常", execution_time)
                    
            except Exception as e:
                execution_time = time.time() - start_time
                self.log_test_result(f"单节点-{node}", False, f"异常: {str(e)}", execution_time)
        
        # 测试多节点组合
        combinations = [
            ['macro_analyst', 'economic_data_analyst'],
            ['technical_analyst', 'chanlun_expert'],
            ['macro_analyst', 'technical_analyst', 'financial_analyst'],
            available_nodes  # 所有节点
        ]
        
        for i, combo in enumerate(combinations):
            start_time = time.time()
            try:
                result = _generate_ai_market_summary(
                    economic_data_list=self.create_comprehensive_economic_data(),
                    news_list=self.create_comprehensive_news_data(),
                    current_market='a',
                    current_code='000001',
                    name='平安银行',
                    frequency='d',
                    selected_nodes=combo
                )
                
                execution_time = time.time() - start_time
                
                if isinstance(result, str) and len(result) > 200:
                    self.log_test_result(f"多节点组合-{i+1}", True, f"成功生成报告({len(combo)}个节点)", execution_time)
                else:
                    self.log_test_result(f"多节点组合-{i+1}", False, "报告生成异常", execution_time)
                    
            except Exception as e:
                execution_time = time.time() - start_time
                self.log_test_result(f"多节点组合-{i+1}", False, f"异常: {str(e)}", execution_time)
                
    def test_different_markets_and_assets(self):
        """测试不同市场和资产"""
        print("\n=== 测试不同市场和资产 ===")
        
        test_cases = [
            {'market': 'a', 'code': '000001', 'name': '平安银行'},
            {'market': 'a', 'code': '000858', 'name': '五粮液'},
            {'market': 'hk', 'code': '00700', 'name': '腾讯控股'},
            {'market': 'hk', 'code': '01211', 'name': '比亚迪股份'},
            {'market': 'us', 'code': 'AAPL', 'name': '苹果公司'},
            {'market': 'us', 'code': 'TSLA', 'name': '特斯拉'},
            {'market': 'fx', 'code': 'EURUSD', 'name': '欧元美元'},
            {'market': 'fx', 'code': 'USDJPY', 'name': '美元日元'},
            {'market': 'futures', 'code': 'AU2412', 'name': '黄金期货'},
            {'market': 'currency', 'code': 'BTCUSDT', 'name': '比特币'}
        ]
        
        for case in test_cases:
            start_time = time.time()
            try:
                result = _generate_ai_market_summary(
                    economic_data_list=self.create_comprehensive_economic_data(),
                    news_list=self.create_comprehensive_news_data(),
                    current_market=case['market'],
                    current_code=case['code'],
                    name=case['name'],
                    frequency='d',
                    selected_nodes=['macro_analyst', 'economic_data_analyst']
                )
                
                execution_time = time.time() - start_time
                
                if isinstance(result, str) and len(result) > 100:
                    self.log_test_result(f"市场测试-{case['market']}-{case['code']}", True, "成功生成报告", execution_time)
                else:
                    self.log_test_result(f"市场测试-{case['market']}-{case['code']}", False, "报告生成异常", execution_time)
                    
            except Exception as e:
                execution_time = time.time() - start_time
                self.log_test_result(f"市场测试-{case['market']}-{case['code']}", False, f"异常: {str(e)}", execution_time)
                
    def test_edge_cases(self):
        """测试边界情况"""
        print("\n=== 测试边界情况 ===")
        
        edge_cases = [
            {
                'name': '空数据测试',
                'economic_data': [],
                'news_data': [],
                'market': '',
                'code': '',
                'asset_name': '',
                'nodes': []
            },
            {
                'name': '无效节点测试',
                'economic_data': self.create_comprehensive_economic_data(),
                'news_data': self.create_comprehensive_news_data(),
                'market': 'a',
                'code': '000001',
                'asset_name': '平安银行',
                'nodes': ['invalid_node1', 'invalid_node2']
            },
            {
                'name': '异常数据格式测试',
                'economic_data': [{'invalid': 'data', 'format': 'wrong'}],
                'news_data': [{'bad': 'news', 'structure': 'invalid'}],
                'market': 'a',
                'code': '000001',
                'asset_name': '平安银行',
                'nodes': ['macro_analyst']
            },
            {
                'name': '超长字符串测试',
                'economic_data': self.create_comprehensive_economic_data(),
                'news_data': [{
                    'title': 'A' * 1000,  # 超长标题
                    'content': 'B' * 10000,  # 超长内容
                    'published_at': datetime.now().isoformat(),
                    'source': 'C' * 100
                }],
                'market': 'a',
                'code': '000001',
                'asset_name': '平安银行',
                'nodes': ['macro_analyst']
            }
        ]
        
        for case in edge_cases:
            start_time = time.time()
            try:
                result = _generate_ai_market_summary(
                    economic_data_list=case['economic_data'],
                    news_list=case['news_data'],
                    current_market=case['market'],
                    current_code=case['code'],
                    name=case['asset_name'],
                    frequency='d',
                    selected_nodes=case['nodes']
                )
                
                execution_time = time.time() - start_time
                
                # 对于边界情况，我们期望函数能够优雅地处理而不是崩溃
                if isinstance(result, str):
                    self.log_test_result(f"边界测试-{case['name']}", True, "成功处理边界情况", execution_time)
                else:
                    self.log_test_result(f"边界测试-{case['name']}", False, "返回类型异常", execution_time)
                    
            except Exception as e:
                execution_time = time.time() - start_time
                self.log_test_result(f"边界测试-{case['name']}", False, f"异常: {str(e)}", execution_time)
                
    def test_performance_under_load(self):
        """测试负载下的性能"""
        print("\n=== 测试负载下的性能 ===")
        
        # 创建大量数据
        large_economic_data = self.create_comprehensive_economic_data() * 10  # 40条经济数据
        large_news_data = self.create_comprehensive_news_data() * 25  # 100条新闻
        
        start_time = time.time()
        try:
            result = _generate_ai_market_summary(
                economic_data_list=large_economic_data,
                news_list=large_news_data,
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['macro_analyst', 'economic_data_analyst', 'technical_analyst']
            )
            
            execution_time = time.time() - start_time
            
            if isinstance(result, str) and len(result) > 500:
                if execution_time < 120:  # 期望在2分钟内完成
                    self.log_test_result("大数据量性能测试", True, f"成功处理大量数据", execution_time)
                else:
                    self.log_test_result("大数据量性能测试", False, f"执行时间过长", execution_time)
            else:
                self.log_test_result("大数据量性能测试", False, "处理大量数据失败", execution_time)
                
        except Exception as e:
            execution_time = time.time() - start_time
            self.log_test_result("大数据量性能测试", False, f"异常: {str(e)}", execution_time)
            
    def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始运行_generate_ai_market_summary函数综合测试套件")
        print("=" * 80)
        
        # 运行各项测试
        self.test_all_node_combinations()
        self.test_different_markets_and_assets()
        self.test_edge_cases()
        self.test_performance_under_load()
        
        # 输出测试总结
        self.print_test_summary()
        
    def print_test_summary(self):
        """打印测试总结"""
        print("\n" + "=" * 80)
        print("📊 综合测试总结")
        print("=" * 80)
        
        print(f"总测试数: {self.total_tests}")
        print(f"通过测试: {self.passed_tests}")
        print(f"失败测试: {self.total_tests - self.passed_tests}")
        print(f"通过率: {(self.passed_tests / self.total_tests * 100):.1f}%")
        
        # 计算平均执行时间
        execution_times = [r['execution_time'] for r in self.test_results if r['execution_time'] > 0]
        if execution_times:
            avg_time = sum(execution_times) / len(execution_times)
            max_time = max(execution_times)
            min_time = min(execution_times)
            print(f"平均执行时间: {avg_time:.2f}秒")
            print(f"最长执行时间: {max_time:.2f}秒")
            print(f"最短执行时间: {min_time:.2f}秒")
        
        print("\n📋 失败测试详情:")
        failed_tests = [r for r in self.test_results if not r['passed']]
        if failed_tests:
            for test in failed_tests:
                print(f"❌ {test['test_name']}: {test['message']}")
        else:
            print("🎉 没有失败的测试！")
            
        # 保存测试结果到文件
        self.save_test_results()
        
    def save_test_results(self):
        """保存测试结果到文件"""
        try:
            results_file = '/Users/jiming/Documents/trae/chanlun-pro/comprehensive_test_results.json'
            
            test_report = {
                'timestamp': datetime.now().isoformat(),
                'total_tests': self.total_tests,
                'passed_tests': self.passed_tests,
                'pass_rate': self.passed_tests / self.total_tests * 100,
                'execution_times': {
                    'avg': sum(r['execution_time'] for r in self.test_results if r['execution_time'] > 0) / len([r for r in self.test_results if r['execution_time'] > 0]) if any(r['execution_time'] > 0 for r in self.test_results) else 0,
                    'max': max((r['execution_time'] for r in self.test_results if r['execution_time'] > 0), default=0),
                    'min': min((r['execution_time'] for r in self.test_results if r['execution_time'] > 0), default=0)
                },
                'results': self.test_results
            }
            
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(test_report, f, ensure_ascii=False, indent=2)
                
            print(f"\n💾 综合测试结果已保存到: {results_file}")
            
        except Exception as e:
            print(f"❌ 保存测试结果失败: {e}")


def main():
    """主函数"""
    try:
        tester = ComprehensiveMarketSummaryTester()
        tester.run_all_tests()
        
        # 根据测试结果返回适当的退出码
        pass_rate = tester.passed_tests / tester.total_tests * 100
        
        if pass_rate >= 90:
            print("\n🎉 优秀！测试通过率超过90%")
            return 0
        elif pass_rate >= 80:
            print("\n✅ 良好！测试通过率超过80%")
            return 0
        elif pass_rate >= 70:
            print("\n⚠️  一般！测试通过率超过70%，建议进一步优化")
            return 1
        else:
            print(f"\n❌ 测试通过率过低({pass_rate:.1f}%)，需要修复")
            return 1
            
    except Exception as e:
        print(f"❌ 综合测试执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)