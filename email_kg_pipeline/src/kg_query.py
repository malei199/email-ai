#!/usr/bin/env python3
"""
邮件知识图谱查询接口
功能：提供高层查询 API，封装底层图遍历逻辑

使用方法:
  from email_kg_pipeline.src.kg_query import KGQueryEngine
  from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
  
  kg = EmailKnowledgeGraph.load('email_kg_pipeline/output/kg_graph.pkl')
  engine = KGQueryEngine(kg)
  
  # 查询某款号涉及的人员
  result = engine.get_people_by_style("CCSS230021")
"""

import json
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple, Optional, Any

try:
    import networkx as nx
except ImportError:
    print("[ERROR] 缺少 networkx 依赖")
    print("请运行: pip install networkx")
    raise SystemExit(1)

from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph


class KGQueryEngine:
    """
    知识图谱查询引擎
    
    封装所有业务查询，提供清晰的 API 接口。
    每个查询方法返回结构化的字典，便于 LLM 生成自然语言回答。
    """
    
    def __init__(self, kg: EmailKnowledgeGraph):
        self.kg = kg
        self.G = kg.G
    
    # ============ 辅助方法 ============
    
    def _get_node(self, node_id: str) -> Optional[Dict]:
        """获取节点数据"""
        if node_id in self.G:
            return dict(self.G.nodes[node_id])
        return None
    
    def _get_neighbors(self, node_id: str, rel_type: str = None, 
                       direction: str = "out") -> List[Tuple[str, str, Dict]]:
        """
        获取邻居节点
        
        Returns:
            List of (neighbor_id, rel_type, edge_data)
        """
        results = []
        if node_id not in self.G:
            return results
        
        if direction in ["out", "both"]:
            for _, target, key, data in self.G.out_edges(node_id, keys=True, data=True):
                if rel_type is None or data.get("rel_type") == rel_type:
                    results.append((target, data.get("rel_type", key), dict(data)))
        
        if direction in ["in", "both"]:
            for source, _, key, data in self.G.in_edges(node_id, keys=True, data=True):
                if rel_type is None or data.get("rel_type") == rel_type:
                    results.append((source, data.get("rel_type", key), dict(data)))
        
        return results
    
    def _get_nodes_by_label(self, label: str) -> List[Tuple[str, Dict]]:
        """获取指定标签的所有节点"""
        return [(n, dict(d)) for n, d in self.G.nodes(data=True) 
                if d.get("label") == label]
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except:
            return None
    
    # ============ 核心查询接口 ============
    
    def get_people_by_style(self, style_id: str, 
                           include_roles: bool = True) -> Dict[str, Any]:
        """
        查询某款号涉及的所有人员
        
        Args:
            style_id: 款号
            include_roles: 是否包含角色信息
            
        Returns:
            {
                "style_id": "CCSS230021",
                "people": [
                    {"name": "Paula Cheng", "role": "负责人", "event_count": 9},
                    {"name": "Alice", "role": "参与者", "event_count": 6},
                    ...
                ],
                "primary_owner": "Paula Cheng",
                "total_people": 10
            }
        """
        style_node = f"Style:{style_id}"
        if style_node not in self.G:
            return {"style_id": style_id, "people": [], "error": "款号不存在"}
        
        people = []
        primary_owner = None
        
        # 通过 INVOLVED_IN 关系查找
        for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "INVOLVED_IN", "in"):
            person_data = self._get_node(neighbor)
            if person_data:
                involvement = edge_data.get("involvement_type", "participant")
                event_count = edge_data.get("event_count", 0)
                
                person_info = {
                    "name": person_data.get("name", ""),
                    "person_id": person_data.get("person_id", ""),
                    "role": involvement,
                    "event_count": event_count,
                }
                
                # 添加组织架构信息（如果有）
                if person_data.get("department"):
                    person_info["department"] = person_data["department"]
                if person_data.get("role"):
                    person_info["org_role"] = person_data["role"]
                
                people.append(person_info)
                
                if involvement == "primary_owner":
                    primary_owner = person_data.get("name", "")
        
        # 通过 RESPONSIBLE_FOR 关系查找（优先级更高）
        for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "RESPONSIBLE_FOR", "in"):
            person_data = self._get_node(neighbor)
            if person_data:
                primary_owner = person_data.get("name", "")
                # 确保在 people 列表中标记为负责人
                for p in people:
                    if p["name"] == person_data.get("name", ""):
                        p["role"] = "负责人"
                        break
                else:
                    people.append({
                        "name": person_data.get("name", ""),
                        "person_id": person_data.get("person_id", ""),
                        "role": "负责人",
                        "event_count": 0,
                    })
        
        # 按 event_count 排序
        people.sort(key=lambda x: x.get("event_count", 0), reverse=True)
        
        # 查询关联客户 (Style --ORDERED_BY--> Customer)
        customers = []
        for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "ORDERED_BY", "out"):
            customer_data = self._get_node(neighbor)
            if customer_data and customer_data.get("label") == "Customer":
                customers.append({
                    "name": customer_data.get("name", ""),
                    "email": customer_data.get("email", ""),
                })
        
        return {
            "style_id": style_id,
            "people": people,
            "primary_owner": primary_owner,
            "total_people": len(people),
            "customers": customers,
            "total_customers": len(customers),
        }
    
    def get_styles_by_person(self, person_name: str) -> Dict[str, Any]:
        """
        查询某人参与的所有款号
        
        Returns:
            {
                "person": "Paula Cheng",
                "styles": [
                    {"style_id": "CCSS230021", "role": "负责人", "event_count": 9, "last_update": "2023-08-25"},
                    ...
                ],
                "total_styles": 94,
                "as_primary_owner": 15,
                "as_participant": 79
            }
        """
        person_node = f"Person:{person_name}"
        if person_node not in self.G:
            return {"person": person_name, "styles": [], "error": "人员不存在"}
        
        styles = []
        as_primary = 0
        as_participant = 0
        
        # 通过 INVOLVED_IN 关系
        for neighbor, rel_type, edge_data in self._get_neighbors(person_node, "INVOLVED_IN"):
            style_data = self._get_node(neighbor)
            if style_data and style_data.get("label") == "Style":
                style_info = {
                    "style_id": style_data.get("style_id", ""),
                    "role": edge_data.get("involvement_type", "participant"),
                    "event_count": edge_data.get("event_count", 0),
                    "last_update": style_data.get("last_update", ""),
                    "total_delay_days": style_data.get("total_delay_days", 0),
                }
                styles.append(style_info)
                
                if edge_data.get("involvement_type") == "primary_owner":
                    as_primary += 1
                else:
                    as_participant += 1
        
        # 通过 RESPONSIBLE_FOR 关系
        for neighbor, rel_type, edge_data in self._get_neighbors(person_node, "RESPONSIBLE_FOR"):
            style_data = self._get_node(neighbor)
            if style_data and style_data.get("label") == "Style":
                style_id = style_data.get("style_id", "")
                # 检查是否已在列表中
                existing = next((s for s in styles if s["style_id"] == style_id), None)
                if existing:
                    existing["role"] = "负责人"
                else:
                    styles.append({
                        "style_id": style_id,
                        "role": "负责人",
                        "event_count": 0,
                        "last_update": style_data.get("last_update", ""),
                        "total_delay_days": style_data.get("total_delay_days", 0),
                    })
                    as_primary += 1
        
        # 按 last_update 降序排序
        styles.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        return {
            "person": person_name,
            "styles": styles,
            "total_styles": len(styles),
            "as_primary_owner": as_primary,
            "as_participant": as_participant,
        }
    
    def get_collaborators(self, person_name: str, top_k: int = 10) -> Dict[str, Any]:
        """
        查询某人的主要协作对象
        
        Returns:
            {
                "person": "Paula Cheng",
                "collaborators": [
                    {"name": "高总", "event_count": 31, "style_count": 13},
                    ...
                ],
                "total_unique": 35
            }
        """
        person_node = f"Person:{person_name}"
        if person_node not in self.G:
            return {"person": person_name, "collaborators": [], "error": "人员不存在"}
        
        collaborators = []
        
        for neighbor, rel_type, edge_data in self._get_neighbors(person_node, "COLLABORATED_WITH"):
            person_data = self._get_node(neighbor)
            if person_data:
                collaborators.append({
                    "name": person_data.get("name", ""),
                    "person_id": person_data.get("person_id", ""),
                    "event_count": edge_data.get("event_count", 0),
                    "style_count": edge_data.get("style_count", 0),
                })
        
        # 按 event_count 排序
        collaborators.sort(key=lambda x: x["event_count"], reverse=True)
        
        return {
            "person": person_name,
            "collaborators": collaborators[:top_k],
            "total_unique": len(collaborators),
        }
    
    def get_timeline(self, style_id: str, 
                     group_by_category: bool = True) -> Dict[str, Any]:
        """
        查询某款号的完整时序
        
        Returns:
            {
                "style_id": "CCSS230021",
                "timeline": [
                    {"date": "2022-11-25", "category": "调纸样", "event_type": "提交", "description": "..."},
                    ...
                ],
                "by_category": {
                    "调纸样": [{...}, {...}],
                    "样衣": [{...}]
                },
                "total_events": 60
            }
        """
        style_node = f"Style:{style_id}"
        if style_node not in self.G:
            return {"style_id": style_id, "timeline": [], "error": "款号不存在"}
        
        events = []
        
        # 收集所有关联事件
        for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "BELONGS_TO", "in"):
            event_data = self._get_node(neighbor)
            if event_data and event_data.get("label") == "Event":
                events.append({
                    "event_id": event_data.get("event_id", ""),
                    "date": event_data.get("date", ""),
                    "category": event_data.get("category", ""),
                    "event_type": event_data.get("event_type", ""),
                    "description": event_data.get("description", ""),
                    "delay_days": event_data.get("delay_days"),
                    "party_from": event_data.get("party_from", ""),
                    "party_to": event_data.get("party_to", ""),
                    "confidence": event_data.get("confidence", 0.0),
                    "source_filename":event_data.get("source_filename", ""),
                    "source_subject":event_data.get("source_subject", ""),
                })
        
        # 按日期排序
        events.sort(key=lambda x: x.get("date", ""))
        
        result = {
            "style_id": style_id,
            "timeline": events,
            "total_events": len(events),
        }
        
        # 按 category 分组
        if group_by_category:
            by_category = defaultdict(list)
            for e in events:
                by_category[e["category"]].append(e)
            result["by_category"] = dict(by_category)
        
        return result
    
    def get_last_update(self, style_id: str) -> Dict[str, Any]:
        """
        查询某款号的最后更新时间
        
        Returns:
            {
                "style_id": "CCSS230021",
                "last_update": "2023-08-25",
                "latest_category": "调纸样",
                "days_since_update": 123,
                "latest_event": {"date": "...", "description": "..."}
            }
        """
        style_node = f"Style:{style_id}"
        if style_node not in self.G:
            return {"style_id": style_id, "error": "款号不存在"}
        
        style_data = self._get_node(style_node)
        last_update = style_data.get("last_update", "")
        latest_category = style_data.get("latest_category", "")
        
        # 计算距今天数
        days_since = None
        if last_update:
            last_date = self._parse_date(last_update)
            if last_date:
                days_since = (datetime.now() - last_date).days
        
        # 获取最新事件详情
        latest_event = None
        timeline = self.get_timeline(style_id, group_by_category=False)
        if timeline.get("timeline"):
            latest_event = timeline["timeline"][-1]
        
        return {
            "style_id": style_id,
            "last_update": last_update,
            "latest_category": latest_category,
            "days_since_update": days_since,
            "latest_event": latest_event,
        }
    
    def get_factory_delays(self, top_k: int = 10) -> Dict[str, Any]:
        """
        查询工厂延期统计（需要工厂数据）
        
        Returns:
            {
                "factories": [
                    {"name": "东台鸿丰", "code": "HF001", "style_count": 15, "total_delay_days": 45, "avg_delay": 3.0},
                    ...
                ],
                "total_factories": 5
            }
        """
        factories = []
        
        for node_id, data in self._get_nodes_by_label("Factory"):
            factories.append({
                "factory_id": data.get("factory_id", ""),
                "name": data.get("name", ""),
                "code": data.get("code", ""),
                "location": data.get("location", ""),
                "style_count": data.get("style_count", 0) or 0,
                "total_delay_days": data.get("total_delay_days", 0) or 0,
                "delay_event_count": data.get("delay_event_count", 0) or 0,
                "avg_delay": round(
                    (data.get("total_delay_days", 0) or 0) / max(data.get("delay_event_count", 1), 1), 2
                ),
            })
        
        # 按 total_delay_days 排序
        factories.sort(key=lambda x: x["total_delay_days"], reverse=True)
        
        return {
            "factories": factories[:top_k],
            "total_factories": len(factories),
        }
    
    def get_styles_by_factory(self, factory_name_or_code: str) -> Dict[str, Any]:
        """
        查询某工厂处理的所有款号
        
        Returns:
            {
                "factory": "东台鸿丰",
                "styles": [
                    {"style_id": "CCSS230021", "order_id": "ORDER-001", "start_date": "2023-01-15", "total_delay": 5},
                    ...
                ],
                "total_styles": 15
            }
        """
        # 查找工厂节点
        factory_node = None
        factory_data = None
        
        for node_id, data in self._get_nodes_by_label("Factory"):
            if (data.get("name") == factory_name_or_code or 
                data.get("code") == factory_name_or_code or
                data.get("factory_id") == factory_name_or_code):
                factory_node = node_id
                factory_data = data
                break
        
        if not factory_node:
            return {"factory": factory_name_or_code, "styles": [], "error": "工厂不存在"}
        
        styles = []
        
        # 通过 PRODUCED_BY 关系查找
        for neighbor, rel_type, edge_data in self._get_neighbors(factory_node, "PRODUCED_BY", "in"):
            style_data = self._get_node(neighbor)
            if style_data and style_data.get("label") == "Style":
                styles.append({
                    "style_id": style_data.get("style_id", ""),
                    "order_id": edge_data.get("order_id", ""),
                    "start_date": edge_data.get("start_date", ""),
                    "last_update": style_data.get("last_update", ""),
                    "total_delay_days": style_data.get("total_delay_days", 0) or 0,
                    "event_count": style_data.get("event_count", 0) or 0,
                })
        
        # 按 last_update 降序
        styles.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        return {
            "factory": factory_data.get("name", factory_name_or_code),
            "factory_code": factory_data.get("code", ""),
            "styles": styles,
            "total_styles": len(styles),
        }
    
    def get_department_styles(self, dept_name: str) -> Dict[str, Any]:
        """
        查询某部门参与的所有款号
        
        Returns:
            {
                "department": "业务部",
                "members": ["Paula Cheng", "Iris Jiang"],
                "styles": [
                    {"style_id": "CCSS230021", "primary_owner": "Paula Cheng", "last_update": "2023-08-25"},
                    ...
                ],
                "total_styles": 120
            }
        """
        # 查找部门节点
        dept_node = None
        for node_id, data in self._get_nodes_by_label("Department"):
            if data.get("name") == dept_name or data.get("dept_id") == dept_name:
                dept_node = node_id
                break
        
        if not dept_node:
            return {"department": dept_name, "styles": [], "error": "部门不存在"}
        
        # 获取部门成员
        members = []
        member_nodes = []
        for neighbor, rel_type, edge_data in self._get_neighbors(dept_node, "BELONGS_TO_DEPT", "in"):
            person_data = self._get_node(neighbor)
            if person_data:
                members.append(person_data.get("name", ""))
                member_nodes.append(neighbor)
        
        # 收集所有成员参与的款号
        styles = []
        seen_styles = set()
        
        for member_node in member_nodes:
            for neighbor, rel_type, edge_data in self._get_neighbors(member_node, "INVOLVED_IN"):
                style_data = self._get_node(neighbor)
                if style_data and style_data.get("label") == "Style":
                    style_id = style_data.get("style_id", "")
                    if style_id not in seen_styles:
                        seen_styles.add(style_id)
                        
                        # 找负责人
                        primary_owner = None
                        for p_node, p_rel, p_data in self._get_neighbors(neighbor, "RESPONSIBLE_FOR", "in"):
                            p_info = self._get_node(p_node)
                            if p_info:
                                primary_owner = p_info.get("name", "")
                                break
                        
                        styles.append({
                            "style_id": style_id,
                            "primary_owner": primary_owner,
                            "last_update": style_data.get("last_update", ""),
                            "total_delay_days": style_data.get("total_delay_days", 0) or 0,
                        })
        
        styles.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        return {
            "department": dept_name,
            "members": members,
            "member_count": len(members),
            "styles": styles,
            "total_styles": len(styles),
        }
    
    def find_styles_with_conditions(self, 
                                    categories: List[str] = None,
                                    min_delay_days: int = None,
                                    factory_name: str = None,
                                    person_name: str = None,
                                    customer_email: str = None) -> Dict[str, Any]:
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
                    {"style_id": "CCSS230021", "matched_categories": ["Lab Dip", "样衣"], "total_delay": 15},
                    ...
                ],
                "total": 10
            }
        """
        candidates = set()
        
        # 从 factory 筛选
        if factory_name:
            factory_result = self.get_styles_by_factory(factory_name)
            factory_styles = {s["style_id"] for s in factory_result.get("styles", [])}
            if not candidates:
                candidates = factory_styles
            else:
                candidates &= factory_styles
        
        # 从 person 筛选
        if person_name:
            person_result = self.get_styles_by_person(person_name)
            person_styles = {s["style_id"] for s in person_result.get("styles", [])}
            if not candidates:
                candidates = person_styles
            else:
                candidates &= person_styles
        
        # 从 customer 筛选
        if customer_email:
            customer_result = self.get_styles_by_customer(customer_email)
            customer_styles = {s["style_id"] for s in customer_result.get("styles", [])}
            if not candidates:
                candidates = customer_styles
            else:
                candidates &= customer_styles
        
        # 如果没有 factory/person/customer 条件，从所有 Style 开始
        if not candidates:
            candidates = {data.get("style_id", "") 
                         for _, data in self._get_nodes_by_label("Style")}
        
        # 应用 category 和 delay 条件
        results = []
        for style_id in candidates:
            if not style_id:
                continue
            
            style_node = f"Style:{style_id}"
            style_data = self._get_node(style_node)
            if not style_data:
                continue
            
            # 检查 delay
            total_delay = style_data.get("total_delay_days", 0) or 0
            if min_delay_days is not None and total_delay < min_delay_days:
                continue
            
            # 检查 categories
            matched_categories = []
            if categories:
                timeline = self.get_timeline(style_id, group_by_category=True)
                style_categories = set(timeline.get("by_category", {}).keys())
                matched_categories = [c for c in categories if c in style_categories]
                if len(matched_categories) < len(categories):
                    continue
            
            results.append({
                "style_id": style_id,
                "matched_categories": matched_categories,
                "total_delay_days": total_delay,
                "event_count": style_data.get("event_count", 0) or 0,
                "last_update": style_data.get("last_update", ""),
                "latest_category": style_data.get("latest_category", ""),
                "factory": None,  # 可在后续补充
            })
        
        # 按 total_delay 排序
        results.sort(key=lambda x: x["total_delay_days"], reverse=True)
        
        return {
            "conditions": {
                "categories": categories,
                "min_delay_days": min_delay_days,
                "factory_name": factory_name,
                "person_name": person_name,
                "customer_email": customer_email,
            },
            "styles": results,
            "total": len(results),
        }
    
    # ============ 客户查询接口 ============
    
    def get_customers_by_style(self, style_id: str) -> Dict[str, Any]:
        """
        查询某款号关联的所有客户
        
        Returns:
            {
                "style_id": "CCSS230011",
                "customers": [
                    {"name": "Heidi Knight", "email": "heidi@curated-collective.co.uk"},
                    ...
                ],
                "total_customers": 2
            }
        """
        style_node = f"Style:{style_id}"
        if style_node not in self.G:
            return {"style_id": style_id, "customers": [], "error": "款号不存在"}
        
        customers = []
        for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "ORDERED_BY", "out"):
            customer_data = self._get_node(neighbor)
            if customer_data and customer_data.get("label") == "Customer":
                customers.append({
                    "name": customer_data.get("name", ""),
                    "email": customer_data.get("email", ""),
                    "source": customer_data.get("source", ""),
                })
        
        return {
            "style_id": style_id,
            "customers": customers,
            "total_customers": len(customers),
        }
    
    def get_styles_by_customer(self, customer_email: str) -> Dict[str, Any]:
        """
        查询某客户关联的所有款号
        
        Returns:
            {
                "customer": "heidi@curated-collective.co.uk",
                "customer_name": "Heidi Knight",
                "styles": [
                    {"style_id": "CCSS230011", "event_count": 50, "latest_category": "面料"},
                    ...
                ],
                "total_styles": 12
            }
        """
        customer_node = f"Customer:{customer_email.lower()}"
        if customer_node not in self.G:
            return {"customer": customer_email, "styles": [], "error": "客户不存在"}
        
        customer_data = self._get_node(customer_node)
        styles = []
        
        for neighbor, rel_type, edge_data in self._get_neighbors(customer_node, "HAS_STYLE", "out"):
            style_data = self._get_node(neighbor)
            if style_data and style_data.get("label") == "Style":
                styles.append({
                    "style_id": style_data.get("style_id", ""),
                    "event_count": style_data.get("event_count", 0) or 0,
                    "latest_category": style_data.get("latest_category", ""),
                    "last_update": style_data.get("last_update", ""),
                    "total_delay_days": style_data.get("total_delay_days", 0) or 0,
                })
        
        styles.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        return {
            "customer": customer_email,
            "customer_name": customer_data.get("name", "") if customer_data else "",
            "source": customer_data.get("source", "") if customer_data else "",
            "styles": styles,
            "total_styles": len(styles),
        }
    
    def get_all_customers(self, min_styles: int = 0) -> Dict[str, Any]:
        """
        获取所有客户列表
        
        Args:
            min_styles: 最少关联款号数（筛选活跃客户）
            
        Returns:
            {
                "customers": [
                    {"name": "Heidi Knight", "email": "...", "style_count": 12, "source": "..."},
                    ...
                ],
                "total": 6,
                "active_count": 3
            }
        """
        customers = []
        active_count = 0
        
        for node_id, data in self._get_nodes_by_label("Customer"):
            style_count = data.get("style_count", 0) or 0
            if style_count >= min_styles:
                customers.append({
                    "name": data.get("name", ""),
                    "email": data.get("email", ""),
                    "style_count": style_count,
                    "source": data.get("source", ""),
                })
                if style_count > 0:
                    active_count += 1
        
        customers.sort(key=lambda x: x["style_count"], reverse=True)
        
        return {
            "customers": customers,
            "total": len(customers),
            "active_count": active_count,
        }
    
    def get_customer_details(self, customer_email: str) -> Dict[str, Any]:
        """
        获取客户详细信息（款号 + 关联人员 + 工厂）
        
        Returns:
            {
                "customer": {...},
                "styles": [...],
                "related_people": [...],
                "related_factories": [...]
            }
        """
        customer_node = f"Customer:{customer_email.lower()}"
        if customer_node not in self.G:
            return {"customer": None, "error": "客户不存在"}
        
        customer_data = self._get_node(customer_node)
        
        # 客户关联的款号
        styles_result = self.get_styles_by_customer(customer_email)
        
        # 从款号推断关联人员（内部人员）
        related_people = set()
        related_factories = set()
        
        for style_info in styles_result.get("styles", []):
            style_id = style_info["style_id"]
            style_node = f"Style:{style_id}"
            
            # 关联人员
            for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "INVOLVED_IN", "in"):
                person_data = self._get_node(neighbor)
                if person_data and person_data.get("label") == "Person":
                    related_people.add(person_data.get("name", ""))
            
            # 关联工厂
            for neighbor, rel_type, edge_data in self._get_neighbors(style_node, "PRODUCED_BY", "out"):
                factory_data = self._get_node(neighbor)
                if factory_data and factory_data.get("label") == "Factory":
                    related_factories.add(factory_data.get("name", ""))
        
        return {
            "customer": {
                "name": customer_data.get("name", ""),
                "email": customer_data.get("email", ""),
                "source": customer_data.get("source", ""),
                "style_count": customer_data.get("style_count", 0) or 0,
            },
            "styles": styles_result.get("styles", []),
            "related_people": sorted(list(related_people)),
            "related_factories": sorted(list(related_factories)),
        }
    
    def get_subordinates(self, manager_name: str) -> Dict[str, Any]:
        """
        查询某人的下属
        
        Returns:
            {
                "manager": "Paula Cheng",
                "subordinates": [
                    {"name": "Iris Jiang", "role": "跟单员", "style_count": 25},
                    ...
                ],
                "total": 3
            }
        """
        manager_node = f"Person:{manager_name}"
        if manager_node not in self.G:
            return {"manager": manager_name, "subordinates": [], "error": "人员不存在"}
        
        subordinates = []
        
        # 查找 REPORTS_TO 指向 manager 的人
        for node_id, data in self._get_nodes_by_label("Person"):
            for neighbor, rel_type, edge_data in self._get_neighbors(node_id, "REPORTS_TO"):
                if neighbor == manager_node:
                    person_data = self._get_node(node_id)
                    if person_data:
                        subordinates.append({
                            "name": person_data.get("name", ""),
                            "person_id": person_data.get("person_id", ""),
                            "role": person_data.get("role", ""),
                            "style_count": person_data.get("style_count", 0) or 0,
                            "event_count": person_data.get("event_count", 0) or 0,
                        })
                    break
        
        return {
            "manager": manager_name,
            "subordinates": subordinates,
            "total": len(subordinates),
        }


# ============ 命令行测试入口 ============

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="知识图谱查询测试")
    parser.add_argument("--graph", default="email_kg_pipeline/output/kg_graph.pkl", help="图谱文件路径")
    parser.add_argument("--query", required=True, 
                       choices=["people_by_style", "styles_by_person", "collaborators",
                               "timeline", "last_update", "factory_delays", 
                               "styles_by_factory", "department_styles",
                               "find_styles", "subordinates",
                               "customers_by_style", "styles_by_customer", 
                               "all_customers", "customer_details"],
                       help="查询类型")
    parser.add_argument("--param", required=True, help="查询参数（如款号、人员名、客户邮箱）")
    parser.add_argument("--top-k", type=int, default=10, help="返回数量限制")
    
    args = parser.parse_args()
    
    # 加载图谱
    kg = EmailKnowledgeGraph.load(args.graph)
    engine = KGQueryEngine(kg)
    
    # 执行查询
    if args.query == "people_by_style":
        result = engine.get_people_by_style(args.param)
    elif args.query == "styles_by_person":
        result = engine.get_styles_by_person(args.param)
    elif args.query == "collaborators":
        result = engine.get_collaborators(args.param, args.top_k)
    elif args.query == "timeline":
        result = engine.get_timeline(args.param)
    elif args.query == "last_update":
        result = engine.get_last_update(args.param)
    elif args.query == "factory_delays":
        result = engine.get_factory_delays(args.top_k)
    elif args.query == "styles_by_factory":
        result = engine.get_styles_by_factory(args.param)
    elif args.query == "department_styles":
        result = engine.get_department_styles(args.param)
    elif args.query == "subordinates":
        result = engine.get_subordinates(args.param)
    elif args.query == "customers_by_style":
        result = engine.get_customers_by_style(args.param)
    elif args.query == "styles_by_customer":
        result = engine.get_styles_by_customer(args.param)
    elif args.query == "all_customers":
        result = engine.get_all_customers(min_styles=int(args.param) if args.param.isdigit() else 0)
    elif args.query == "customer_details":
        result = engine.get_customer_details(args.param)
    else:
        result = {"error": "未知查询类型"}
    
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
