"""
知识图谱适配器
封装 email_kg_pipeline 的查询接口，供Agent服务调用
"""
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# 将KG pipeline加入路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# 延迟导入（避免启动时强依赖）
_kg_engine = None


def _get_kg_engine():
    """懒加载KG查询引擎"""
    global _kg_engine
    if _kg_engine is None:
        try:
            from email_kg_pipeline.src.kg_query import KGQueryEngine
            from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
            from email_agent.config import KG_GRAPH_PATH
            
            if KG_GRAPH_PATH.exists():
                kg = EmailKnowledgeGraph.load(str(KG_GRAPH_PATH))
                _kg_engine = KGQueryEngine(kg)
            else:
                print(f"[WARN] KG图谱文件不存在: {KG_GRAPH_PATH}")
        except Exception as e:
            print(f"[WARN] KG加载失败: {e}")
    return _kg_engine


# ============ 基础查询接口 ============

def query_person_by_email(email: str) -> Optional[dict]:
    """
    通过邮箱查找人员信息
    注意：当前KG Schema中可能没有email字段，需要扩展或做名字映射
    """
    engine = _get_kg_engine()
    if not engine:
        return None
    
    # 临时方案：从organization.json中查找
    try:
        import json
        from email_agent.config import EMAIL_KG_PIPELINE
        org_path = EMAIL_KG_PIPELINE / "data/organization.json"
        if org_path.exists():
            with open(org_path, "r", encoding="utf-8") as f:
                org = json.load(f)
            for user in org.get("users", []):
                if user.get("email") == email:
                    return {"name": user.get("name"), "id": user.get("id")}
    except Exception:
        pass
    
    return None


def query_styles_by_person(person_name: str) -> dict:
    """查询某人员负责的所有款号"""
    engine = _get_kg_engine()
    if not engine:
        return {"styles": []}
    
    try:
        result = engine.get_styles_by_person(person_name)
        return result
    except Exception as e:
        print(f"[WARN] KG查询失败: {e}")
        return {"styles": []}


def query_timeline(style_id: str) -> list:
    """查询某款号的时间线"""
    engine = _get_kg_engine()
    if not engine:
        return []
    
    try:
        result = engine.get_timeline(style_id)
        return result.get("events", [])
    except Exception as e:
        print(f"[WARN] KG时间线查询失败: {e}")
        return []


def query_last_update(style_id: str) -> dict:
    """查询某款号的最后更新时间"""
    engine = _get_kg_engine()
    if not engine:
        return {"last_update": None, "days_since_update": 999}
    
    try:
        result = engine.get_last_update(style_id)
        return result
    except Exception as e:
        print(f"[WARN] KG最后更新查询失败: {e}")
        return {"last_update": None, "days_since_update": 999}


def query_people_by_style(style_id: str) -> dict:
    """查询某款号涉及的所有人员"""
    engine = _get_kg_engine()
    if not engine:
        return {"people": []}
    
    try:
        result = engine.get_people_by_style(style_id)
        return result
    except Exception as e:
        print(f"[WARN] KG人员查询失败: {e}")
        return {"people": []}


# ============ 新增：V2 五类问题所需接口 ============

def query_customers_by_style(style_id: str) -> dict:
    """
    查询某款号关联的所有客户
    
    Returns:
        {
            "style_id": "CCSS230011",
            "customers": [
                {"name": "Heidi Knight", "email": "heidi@..."}
            ],
            "total_customers": 1
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"style_id": style_id, "customers": []}
    
    try:
        result = engine.get_customers_by_style(style_id)
        return result
    except Exception as e:
        print(f"[WARN] KG客户查询失败: {e}")
        return {"style_id": style_id, "customers": []}


def query_collaborators(person_name: str, top_k: int = 10) -> dict:
    """
    查询某人的主要协作对象
    
    Returns:
        {
            "person": "Paula Cheng",
            "collaborators": [
                {"name": "高总", "event_count": 31, "style_count": 13}
            ],
            "total_unique": 35
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"person": person_name, "collaborators": []}
    
    try:
        result = engine.get_collaborators(person_name, top_k=top_k)
        return result
    except Exception as e:
        print(f"[WARN] KG协作对象查询失败: {e}")
        return {"person": person_name, "collaborators": []}


def query_styles_by_factory(factory_name_or_code: str) -> dict:
    """
    查询某工厂处理的所有款号
    
    Returns:
        {
            "factory": "东台鸿丰",
            "styles": [
                {"style_id": "CCSS230021", "order_id": "ORDER-001", "total_delay_days": 5}
            ],
            "total_styles": 15
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"factory": factory_name_or_code, "styles": []}
    
    try:
        result = engine.get_styles_by_factory(factory_name_or_code)
        return result
    except Exception as e:
        print(f"[WARN] KG工厂款号查询失败: {e}")
        return {"factory": factory_name_or_code, "styles": []}


def query_factory_delays(top_k: int = 10) -> dict:
    """
    查询工厂延期统计
    
    Returns:
        {
            "factories": [
                {"name": "东台鸿丰", "total_delay_days": 45, "avg_delay": 3.0}
            ],
            "total_factories": 5
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"factories": []}
    
    try:
        result = engine.get_factory_delays(top_k=top_k)
        return result
    except Exception as e:
        print(f"[WARN] KG工厂延期查询失败: {e}")
        return {"factories": []}


def find_styles_with_conditions(
    categories: List[str] = None,
    min_delay_days: int = None,
    factory_name: str = None,
    person_name: str = None,
    customer_email: str = None
) -> dict:
    """
    多条件筛选款号（图谱优势场景）
    
    Args:
        categories: 必须经历的业务阶段列表
        min_delay_days: 最小延期天数
        factory_name: 工厂名称
        person_name: 参与人员
        customer_email: 客户邮箱
        
    Returns:
        {
            "conditions": {...},
            "styles": [
                {"style_id": "CCSS230021", "matched_categories": [...], "total_delay_days": 15}
            ],
            "total": 10
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"conditions": {}, "styles": [], "total": 0}
    
    try:
        result = engine.find_styles_with_conditions(
            categories=categories,
            min_delay_days=min_delay_days,
            factory_name=factory_name,
            person_name=person_name,
            customer_email=customer_email
        )
        return result
    except Exception as e:
        print(f"[WARN] KG条件筛选查询失败: {e}")
        return {"conditions": {}, "styles": [], "total": 0}


def query_person_styles_with_stats(person_name: str) -> dict:
    """
    查询人员款号完整统计（含 latest_category，用于 V2 款号列表展示）
    
    Returns:
        {
            "person": "Paula Cheng",
            "styles": [
                {
                    "style_id": "CCSS230021",
                    "role": "负责人",
                    "event_count": 9,
                    "last_update": "2023-08-25",
                    "latest_category": "调纸样",
                    "total_delay_days": 5
                }
            ],
            "total_styles": 94,
            "as_primary_owner": 15,
            "as_participant": 79
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"person": person_name, "styles": []}
    
    try:
        result = engine.get_styles_by_person(person_name)
        return result
    except Exception as e:
        print(f"[WARN] KG人员款号统计查询失败: {e}")
        return {"person": person_name, "styles": []}


def get_style_overview(style_id: str) -> dict:
    """
    获取款号综合概览（整合多个KG查询）
    
    Returns:
        {
            "style_id": "CCSS230021",
            "people": [...],
            "customers": [...],
            "timeline": [...],
            "last_update": {...},
            "total_events": 60,
            "total_delay_days": 15
        }
    """
    engine = _get_kg_engine()
    if not engine:
        return {"style_id": style_id, "error": "KG未加载"}
    
    try:
        people = engine.get_people_by_style(style_id)
        customers = engine.get_customers_by_style(style_id)
        timeline = engine.get_timeline(style_id)
        last_update = engine.get_last_update(style_id)
        
        return {
            "style_id": style_id,
            "people": people.get("people", []),
            "primary_owner": people.get("primary_owner"),
            "customers": customers.get("customers", []),
            "timeline": timeline.get("timeline", []),
            "by_category": timeline.get("by_category", {}),
            "total_events": timeline.get("total_events", 0),
            "last_update": last_update.get("last_update"),
            "latest_category": last_update.get("latest_category"),
            "days_since_update": last_update.get("days_since_update"),
        }
    except Exception as e:
        print(f"[WARN] KG款号概览查询失败: {e}")
        return {"style_id": style_id, "error": str(e)}
