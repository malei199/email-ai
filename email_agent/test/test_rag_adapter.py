"""
RAG Adapter 测试
测试术语RAG和邮件事件RAG的查询接口
"""
import sys
import os
from pathlib import Path

# 设置环境变量（必须在导入adapter之前）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.services import rag_adapter


def test_term_rag_basic():
    """测试术语RAG基础查询"""
    print("\n=== test_term_rag_basic ===")
    terms = rag_adapter.query_terms("invisible zipper", top_k=3)
    assert len(terms) > 0, "术语查询应返回结果"
    assert "chinese" in terms[0], "结果应包含chinese字段"
    assert "english" in terms[0], "结果应包含english字段"
    print(f"✅ 查询 invisible zipper: {len(terms)} 条结果")
    for t in terms:
        print(f"   - {t['chinese']} / {t['english']} (score={t['score']:.3f})")


def test_term_rag_chinese():
    """测试术语RAG中文查询"""
    print("\n=== test_term_rag_chinese ===")
    terms = rag_adapter.query_terms("隐形拉链", top_k=3)
    assert len(terms) > 0, "中文术语查询应返回结果"
    print(f"✅ 查询 隐形拉链: {len(terms)} 条结果")
    for t in terms:
        print(f"   - {t['chinese']} / {t['english']}")


def test_translate_term():
    """测试术语翻译"""
    print("\n=== test_translate_term ===")
    result = rag_adapter.translate_term("隐形拉链", top_k=2)
    assert result["best_match"] is not None, "应找到最佳匹配"
    assert "chinese" in result["best_match"], "best_match应包含chinese"
    assert "english" in result["best_match"], "best_match应包含english"
    print(f"✅ 隐形拉链 -> {result['best_match']['english']}")


def test_enhance_query():
    """测试查询增强"""
    print("\n=== test_enhance_query ===")
    enhanced = rag_adapter.enhance_query_with_terms("invisible zipper 问题")
    assert "拉链" in enhanced or "zipper" in enhanced, "增强后应包含术语"
    print(f"✅ 增强前: 'invisible zipper 问题'")
    print(f"   增强后: '{enhanced}'")


def test_email_events_by_style_id():
    """测试按单款号查询事件"""
    print("\n=== test_email_events_by_style_id ===")
    events = rag_adapter.query_email_events(style_id="CCAW240015", top_k=5)
    assert isinstance(events, list), "应返回列表"
    print(f"✅ 款号CCAW240015: {len(events)} 条事件")
    if events:
        e = events[0]
        assert "style_id" in e, "事件应包含style_id"
        assert "category" in e, "事件应包含category"
        print(f"   样例: {e['category']} | {e.get('event_type', 'N/A')} | {e.get('date', 'N/A')}")


def test_email_events_semantic():
    """测试语义检索"""
    print("\n=== test_email_events_semantic ===")
    events = rag_adapter.query_email_events(query_text="船样", top_k=5)
    assert isinstance(events, list), "应返回列表"
    print(f"✅ 语义检索'船样': {len(events)} 条结果")
    if events:
        e = events[0]
        # 验证完整字段
        assert "order_id" in e, "应包含order_id"
        assert "party_from" in e, "应包含party_from"
        assert "party_to" in e, "应包含party_to"
        assert "source_filename" in e, "应包含source_filename"
        assert "source_subject" in e, "应包含source_subject"
        print(f"   样例: style={e['style_id']}, order={e['order_id']}, from={e['party_from']}")
        print(f"   source={e['source_filename']}")


def test_email_events_by_styles():
    """测试多款号范围过滤"""
    print("\n=== test_email_events_by_styles ===")
    events = rag_adapter.query_email_events(
        style_ids=["CCAW240015", "CCAW240016"],
        query_text="船样",
        top_k=5
    )
    assert isinstance(events, list), "应返回列表"
    print(f"✅ 多款号检索: {len(events)} 条结果")
    style_set = set(e.get("style_id") for e in events)
    print(f"   涉及款号: {style_set}")


def test_email_events_by_date():
    """测试日期范围查询"""
    print("\n=== test_email_events_by_date ===")
    events = rag_adapter.query_email_events_by_date(
        style_ids=["CCAW240015", "CCAW240016"],
        days=365 * 2  # 2年
    )
    assert isinstance(events, list), "应返回列表"
    print(f"✅ 最近2年: {len(events)} 条事件")


def test_email_events_by_conditions():
    """测试多条件组合查询"""
    print("\n=== test_email_events_by_conditions ===")
    events = rag_adapter.query_email_events_by_conditions(
        style_ids=["CCAW240015", "CCSS230021"],
        categories=["船样"],
        top_k=5
    )
    assert isinstance(events, list), "应返回列表"
    print(f"✅ 条件筛选(船样阶段): {len(events)} 条事件")
    for e in events:
        assert e.get("category") == "船样", "应只返回船样阶段事件"


def run_all_tests():
    """运行所有RAG Adapter测试"""
    print("=" * 60)
    print("RAG Adapter 测试开始")
    print("=" * 60)
    
    tests = [
        test_term_rag_basic,
        test_term_rag_chinese,
        test_translate_term,
        test_enhance_query,
        test_email_events_by_style_id,
        test_email_events_semantic,
        test_email_events_by_styles,
        test_email_events_by_date,
        test_email_events_by_conditions,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
