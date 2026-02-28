#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_generate_ai_market_summary函数测试脚本

此脚本用于测试修复后的_generate_ai_market_summary函数的各种功能和错误处理机制。
"""

import sys
import os
import json
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
web_path = os.path.join(project_root, 'web', 'chanlun_chart', 'cl_app')
if web_path not in sys.path:
    sys.path.append(web_path)

# 导入测试目标函数
try:
    from news_vector_api import _generate_ai_market_summary, logger
    print("✅ 成功导入_generate_ai_market_summary函数")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)


class MarketSummaryTester:
    """市场摘要生成器测试类"""
    
    def __init__(self):
        self.test_results = []
        self.total_tests = 0
        self.passed_tests = 0
        
    def log_test_result(self, test_name: str, passed: bool, message: str = ""):
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
            'timestamp': datetime.now().isoformat()
        }
        self.test_results.append(result)
        print(f"{status} {test_name}: {message}")
        
    def create_mock_economic_data(self) -> List[Dict]:
        """创建模拟经济数据"""
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
        
    def create_mock_news_data(self) -> List[Dict]:
        """创建模拟新闻数据"""
        return [
            {
                'title': '【🔥最新】美联储宣布维持利率不变',
                'content': '美联储在最新的议息会议上决定维持联邦基金利率在5.25%-5.50%区间不变，符合市场预期。',
                'published_at': datetime.now().isoformat(),
                'source': '财经新闻',
                'importance_score': 0.9
            },
            {
                'title': '【⚡近期】中国12月CPI数据公布',
                'content': '国家统计局公布12月CPI同比上涨1.7%，环比持平，通胀压力温和。',
                'published_at': (datetime.now() - timedelta(hours=2)).isoformat(),
                'source': '官方数据',
                'importance_score': 0.8
            }
        ]
        
    def test_basic_functionality(self):
        """测试基本功能"""
        print("\n=== 测试基本功能 ===")
        
        try:
            economic_data = self.create_mock_economic_data()
            news_data = self.create_mock_news_data()
            
            result = _generate_ai_market_summary(
                economic_data_list=economic_data,
                news_list=news_data,
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['macro_analyst', 'economic_data_analyst']
            )
            
            # 检查结果是否为字符串且不为空
            if isinstance(result, str) and len(result) > 0:
                self.log_test_result("基本功能测试", True, "成功生成报告")
                
                # 检查报告内容是否包含预期的部分
                expected_sections = ['宏观', '经济', '分析']
                found_sections = sum(1 for section in expected_sections if section in result)
                
                if found_sections >= 2:
                    self.log_test_result("报告内容检查", True, f"包含{found_sections}个预期部分")
                else:
                    self.log_test_result("报告内容检查", False, f"只包含{found_sections}个预期部分")
            else:
                self.log_test_result("基本功能测试", False, f"返回结果异常: {type(result)}")
                
        except Exception as e:
            self.log_test_result("基本功能测试", False, f"异常: {str(e)}")
            
    def test_empty_inputs(self):
        """测试空输入处理"""
        print("\n=== 测试空输入处理 ===")
        
        try:
            result = _generate_ai_market_summary(
                economic_data_list=[],
                news_list=[],
                current_market='',
                current_code='',
                name='',
                frequency='d',
                selected_nodes=[]
            )
            
            if isinstance(result, str):
                if "错误" in result or "没有选择" in result:
                    self.log_test_result("空输入处理", True, "正确处理空输入")
                else:
                    self.log_test_result("空输入处理", False, "未正确处理空输入")
            else:
                self.log_test_result("空输入处理", False, "返回类型错误")
                
        except Exception as e:
            self.log_test_result("空输入处理", False, f"异常: {str(e)}")
            
    def test_invalid_nodes(self):
        """测试无效节点处理"""
        print("\n=== 测试无效节点处理 ===")
        
        try:
            economic_data = self.create_mock_economic_data()
            news_data = self.create_mock_news_data()
            
            result = _generate_ai_market_summary(
                economic_data_list=economic_data,
                news_list=news_data,
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['invalid_node', 'another_invalid_node']
            )
            
            if isinstance(result, str) and ("错误" in result or "没有选择" in result or "没有有效" in result):
                self.log_test_result("无效节点处理", True, "正确处理无效节点")
            else:
                self.log_test_result("无效节点处理", False, "未正确处理无效节点")
                
        except Exception as e:
            self.log_test_result("无效节点处理", False, f"异常: {str(e)}")
            
    def test_single_node_selection(self):
        """测试单个节点选择"""
        print("\n=== 测试单个节点选择 ===")
        
        available_nodes = ['macro_analyst', 'economic_data_analyst', 'technical_analyst', 
                          'chanlun_expert', 'financial_analyst', 'geopolitical_analyst']
        
        for node in available_nodes:
            try:
                economic_data = self.create_mock_economic_data()
                news_data = self.create_mock_news_data()
                
                result = _generate_ai_market_summary(
                    economic_data_list=economic_data,
                    news_list=news_data,
                    current_market='a',
                    current_code='000001',
                    name='平安银行',
                    frequency='d',
                    selected_nodes=[node]
                )
                
                if isinstance(result, str) and len(result) > 0 and not result.startswith("错误"):
                    self.log_test_result(f"单节点测试-{node}", True, "成功执行")
                else:
                    self.log_test_result(f"单节点测试-{node}", False, "执行失败")
                    
            except Exception as e:
                self.log_test_result(f"单节点测试-{node}", False, f"异常: {str(e)}")
                
    def test_different_markets(self):
        """测试不同市场"""
        print("\n=== 测试不同市场 ===")
        
        markets = ['a', 'hk', 'us', 'fx']
        
        for market in markets:
            try:
                economic_data = self.create_mock_economic_data()
                news_data = self.create_mock_news_data()
                
                result = _generate_ai_market_summary(
                    economic_data_list=economic_data,
                    news_list=news_data,
                    current_market=market,
                    current_code='TEST001',
                    name='测试标的',
                    frequency='d',
                    selected_nodes=['macro_analyst']
                )
                
                if isinstance(result, str) and len(result) > 0:
                    self.log_test_result(f"市场测试-{market}", True, "成功处理")
                else:
                    self.log_test_result(f"市场测试-{market}", False, "处理失败")
                    
            except Exception as e:
                self.log_test_result(f"市场测试-{market}", False, f"异常: {str(e)}")
                
    def test_error_resilience(self):
        """测试错误恢复能力"""
        print("\n=== 测试错误恢复能力 ===")
        
        # 测试异常数据格式
        try:
            malformed_data = [{'invalid': 'data'}]
            
            result = _generate_ai_market_summary(
                economic_data_list=malformed_data,
                news_list=malformed_data,
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['macro_analyst']
            )
            
            if isinstance(result, str):
                self.log_test_result("异常数据处理", True, "成功处理异常数据")
            else:
                self.log_test_result("异常数据处理", False, "未能处理异常数据")
                
        except Exception as e:
            self.log_test_result("异常数据处理", False, f"异常: {str(e)}")
            
    def run_performance_test(self):
        """运行性能测试"""
        print("\n=== 性能测试 ===")
        
        try:
            start_time = datetime.now()
            
            economic_data = self.create_mock_economic_data()
            news_data = self.create_mock_news_data()
            
            result = _generate_ai_market_summary(
                economic_data_list=economic_data,
                news_list=news_data,
                current_market='a',
                current_code='000001',
                name='平安银行',
                frequency='d',
                selected_nodes=['macro_analyst', 'economic_data_analyst']
            )
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            if duration < 60:  # 期望在60秒内完成
                self.log_test_result("性能测试", True, f"执行时间: {duration:.2f}秒")
            else:
                self.log_test_result("性能测试", False, f"执行时间过长: {duration:.2f}秒")
                
        except Exception as e:
            self.log_test_result("性能测试", False, f"异常: {str(e)}")
            
    def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始运行_generate_ai_market_summary函数测试套件")
        print("=" * 60)
        
        # 运行各项测试
        self.test_basic_functionality()
        self.test_empty_inputs()
        self.test_invalid_nodes()
        self.test_single_node_selection()
        self.test_different_markets()
        self.test_error_resilience()
        self.run_performance_test()
        
        # 输出测试总结
        self.print_test_summary()
        
    def print_test_summary(self):
        """打印测试总结"""
        print("\n" + "=" * 60)
        print("📊 测试总结")
        print("=" * 60)
        
        print(f"总测试数: {self.total_tests}")
        print(f"通过测试: {self.passed_tests}")
        print(f"失败测试: {self.total_tests - self.passed_tests}")
        print(f"通过率: {(self.passed_tests / self.total_tests * 100):.1f}%")
        
        print("\n📋 详细结果:")
        for result in self.test_results:
            print(f"{result['status']} {result['test_name']}: {result['message']}")
            
        # 保存测试结果到文件
        self.save_test_results()
        
    def save_test_results(self):
        """保存测试结果到文件"""
        try:
            results_file = os.path.join(project_root, 'test_results.json')
            
            test_report = {
                'timestamp': datetime.now().isoformat(),
                'total_tests': self.total_tests,
                'passed_tests': self.passed_tests,
                'pass_rate': self.passed_tests / self.total_tests * 100,
                'results': self.test_results
            }
            
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(test_report, f, ensure_ascii=False, indent=2)
                
            print(f"\n💾 测试结果已保存到: {results_file}")
            
        except Exception as e:
            print(f"❌ 保存测试结果失败: {e}")


def main():
    """主函数"""
    try:
        tester = MarketSummaryTester()
        tester.run_all_tests()
        
        # 根据测试结果返回适当的退出码
        if tester.passed_tests == tester.total_tests:
            print("\n🎉 所有测试通过！")
            return 0
        else:
            print(f"\n⚠️  有 {tester.total_tests - tester.passed_tests} 个测试失败")
            return 1
            
    except Exception as e:
        print(f"❌ 测试执行失败: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)