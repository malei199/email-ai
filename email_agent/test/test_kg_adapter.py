"""
KG Adapter 测试
测试知识图谱查询接口
"""
import sys
import os
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.services import kg_adapter

# 测试用常量
TEST_PERSON = "Paula Cheng"
TEST_STYLE_ID = "CCSS230021"
TEST_FACTORY = "东台鸿丰服饰有限公司"


def test_query_styles_by_person():
    """测试查询人员款号"""
    print("\n=== test_query_styles_by_person ===")
    result = kg_adapter.query_styles_by_person(TEST_PERSON)
    assert "styles" in result, "结果应包含styles字段"
    assert isinstance(result["styles"], list), "styles应为列表"
    print(f"✅ {TEST_PERSON}: {result['total_styles']} 个款号")
    print(f"   负责人: {result.get('as_primary_owner', 0)}, 参与者: {result.get('as_participant', 0)}")
    if result["styles"]:
        s = result["styles"][0]
        print(f"   最近款号: {s['style_id']} (role={s.get('role')})")


def test_query_timeline():
    """测试查询款号时间线"""
    print("\n=== test_query_timeline ===")
    events = kg_adapter.query_timeline(TEST_STYLE_ID)
    assert isinstance(events, list), "应返回事件列表"
    print(f"✅ 款号{TEST_STYLE_ID}: {len(events)} 个事件")
    if events:
        e = events[0]
        assert "date" in e, "事件应包含date"
        assert "category" in e, "事件应包含category"
        print(f"   首个: {e['date']} | {e['category']} | {e.get('event_type', 'N/A')}")


def test_query_last_update():
    """测试查询最后更新"""
    print("\n=== test_query_last_update ===")
    result = kg_adapter.query_last_update(TEST_STYLE_ID)
    assert "last_update" in result, "结果应包含last_update"
    print(f"✅ 款号{TEST_STYLE_ID}: 最后更新={result['last_update']}")
    print(f"   距今天数: {result.get('days_since_update')}")


def test_query_people_by_style():
    """测试查询款号人员"""
    print("\n=== test_query_people_by_style ===")
    result = kg_adapter.query_people_by_style(TEST_STYLE_ID)
    assert "people" in result, "结果应包含people"
    print(f"✅ 款号{TEST_STYLE_ID}: {result['total_people']} 人参与")
    if result.get("primary_owner"):
        print(f"   负责人: {result['primary_owner']}")


def test_query_customers_by_style():
    """测试查询款号客户（新增）"""
    print("\n=== test_query_customers_by_style ===")
    result = kg_adapter.query_customers_by_style(TEST_STYLE_ID)
    assert "customers" in result, "结果应包含customers"
    print(f"✅ 款号{TEST_STYLE_ID}: {result['total_customers']} 个客户")
    for c in result.get("customers", [])[:2]:
        print(f"   - {c.get('name', 'N/A')} ({c.get('email', 'N/A')})")


def test_query_collaborators():
    """测试查询协作对象（新增）"""
    print("\n=== test_query_collaborators ===")
    result = kg_adapter.query_collaborators(TEST_PERSON, top_k=5)
    assert "collaborators" in result, "结果应包含collaborators"
    print(f"✅ {TEST_PERSON}: {result['total_unique']} 个协作对象")
    for c in result.get("collaborators", [])[:3]:
        print(f"   - {c['name']}: {c['event_count']} events, {c['style_count']} styles")


def test_query_styles_by_factory():
    """测试查询工厂款号（新增）"""
    print("\n=== test_query_styles_by_factory ===")
    result = kg_adapter.query_styles_by_factory(TEST_FACTORY)
    assert "styles" in result, "结果应包含styles"
    print(f"✅ 工厂{result.get('factory', TEST_FACTORY)}: {result['total_styles']} 个款号")


def test_query_factory_delays():
    """测试工厂延期统计（新增）"""
    print("\n=== test_query_factory_delays ===")
    result = kg_adapter.query_factory_delays(top_k=5)
    assert "factories" in result, "结果应包含factories"
    print(f"✅ 共{result['total_factories']} 个工厂")
    for f in result.get("factories", [])[:3]:
        print(f"   - {f['name']}: total_delay={f['total_delay_days']}, avg={f['avg_delay']}")


def test_find_styles_with_conditions():
    """测试多条件筛选款号（新增）"""
    print("\n=== test_find_styles_with_conditions ===")
    result = kg_adapter.find_styles_with_conditions(
        person_name=TEST_PERSON,
        min_delay_days=1
    )
    assert "styles" in result, "结果应包含styles"
    print(f"✅ 条件筛选: {result['total']} 个款号匹配")
    for s in result.get("styles", [])[:3]:
        print(f"   - {s['style_id']}: delay={s['total_delay_days']}, categories={s.get('matched_categories', [])}")


def test_query_person_styles_with_stats():
    """测试人员款号统计（新增）"""
    print("\n=== test_query_person_styles_with_stats ===")
    result = kg_adapter.query_person_styles_with_stats(TEST_PERSON)
    assert "styles" in result, "结果应包含styles"
    print(f"✅ {TEST_PERSON}: {result['total_styles']} 个款号")
    print(f"   负责人: {result.get('as_primary_owner', 0)}, 参与者: {result.get('as_participant', 0)}")


def test_get_style_overview():
    """测试款号综合概览（新增）"""
    print("\n=== test_get_style_overview ===")
    result = kg_adapter.get_style_overview(TEST_STYLE_ID)
    assert "style_id" in result, "结果应包含style_id"
    assert "people" in result, "结果应包含people"
    assert "timeline" in result, "结果应包含timeline"
    print(f"✅ 款号{TEST_STYLE_ID}概览:")
    print(f"   人员: {len(result['people'])} 人")
    print(f"   客户: {len(result.get('customers', []))} 个")
    print(f"   事件: {result['total_events']} 个")
    print(f"   最后更新: {result.get('last_update')} ({result.get('latest_category')})")


def run_all_tests():
    """运行所有KG Adapter测试"""
    print("=" * 60)
    print("KG Adapter 测试开始")
    print("=" * 60)
    
    tests = [
        test_query_styles_by_person,
        test_query_timeline,
        test_query_last_update,
        test_query_people_by_style,
        test_query_customers_by_style,
        test_query_collaborators,
        test_query_styles_by_factory,
        test_query_factory_delays,
        test_find_styles_with_conditions,
        test_query_person_styles_with_stats,
        test_get_style_overview,
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
