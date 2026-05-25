"""
测试运行器
运行 email_agent/services/ 下所有adapter的测试
"""
import sys
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.test import test_rag_adapter, test_kg_adapter, test_query_orchestrator, test_integration


def run_all():
    """运行所有测试套件"""
    print("\n" + "=" * 70)
    print(" Email Agent Services 测试套件 ".center(70, "="))
    print("=" * 70 + "\n")
    
    modules = [
        ("RAG Adapter", test_rag_adapter),
        ("KG Adapter", test_kg_adapter),
        ("Query Orchestrator", test_query_orchestrator),
        ("Integration", test_integration),
    ]
    
    total_passed = 0
    total_failed = 0
    
    for name, module in modules:
        print(f"\n{'─' * 70}")
        print(f"  运行: {name}")
        print(f"{'─' * 70}")
        try:
            success = module.run_all_tests()
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"❌ {name} 测试套件异常: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1
    
    print("\n" + "=" * 70)
    print(f" 总结果: {total_passed} 个套件通过, {total_failed} 个套件失败")
    print("=" * 70 + "\n")
    
    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
