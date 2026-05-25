#!/usr/bin/env python3
"""
邮件知识图谱增量更新器
功能：新邮件到达时，增量更新图谱（不重建）

使用方法:
  from email_kg_pipeline.src.kg_updater import KGUpdater
  from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
  
  kg = EmailKnowledgeGraph.load('email_kg_pipeline/output/kg_graph.pkl')
  updater = KGUpdater(kg)
  
  # 新事件（从 LLM 提取）
  new_event = {
      "style_id": "CCSS230021",
      "category": "出货",
      "event_type": "确认",
      "date": "2025-08-20",
      "party_from": "工厂",
      "party_to": "客人",
      "description": "款号 CCSS230021 确认出货",
      "source_filename": "new_email.eml"
  }
  
  updater.add_event(new_event)
  kg.save()
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any

try:
    import networkx as nx
except ImportError:
    print("[ERROR] 缺少 networkx 依赖")
    print("请运行: pip install networkx")
    raise SystemExit(1)

from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph


class KGUpdater:
    """
    知识图谱增量更新器
    
    设计原则:
    1. 增量更新，不重建整个图谱
    2. 自动维护预计算属性
    3. 支持批量更新和单条更新
    4. 更新失败时可回滚
    """
    
    def __init__(self, kg: EmailKnowledgeGraph):
        self.kg = kg
        self.G = kg.G
        self._event_counter = self._get_max_event_counter()
        self._batch_changes = []  # 用于批量更新的变更日志
    
    def _get_max_event_counter(self) -> int:
        """获取当前最大事件编号"""
        max_counter = 0
        for node_id in self.G.nodes():
            if node_id.startswith("Event:evt_"):
                try:
                    counter = int(node_id.split("_")[1])
                    max_counter = max(max_counter, counter)
                except:
                    pass
        return max_counter
    
    def _normalize_person_name(self, name: str) -> Optional[str]:
        """复用 builder 的归一化逻辑"""
        if not name or name in ["未知", "工厂", "客人", "供应商"]:
            return None
        
        from email_kg_pipeline.src.kg_builder import VARIANT_TO_STANDARD
        
        name = name.strip()
        if name in VARIANT_TO_STANDARD:
            return VARIANT_TO_STANDARD[name]
        
        name = name.title()
        if name in VARIANT_TO_STANDARD:
            return VARIANT_TO_STANDARD[name]
        
        return name
    
    def _get_or_create_node(self, node_id: str, label: str, **props) -> str:
        """获取或创建节点"""
        if node_id not in self.G:
            self.G.add_node(node_id, label=label, **props)
        return node_id
    
    def _add_rel(self, from_id: str, to_id: str, rel_type: str, **props):
        """添加关系"""
        self.G.add_edge(from_id, to_id, key=rel_type, rel_type=rel_type, **props)
    
    def add_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        添加单个事件到图谱
        
        Args:
            event: 事件字典，格式与 events_passed.json 一致
            
        Returns:
            {
                "success": True,
                "event_id": "evt_4668",
                "updated_nodes": ["Style:CCSS230021", "Person:Paula Cheng", ...],
                "updated_properties": {
                    "Style:CCSS230021": {"last_update": "2025-08-20", "event_count": 61}
                }
            }
        """
        result = {
            "success": False,
            "event_id": None,
            "updated_nodes": [],
            "updated_properties": {},
        }
        
        try:
            self._event_counter += 1
            event_id = f"evt_{self._event_counter}"
            result["event_id"] = event_id
            
            style_id = event.get("style_id", "")
            category = event.get("category", "")
            date = event.get("date", "")
            delay_days = event.get("delay_days")
            if delay_days in [None, -999, 0]:
                delay_days = None
            
            # 1. 创建 Event 节点
            event_node = f"Event:{event_id}"
            self.G.add_node(event_node,
                          label="Event",
                          event_id=event_id,
                          category=category,
                          event_type=event.get("event_type", ""),
                          date=date,
                          related_date=event.get("related_date", ""),
                          delay_days=delay_days,
                          description=event.get("description", ""),
                          confidence=event.get("confidence", 1.0),
                          source_filename=event.get("source_filename", ""),
                          source_subject=event.get("source_subject", ""))
            result["updated_nodes"].append(event_node)
            
            # 2. 关联 Style 节点（如果存在）
            if style_id and style_id != "UNKNOWN":
                style_node = f"Style:{style_id}"
                
                # Style 节点可能不存在（新款号）
                if style_node not in self.G:
                    self.G.add_node(style_node,
                                  label="Style",
                                  style_id=style_id,
                                  first_event_date=date,
                                  last_update=date,
                                  event_count=1,
                                  delay_event_count=1 if delay_days else 0,
                                  total_delay_days=delay_days or 0,
                                  latest_category=category)
                    result["updated_nodes"].append(style_node)
                    result["updated_properties"][style_node] = "created"
                else:
                    # 更新预计算属性
                    old_props = dict(self.G.nodes[style_node])
                    new_props = {}
                    
                    # event_count
                    new_props["event_count"] = old_props.get("event_count", 0) + 1
                    
                    # last_update
                    if date and date > old_props.get("last_update", ""):
                        new_props["last_update"] = date
                        new_props["latest_category"] = category
                    
                    # first_event_date
                    if date and (not old_props.get("first_event_date") or 
                                date < old_props["first_event_date"]):
                        new_props["first_event_date"] = date
                    
                    # delay stats
                    if delay_days:
                        new_props["delay_event_count"] = old_props.get("delay_event_count", 0) + 1
                        new_props["total_delay_days"] = (old_props.get("total_delay_days", 0) or 0) + delay_days
                    
                    for k, v in new_props.items():
                        self.G.nodes[style_node][k] = v
                    
                    result["updated_properties"][style_node] = new_props
                
                # 添加 BELONGS_TO 关系
                self._add_rel(event_node, style_node, "BELONGS_TO")
                
                # 3. 处理人员
                people_in_event = []
                for field in ["party_from", "party_to"]:
                    raw_name = event.get(field, "")
                    norm_name = self._normalize_person_name(raw_name)
                    if norm_name:
                        people_in_event.append(norm_name)
                        
                        person_node = f"Person:{norm_name}"
                        
                        # 人员节点可能不存在
                        if person_node not in self.G:
                            self.G.add_node(person_node,
                                          label="Person",
                                          person_id=norm_name,
                                          name=norm_name,
                                          is_from_email=True,
                                          event_count=1,
                                          style_count=1 if style_id else 0)
                            result["updated_nodes"].append(person_node)
                        else:
                            # 更新人员统计
                            old_count = self.G.nodes[person_node].get("event_count", 0) or 0
                            self.G.nodes[person_node]["event_count"] = old_count + 1
                            
                            # 检查是否是新款号
                            involved_styles = set()
                            for _, tgt, key, data in self.G.out_edges(person_node, keys=True, data=True):
                                if data.get("rel_type") == "INVOLVED_IN":
                                    tgt_data = self.G.nodes.get(tgt, {})
                                    if tgt_data.get("label") == "Style":
                                        involved_styles.add(tgt_data.get("style_id", ""))
                            
                            if style_id not in involved_styles:
                                old_style_count = self.G.nodes[person_node].get("style_count", 0) or 0
                                self.G.nodes[person_node]["style_count"] = old_style_count + 1
                        
                        # 添加 PARTICIPATED_IN 关系
                        self._add_rel(person_node, event_node, "PARTICIPATED_IN", role=field)
                        
                        # 更新/创建 INVOLVED_IN 关系
                        involved = False
                        for _, tgt, key, data in self.G.out_edges(person_node, keys=True, data=True):
                            if (data.get("rel_type") == "INVOLVED_IN" and 
                                tgt == style_node):
                                involved = True
                                old_count = data.get("event_count", 0) or 0
                                self.G[person_node][style_node][key]["event_count"] = old_count + 1
                                break
                        
                        if not involved:
                            self._add_rel(person_node, style_node, "INVOLVED_IN",
                                        involvement_type="participant",
                                        event_count=1)
                
                # 4. 更新协作关系
                for i, p1 in enumerate(people_in_event):
                    for p2 in people_in_event[i+1:]:
                        if p1 != p2:
                            p1_node = f"Person:{p1}"
                            p2_node = f"Person:{p2}"
                            
                            # 检查是否已有协作关系
                            existing = False
                            for _, tgt, key, data in self.G.out_edges(p1_node, keys=True, data=True):
                                if (data.get("rel_type") == "COLLABORATED_WITH" and 
                                    tgt == p2_node):
                                    existing = True
                                    old_count = data.get("event_count", 0) or 0
                                    old_styles = data.get("style_count", 0) or 0
                                    self.G[p1_node][p2_node][key]["event_count"] = old_count + 1
                                    
                                    # 检查是否是新共同款号
                                    p1_styles = set()
                                    p2_styles = set()
                                    for _, t, k, d in self.G.out_edges(p1_node, keys=True, data=True):
                                        if d.get("rel_type") == "INVOLVED_IN":
                                            t_data = self.G.nodes.get(t, {})
                                            if t_data.get("label") == "Style":
                                                p1_styles.add(t_data.get("style_id", ""))
                                    for _, t, k, d in self.G.out_edges(p2_node, keys=True, data=True):
                                        if d.get("rel_type") == "INVOLVED_IN":
                                            t_data = self.G.nodes.get(t, {})
                                            if t_data.get("label") == "Style":
                                                p2_styles.add(t_data.get("style_id", ""))
                                    
                                    new_common = len(p1_styles & p2_styles)
                                    self.G[p1_node][p2_node][key]["style_count"] = new_common
                                    break
                            
                            if not existing:
                                self._add_rel(p1_node, p2_node, "COLLABORATED_WITH",
                                            event_count=1, style_count=1)
                                self._add_rel(p2_node, p1_node, "COLLABORATED_WITH",
                                            event_count=1, style_count=1)
                
                # 5. 更新 FOLLOWS 时序关系
                if category:
                    # 找到同 Style 同 Category 的前一个事件
                    prev_event = None
                    prev_date = ""
                    
                    for _, tgt, key, data in self.G.in_edges(style_node, keys=True, data=True):
                        if data.get("rel_type") == "BELONGS_TO":
                            evt_data = self.G.nodes.get(tgt, {})
                            if (evt_data.get("label") == "Event" and 
                                evt_data.get("category") == category and
                                evt_data.get("date", "") < date and
                                evt_data.get("date", "") > prev_date):
                                prev_event = tgt
                                prev_date = evt_data.get("date", "")
                    
                    if prev_event:
                        gap = None
                        if prev_date and date:
                            try:
                                gap = (datetime.strptime(date, "%Y-%m-%d") - 
                                       datetime.strptime(prev_date, "%Y-%m-%d")).days
                            except:
                                pass
                        self._add_rel(prev_event, event_node, "FOLLOWS", time_gap_days=gap)
            
            # 6. 关联 Category 节点
            if category:
                cat_node = f"Category:{category}"
                if cat_node not in self.G:
                    self.G.add_node(cat_node, label="Category", name=category,
                                  event_count=1,
                                  delay_event_count=1 if delay_days else 0)
                    result["updated_nodes"].append(cat_node)
                else:
                    old_count = self.G.nodes[cat_node].get("event_count", 0) or 0
                    self.G.nodes[cat_node]["event_count"] = old_count + 1
                    
                    if delay_days:
                        old_delay = self.G.nodes[cat_node].get("delay_event_count", 0) or 0
                        self.G.nodes[cat_node]["delay_event_count"] = old_delay + 1
                        
                        # 重新计算平均延期
                        all_delays = []
                        for _, tgt, key, data in self.G.in_edges(cat_node, keys=True, data=True):
                            if data.get("rel_type") == "HAS_CATEGORY":
                                evt_data = self.G.nodes.get(tgt, {})
                                d = evt_data.get("delay_days")
                                if d is not None and d != 0:
                                    all_delays.append(d)
                        if all_delays:
                            self.G.nodes[cat_node]["avg_delay_days"] = round(sum(all_delays) / len(all_delays), 2)
                
                self._add_rel(event_node, cat_node, "HAS_CATEGORY")
            
            # 7. 关联 Email 节点
            filename = event.get("source_filename", "")
            if filename:
                email_node = f"Email:{filename}"
                if email_node not in self.G:
                    self.G.add_node(email_node, label="Email", filename=filename,
                                  subject=event.get("source_subject", ""),
                                  event_count=1)
                    result["updated_nodes"].append(email_node)
                else:
                    old_count = self.G.nodes[email_node].get("event_count", 0) or 0
                    self.G.nodes[email_node]["event_count"] = old_count + 1
                
                self._add_rel(event_node, email_node, "FROM_EMAIL")
            
            # 8. 更新 Factory 统计（如果 Style 关联了 Factory）
            if style_id:
                style_node = f"Style:{style_id}"
                for _, tgt, key, data in self.G.out_edges(style_node, keys=True, data=True):
                    if data.get("rel_type") == "PRODUCED_BY":
                        factory_data = self.G.nodes.get(tgt, {})
                        if factory_data.get("label") == "Factory":
                            # 更新工厂延期统计
                            if delay_days:
                                old_delay = factory_data.get("total_delay_days", 0) or 0
                                old_count = factory_data.get("delay_event_count", 0) or 0
                                self.G.nodes[tgt]["total_delay_days"] = old_delay + delay_days
                                self.G.nodes[tgt]["delay_event_count"] = old_count + 1
                            
                            result["updated_nodes"].append(tgt)
                        break
            
            result["success"] = True
            self.kg._build_time = datetime.now().isoformat()
            
        except Exception as e:
            result["error"] = str(e)
            # 回滚：删除已创建的节点
            if result["event_id"]:
                event_node = f"Event:{result['event_id']}"
                if event_node in self.G:
                    self.G.remove_node(event_node)
        
        return result
    
    def add_events_batch(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量添加事件
        
        Returns:
            {
                "success_count": 10,
                "failed_count": 0,
                "results": [...]
            }
        """
        results = []
        success = 0
        failed = 0
        
        for event in events:
            result = self.add_event(event)
            results.append(result)
            if result["success"]:
                success += 1
            else:
                failed += 1
        
        return {
            "success_count": success,
            "failed_count": failed,
            "results": results,
        }
    
    def update_factory_mapping(self, style_id: str, factory_info: Dict[str, str]):
        """
        更新款号的工厂映射
        
        Args:
            style_id: 款号
            factory_info: {factory_id, factory_name, factory_code, order_id, start_date}
        """
        style_node = f"Style:{style_id}"
        if style_node not in self.G:
            print(f"[WARN] 款号不存在: {style_id}")
            return
        
        factory_id = factory_info.get("factory_id", "")
        if not factory_id:
            factory_name = factory_info.get("factory_name", "")
            factory_id = factory_info.get("factory_code", "") or factory_name
        
        factory_node = f"Factory:{factory_id}"
        
        # 创建/更新 Factory 节点
        if factory_node not in self.G:
            self.G.add_node(factory_node,
                          label="Factory",
                          factory_id=factory_id,
                          name=factory_info.get("factory_name", ""),
                          code=factory_info.get("factory_code", ""),
                          location=factory_info.get("location", ""),
                          contact_person=factory_info.get("contact_person", ""),
                          status=factory_info.get("status", ""),
                          style_count=1)
        else:
            old_count = self.G.nodes[factory_node].get("style_count", 0) or 0
            self.G.nodes[factory_node]["style_count"] = old_count + 1
        
        # 添加 PRODUCED_BY 关系
        self._add_rel(style_node, factory_node, "PRODUCED_BY",
                    order_id=factory_info.get("order_id", ""),
                    start_date=factory_info.get("start_date", ""))
        
        print(f"[SUCCESS] 更新工厂映射: {style_id} -> {factory_id}")


# ============ 命令行测试入口 ============

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="知识图谱增量更新测试")
    parser.add_argument("--graph", default="email_kg_pipeline/output/kg_graph.pkl", help="图谱文件路径")
    parser.add_argument("--event", help="单个事件 JSON 字符串")
    parser.add_argument("--events-file", help="批量事件 JSON 文件")
    
    args = parser.parse_args()
    
    # 加载图谱
    kg = EmailKnowledgeGraph.load(args.graph)
    updater = KGUpdater(kg)
    
    if args.event:
        event = json.loads(args.event)
        result = updater.add_event(event)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        kg.save(args.graph)
    
    elif args.events_file:
        with open(args.events_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
        result = updater.add_events_batch(events)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        kg.save(args.graph)
    
    else:
        print("请提供 --event 或 --events-file 参数")


if __name__ == "__main__":
    main()
