import sys
import os
import pprint

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))
sys.path.insert(0, os.path.join(project_root, 'web/chanlun_chart'))

from cl_app.news_vector_api import chanlun_expert_node
from typing import TypedDict, List, Dict, Any

class ReportGenerationState(TypedDict):
    # Initial inputs
    news_list: List[Dict]
    economic_data_list: List[Dict]
    current_market: str
    current_code: str
    name: str
    frequency: str
    
    # Analyst reports
    macro_analysis: str
    economic_analysis: str
    technical_analysis: str
    chanlun_analysis: str
    financial_analysis: str
    geopolitical_analysis: str
    
    # Control flags
    needs_revision: bool
    revision_target_node: str
    revision_count: int
    
    # Final output
    final_report: str

def test_chanlun_node():
    """
    Tests the chanlun_expert_node to ensure it can run and produce analysis.
    """
    # Create a sample state. Using SH.000001 (SSE Composite Index) for the test.
    sample_state: ReportGenerationState = {
        "news_list": [],
        "economic_data_list": [],
        "current_market": "a",
        "current_code": "SH.000001",
        "name": "上证指数",
        "frequency": "d",
        "macro_analysis": "",
        "economic_analysis": "",
        "technical_analysis": "",
        "chanlun_analysis": "",
        "financial_analysis": "",
        "geopolitical_analysis": "",
        "needs_revision": False,
        "revision_target_node": "",
        "revision_count": 0,
        "final_report": "",
    }

    print("--- Testing chanlun_expert_node ---")
    print("Input state:")
    pprint.pprint(sample_state)

    try:
        result = chanlun_expert_node(sample_state)

        print("\nOutput from chanlun_expert_node:")
        pprint.pprint(result)

        # Assertions to validate the output
        assert "chanlun_analysis" in result, "The key 'chanlun_analysis' is missing from the result."
        assert isinstance(result["chanlun_analysis"], str), "The analysis should be a string."
        assert len(result["chanlun_analysis"]) > 0, "The analysis result is empty."
        assert "异常" not in result["chanlun_analysis"], f"The analysis returned an error: {result['chanlun_analysis']}"
        
        print("\n--- Test Passed ---")

    except Exception as e:
        print(f"\n--- Test Failed ---")
        print(f"An exception occurred during the test: {e}")
        raise

if __name__ == "__main__":
    test_chanlun_node()