"""
集成测试
测试三个adapter的协同工作
"""
import sys
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.services import kg_adapter, rag_adapter, query_orchestrator

TEST_PERSON = "Paula Cheng"


def test_kg_to_rag_pipeline():
    """测试KG查款号 -> RAG查事件 的流水线"""
    print("\n=== test_kg_to_rag_pipeline ===")
    
    # Step 1: KG查人员款号
    kg_result = kg_adapter.query_styles_by_person(TEST_PERSON)
    style_ids = [s["style_id"] for s in kg_result.get("styles", [])[:3]]
    assert len(style_ids) > 0, f"{TEST_PERSON}应有关联款号"
    print(f"Step 1 KG: {TEST_PERSON} -> {len(style_ids)} 个款号")
    
    # Step 2: RAG查这些款号的事件
    events = rag_adapter.query_email_events(
        style_ids=style_ids,
        query_text="船样",
        top_k=5
    )
    print(f"Step 2 RAG: 船样相关 -> {len(events)} 条事件")
    
    # Step 3: 验证结果
    for e in events:
        assert e.get("style_id") in style_ids, "事件款号应在查询范围内"
    print("✅ KG->RAG 流水线测试通过")


def test_term_enhanced_rag():
    """测试术语增强 -> RAG语义检索"""
    print("\n=== test_term_enhanced_rag ===")
    
    # Step 1: 术语翻译
    term_result = rag_adapter.translate_term("zipper", top_k=1)
    assert term_result["best_match"] is not None, "应找到zipper的翻译"
    chinese_term = term_result["best_match"]["chinese"]
    print(f"Step 1 术语: zipper -> {chinese_term}")
    
    # Step 2: 用中文术语做RAG检索
    events = rag_adapter.query_email_events(
        query_text=chinese_term,
        top_k=3
    )
    print(f"Step 2 RAG: '{chinese_term}' -> {len(events)} 条事件")
    print("✅ 术语增强RAG测试通过")


def test_orchestrator_end_to_end():
    """测试端到端：用户问题 -> 编排器 -> 结果"""
    print("\n=== test_orchestrator_end_to_end ===")
    
    # 场景1: "我这款号进展如何"（歧义消解+总览）
    result = query_orchestrator.execute_query(
        query_text="我这款号进展如何",
        person_name=TEST_PERSON
    )
    assert result["result"] is not None, "应返回结果"
    assert result["result"]["type"] == "kg_overview", "应为总览类型"
    print(f"场景1 '进展如何': {result['routing']['strategy']} -> {result['result']['data']['timeline_summary']['total_events']} 事件")
    
    # 场景2: "船样问题"（语义检索）
    result = query_orchestrator.execute_query(
        query_text="船样问题",
        person_name=TEST_PERSON
    )
    assert result["result"] is not None, "应返回结果"
    print(f"场景2 '船样问题': {result['routing']['strategy']} -> {result['result']['event_count']} 事件")
    
    # 场景3: "哪些款号延期了"（时序查询）
    result = query_orchestrator.execute_query(
        query_text="哪些款号延期了",
        person_name=TEST_PERSON
    )
    assert result["result"] is not None, "应返回结果"
    print(f"场景3 '延期': {result['routing']['strategy']} -> {result['result'].get('total_delayed', 0)} 延期款号")
    
    print("✅ 端到端测试通过")


def test_multi_source_merge():
    """测试多数据源结果合并"""
    print("\n=== test_multi_source_merge ===")
    
    # 联合查询会同时用到KG和RAG
    result = query_orchestrator.execute_hybrid(
        query_text="船样",
        style_ids=["CCSS230021", "CCAW240015"],
        top_k=5
    )
    
    # 验证KG部分
    assert "kg_summary" in result, "应包含KG摘要"
    kg_styles = [s["style_id"] for s in result["kg_summary"]]
    print(f"KG部分: {len(kg_styles)} 个款号 -> {kg_styles}")
    
    # 验证RAG部分
    assert "rag_events" in result, "应包含RAG事件"
    print(f"RAG部分: {result['total_events']} 条事件")
    
    # 验证按款号分组
    assert "events_by_style" in result, "应包含按款号分组"
    for style_id, events in result["events_by_style"].items():
        print(f"   {style_id}: {len(events)} 条")
    
    print("✅ 多数据源合并测试通过")


def test_style_ambiguity_clarification():
    """测试款号歧义需要澄清的场景"""
    print("\n=== test_style_ambiguity_clarification ===")
    
    # 用户有多个款号，需要澄清
    ambiguity = query_orchestrator.resolve_style_ambiguity(
        person_name=TEST_PERSON,
        max_suggestions=5
    )
    
    if ambiguity["needs_clarification"]:
        print(f"⚠️ 需要澄清: {ambiguity['style_count']} 个候选款号")
        for sug in ambiguity["suggestions"][:3]:
            print(f"   - {sug['style_id']}: {sug.get('reason', '')}")
    else:
        print(f"✅ 无需澄清: {ambiguity['style_count']} 个款号")
    
    # 用上下文消除歧义
    result = query_orchestrator.execute_query(
        query_text="我这款号进展如何",
        person_name=TEST_PERSON,
        context_style_ids=["CCSS230021"]  # 明确上下文
    )
    if result["ambiguity"] and result["ambiguity"]["reason"] == "继承对话上下文":
        print(f"✅ 上下文消除歧义: {result['ambiguity']['style_ids']}")


def test_performance():
    """测试基本性能"""
    print("\n=== test_performance ===")
    import time
    
    # 测试各策略执行时间
    test_cases = [
        ("kg_overview", lambda: query_orchestrator.execute_kg_overview("CCSS230021")),
        ("rag_semantic", lambda: query_orchestrator.execute_rag_semantic("船样", top_k=5)),
        ("hybrid", lambda: query_orchestrator.execute_hybrid("船样", ["CCSS230021"], top_k=5)),
        ("kg_temporal", lambda: query_orchestrator.execute_kg_temporal("person_delays", TEST_PERSON)),
        ("kg_relational", lambda: query_orchestrator.execute_kg_relational("collaborators", TEST_PERSON)),
    ]
    
    for name, fn in test_cases:
        start = time.time()
        fn()
        elapsed = (time.time() - start) * 1000
        print(f"   {name}: {elapsed:.0f}ms")
    
    print("✅ 性能测试完成")


def run_all_tests():
    """运行所有集成测试"""
    print("=" * 60)
    print("集成测试开始")
    print("=" * 60)
    
    tests = [
        test_kg_to_rag_pipeline,
        test_term_enhanced_rag,
        test_orchestrator_end_to_end,
        test_multi_source_merge,
        test_style_ambiguity_clarification,
        test_performance,
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
