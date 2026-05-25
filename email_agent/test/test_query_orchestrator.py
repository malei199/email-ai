"""
Query Orchestrator 测试
测试联合查询编排器的路由、歧义消解和执行
"""
import sys
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.services import query_orchestrator

TEST_PERSON = "Paula Cheng"
TEST_STYLE_ID = "CCSS230021"


def test_resolve_style_ambiguity():
    """测试款号歧义消解"""
    print("\n=== test_resolve_style_ambiguity ===")
    
    # 1. 从人员推断
    result = query_orchestrator.resolve_style_ambiguity(
        person_name=TEST_PERSON,
        max_suggestions=3
    )
    assert result["resolved"] is True, "应能解析出款号"
    assert len(result["style_ids"]) > 0, "应返回款号列表"
    print(f"✅ 从人员推断: {result['style_count']} 个款号")
    print(f"   reason: {result['reason']}")
    print(f"   needs_clarification: {result['needs_clarification']}")
    
    # 2. 继承上下文
    result = query_orchestrator.resolve_style_ambiguity(
        context_style_ids=["CCAW240015"]
    )
    assert result["resolved"] is True, "应继承上下文"
    assert result["style_ids"] == ["CCAW240015"], "应返回上下文款号"
    print(f"✅ 继承上下文: {result['style_ids']}")
    
    # 3. 无法推断
    result = query_orchestrator.resolve_style_ambiguity()
    assert result["resolved"] is False, "无信息时应无法解析"
    print(f"✅ 无法推断: {result['reason']}")


def test_narrow_style_scope():
    """测试款号范围缩小"""
    print("\n=== test_narrow_style_scope ===")
    
    # 假设有多个款号，按"面料"关键词缩小
    style_ids = ["CCSS230021", "CCAW240015", "UNKNOWN"]
    filtered = query_orchestrator.narrow_style_scope(
        style_ids=style_ids,
        query_text="面料问题"
    )
    print(f"✅ 原始: {len(style_ids)} 个 -> 过滤后: {len(filtered)} 个")
    print(f"   结果: {filtered}")


def test_route_query_kg_overview():
    """测试路由：KG款号总览"""
    print("\n=== test_route_query_kg_overview ===")
    routing = query_orchestrator.route_query(
        "我这款号进展如何",
        TEST_PERSON,
        TEST_STYLE_ID,
        None
    )
    assert routing["strategy"] == "kg_overview", f"应为kg_overview, 实际是{routing['strategy']}"
    print(f"✅ 路由: {routing['strategy']} (confidence={routing['confidence']})")
    print(f"   reason: {routing['reason']}")


def test_route_query_rag_semantic():
    """测试路由：RAG语义检索"""
    print("\n=== test_route_query_rag_semantic ===")
    routing = query_orchestrator.route_query(
        "拉链问题怎么处理"
    )
    assert routing["strategy"] == "rag_semantic", f"应为rag_semantic, 实际是{routing['strategy']}"
    print(f"✅ 路由: {routing['strategy']} (confidence={routing['confidence']})")


def test_route_query_hybrid():
    """测试路由：联合查询"""
    print("\n=== test_route_query_hybrid ===")
    routing = query_orchestrator.route_query(
        "我这款号的船样进展",
        TEST_PERSON,
        None,
        ["CCSS230021", "CCAW240015"]
    )
    assert routing["strategy"] == "hybrid", f"应为hybrid, 实际是{routing['strategy']}"
    print(f"✅ 路由: {routing['strategy']} (confidence={routing['confidence']})")


def test_route_query_kg_temporal():
    """测试路由：KG时序/延期"""
    print("\n=== test_route_query_kg_temporal ===")
    routing = query_orchestrator.route_query(
        "哪些款号延期了",
        TEST_PERSON
    )
    assert routing["strategy"] == "kg_temporal", f"应为kg_temporal, 实际是{routing['strategy']}"
    print(f"✅ 路由: {routing['strategy']} (confidence={routing['confidence']})")


def test_route_query_kg_relational():
    """测试路由：KG关系查询"""
    print("\n=== test_route_query_kg_relational ===")
    routing = query_orchestrator.route_query(
        "我和谁合作最多",
        TEST_PERSON
    )
    assert routing["strategy"] == "kg_relational", f"应为kg_relational, 实际是{routing['strategy']}"
    print(f"✅ 路由: {routing['strategy']} (confidence={routing['confidence']})")


def test_execute_kg_overview():
    """测试执行：KG款号总览"""
    print("\n=== test_execute_kg_overview ===")
    result = query_orchestrator.execute_kg_overview(TEST_STYLE_ID)
    assert result["type"] == "kg_overview", "类型应为kg_overview"
    assert "data" in result, "应包含data"
    data = result["data"]
    assert "people" in data, "应包含people"
    assert "timeline_summary" in data, "应包含timeline_summary"
    print(f"✅ 款号{TEST_STYLE_ID}概览:")
    print(f"   事件数: {data['timeline_summary']['total_events']}")
    print(f"   人员数: {len(data['people'])}")
    print(f"   最后更新: {data['last_update']['date']}")


def test_execute_rag_semantic():
    """测试执行：RAG语义检索"""
    print("\n=== test_execute_rag_semantic ===")
    result = query_orchestrator.execute_rag_semantic(
        query_text="船样",
        style_ids=["CCAW240015"],
        top_k=5
    )
    assert result["type"] == "rag_semantic", "类型应为rag_semantic"
    assert "events" in result, "应包含events"
    print(f"✅ 语义检索: {result['event_count']} 条事件")


def test_execute_hybrid():
    """测试执行：联合查询"""
    print("\n=== test_execute_hybrid ===")
    result = query_orchestrator.execute_hybrid(
        query_text="船样进展",
        style_ids=["CCSS230021", "CCAW240015"],
        top_k=5
    )
    assert result["type"] == "hybrid", "类型应为hybrid"
    assert "kg_summary" in result, "应包含kg_summary"
    assert "rag_events" in result, "应包含rag_events"
    print(f"✅ 联合查询:")
    print(f"   KG摘要: {len(result['kg_summary'])} 个款号")
    print(f"   RAG事件: {result['total_events']} 条")


def test_execute_kg_temporal():
    """测试执行：KG时序查询"""
    print("\n=== test_execute_kg_temporal ===")
    result = query_orchestrator.execute_kg_temporal(
        query_type="person_delays",
        person_name=TEST_PERSON,
        top_k=5
    )
    assert result["type"] == "kg_temporal", "类型应为kg_temporal"
    assert result["subtype"] == "person_delays", "子类型应为person_delays"
    print(f"✅ 时序查询:")
    print(f"   延期款号: {result['total_delayed']} / {result['total_styles']}")


def test_execute_kg_relational():
    """测试执行：KG关系查询"""
    print("\n=== test_execute_kg_relational ===")
    result = query_orchestrator.execute_kg_relational(
        query_type="collaborators",
        person_name=TEST_PERSON,
        top_k=5
    )
    assert result["type"] == "kg_relational", "类型应为kg_relational"
    assert result["subtype"] == "collaborators", "子类型应为collaborators"
    print(f"✅ 关系查询:")
    print(f"   协作对象: {result['total_unique']} 人")
    for c in result.get("collaborators", [])[:3]:
        print(f"   - {c['name']}: {c['event_count']} events")


def test_execute_query_full_flow():
    """测试完整流程：自动路由+执行"""
    print("\n=== test_execute_query_full_flow ===")
    
    test_cases = [
        ("我这款号进展如何", TEST_PERSON, TEST_STYLE_ID, None, "kg_overview"),
        ("拉链问题怎么处理", None, None, None, "rag_semantic"),
        ("哪些款号延期了", TEST_PERSON, None, None, "kg_temporal"),
        ("我和谁合作最多", TEST_PERSON, None, None, "kg_relational"),
    ]
    
    for query_text, person, style_id, style_ids, expected_strategy in test_cases:
        result = query_orchestrator.execute_query(
            query_text=query_text,
            person_name=person,
            style_id=style_id,
            style_ids=style_ids
        )
        actual = result["routing"]["strategy"]
        assert actual == expected_strategy, f"'{query_text}' 期望{expected_strategy}, 实际{actual}"
        print(f"✅ '{query_text}' -> {actual}")
        print(f"   数据源: {result['metadata']['data_sources']}")
        print(f"   耗时: {result['metadata']['execution_time_ms']}ms")


def test_execute_query_with_ambiguity():
    """测试完整流程：带歧义消解"""
    print("\n=== test_execute_query_with_ambiguity ===")
    result = query_orchestrator.execute_query(
        query_text="我这款号进展如何",
        person_name=TEST_PERSON
        # 不提供style_id，触发歧义消解
    )
    print(f"✅ 歧义消解:")
    if result["ambiguity"]:
        print(f"   已解析: {result['ambiguity']['style_count']} 个款号")
        print(f"   需要澄清: {result['ambiguity']['needs_clarification']}")
    print(f"   最终策略: {result['routing']['strategy']}")
    print(f"   结果类型: {result['result']['type']}")


def run_all_tests():
    """运行所有Query Orchestrator测试"""
    print("=" * 60)
    print("Query Orchestrator 测试开始")
    print("=" * 60)
    
    tests = [
        test_resolve_style_ambiguity,
        test_narrow_style_scope,
        test_route_query_kg_overview,
        test_route_query_rag_semantic,
        test_route_query_hybrid,
        test_route_query_kg_temporal,
        test_route_query_kg_relational,
        test_execute_kg_overview,
        test_execute_rag_semantic,
        test_execute_hybrid,
        test_execute_kg_temporal,
        test_execute_kg_relational,
        test_execute_query_full_flow,
        test_execute_query_with_ambiguity,
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
