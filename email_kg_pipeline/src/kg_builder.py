#!/usr/bin/env python3
"""
邮件知识图谱构建器
功能：从 events.json + factory_mapping.csv + organization.json 构建 NetworkX 知识图谱

使用方法:
  1. 准备数据文件:
     - email_rag_pipeline/output/events_passed.json (已有)
     - email_kg_pipeline/data/factory_mapping.csv (用户提供)
     - email_kg_pipeline/data/organization.json (用户提供)
  
  2. 构建图谱:
     python email_kg_pipeline/src/kg_builder.py
  
  3. 使用图谱:
     from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
     kg = EmailKnowledgeGraph.load('email_kg_pipeline/output/kg_graph.pkl')
"""

import os
import json
import csv
import pickle
import re
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path

try:
    import networkx as nx
except ImportError:
    print("[ERROR] 缺少 networkx 依赖")
    print("请运行: pip install networkx")
    raise SystemExit(1)


# ============ 配置 ============
DEFAULT_CONFIG = {
    "events_file": "email_rag_pipeline/output/new/events_passed.json",
    "factory_file": "email_kg_pipeline/data/factory_mapping.csv",
    "org_file": "email_kg_pipeline/data/organization.json",
    "email_summary_file": "data/data-summary/email_summary.json",
    "output_dir": "email_kg_pipeline/output",
    "graph_file": "email_kg_pipeline/output/kg_graph_with_customers.pkl",
    "stats_file": "email_kg_pipeline/output/kg_stats.json",
}

# ============ 客户识别规则 ============
# 基于 email_summary.json 的 company_people 字段
# 标准：真实外部客户（有采购订单往来、人工邮件沟通）
CUSTOMER_SOURCE_FIELDS = [
    "Indochine UK",  # UK 客户，indochine.co.uk 域名
    "Curated Collective (客户/合作方)",  # UK 客户，.co.uk 域名
]

# 内部字段（非客户）
INTERNAL_SOURCE_FIELDS = [
    "Indochine (主公司)",
    "New Look EDI (系统)",
]

# 系统/自动发送字段（不建立 Customer 节点）
SYSTEM_SOURCE_FIELDS = [
    "New Look (客户)",  # 客户编辑系统后自动发送，无人工沟通价值
]


# ============ 人员名归一化规则 ============
NAME_NORMALIZATION = {
    # 大小写变体合并
    "Paula Cheng": ["PAULA CHENG"],
    "Iris Jiang": ["IRIS JIANG"],
    "Suresh": ["SURESH"],
    "Leo Lin": ["LEO LIN"],
    "Judy": ["JUDY"],
    "Layna Yan": ["Layna yan"],
    "Lisa/Vivi": ["Lisa/vivi"],
    "Lee": ["lee"],
}

# 反向映射：变体 -> 标准名
VARIANT_TO_STANDARD = {}
for standard, variants in NAME_NORMALIZATION.items():
    for v in variants:
        VARIANT_TO_STANDARD[v] = standard


class EmailKnowledgeGraph:
    """
    邮件知识图谱
    
    基于 NetworkX 的多图（MultiDiGraph），支持:
    - 节点属性存储
    - 多类型关系
    - 关系属性
    - 预计算统计
    """
    
    def __init__(self, config: Dict[str, str] = None):
        self.config = config or DEFAULT_CONFIG
        self.G = nx.MultiDiGraph()
        self._person_name_map = {}  # 原始名 -> 标准名
        self._build_time = None
        
    # ============ 人员名归一化 ============
    
    def _normalize_person_name(self, name: str) -> str:
        """归一化人员名称"""
        if not name or name in ["未知", "工厂", "客人", "供应商"]:
            return None
        
        name = name.strip()
        
        # 检查是否在变体映射中
        if name in VARIANT_TO_STANDARD:
            return VARIANT_TO_STANDARD[name]
        
        # Title case 标准化
        name = name.title()
        
        # 再次检查（title case 后可能匹配）
        if name in VARIANT_TO_STANDARD:
            return VARIANT_TO_STANDARD[name]
        
        return name
    
    # ============ 节点创建 ============
    
    def _add_style_node(self, style_id: str, **props) -> str:
        """添加/更新 Style 节点"""
        node_id = f"Style:{style_id}"
        if node_id not in self.G:
            self.G.add_node(node_id, 
                          label="Style",
                          style_id=style_id,
                          **props)
        else:
            # 更新属性
            for k, v in props.items():
                if v is not None:
                    self.G.nodes[node_id][k] = v
        return node_id
    
    def _add_event_node(self, event_id: str, **props) -> str:
        """添加 Event 节点"""
        node_id = f"Event:{event_id}"
        self.G.add_node(node_id, label="Event", **props)
        return node_id
    
    def _add_person_node(self, person_id: str, name: str, **props) -> str:
        """添加/更新 Person 节点"""
        node_id = f"Person:{person_id}"
        if node_id not in self.G:
            self.G.add_node(node_id,
                          label="Person",
                          person_id=person_id,
                          name=name,
                          **props)
        else:
            # 更新属性（保留已有值）
            for k, v in props.items():
                if v is not None and self.G.nodes[node_id].get(k) is None:
                    self.G.nodes[node_id][k] = v
        return node_id
    
    def _add_factory_node(self, factory_id: str, **props) -> str:
        """添加 Factory 节点"""
        node_id = f"Factory:{factory_id}"
        if node_id not in self.G:
            self.G.add_node(node_id, label="Factory", factory_id=factory_id, **props)
        return node_id
    
    def _add_category_node(self, name: str) -> str:
        """添加 Category 节点"""
        node_id = f"Category:{name}"
        if node_id not in self.G:
            self.G.add_node(node_id, label="Category", name=name)
        return node_id
    
    def _add_department_node(self, dept_id: str, **props) -> str:
        """添加 Department 节点"""
        node_id = f"Department:{dept_id}"
        if node_id not in self.G:
            self.G.add_node(node_id, label="Department", dept_id=dept_id, **props)
        return node_id
    
    def _add_email_node(self, filename: str, **props) -> str:
        """添加 Email 节点"""
        node_id = f"Email:{filename}"
        if node_id not in self.G:
            self.G.add_node(node_id, label="Email", filename=filename, **props)
        return node_id
    
    def _add_customer_node(self, email: str, name: str = "", **props) -> str:
        """添加 Customer 节点"""
        node_id = f"Customer:{email}"
        if node_id not in self.G:
            self.G.add_node(node_id,
                          label="Customer",
                          email=email,
                          name=name or email.split('@')[0],
                          **props)
        else:
            # 更新名称（如果之前未识别）
            if name and not self.G.nodes[node_id].get("name"):
                self.G.nodes[node_id]["name"] = name
        return node_id
    
    # ============ 关系创建 ============
    
    def _add_rel(self, from_id: str, to_id: str, rel_type: str, **props):
        """添加关系边"""
        self.G.add_edge(from_id, to_id, key=rel_type, rel_type=rel_type, **props)
    
    # ============ 核心构建流程 ============
    
    def build_from_events(self, events: List[Dict]):
        """从事件列表构建图谱核心结构"""
        print(f"[INFO] 开始构建图谱，事件数: {len(events)}")
        
        # 统计用的临时结构
        style_events = defaultdict(list)
        style_people = defaultdict(set)
        person_events = defaultdict(list)
        person_styles = defaultdict(set)
        email_events = defaultdict(list)
        category_events = defaultdict(list)
        collaboration_pairs = defaultdict(int)
        
        for idx, evt in enumerate(events):
            event_id = f"evt_{idx}"
            style_id = evt.get("style_id", "")
            category = evt.get("category", "")
            
            # 1. 创建 Event 节点
            event_node = self._add_event_node(
                event_id=event_id,
                category=category,
                event_type=evt.get("event_type", ""),
                date=evt.get("date", ""),
                related_date=evt.get("related_date", ""),
                delay_days=evt.get("delay_days") if evt.get("delay_days") not in [None, -999] else None,
                description=evt.get("description", ""),
                confidence=evt.get("confidence", 0.0),
                source_filename=evt.get("source_filename", ""),
                source_subject=evt.get("source_subject", "")
            )
            
            # 2. 创建/关联 Style 节点
            if style_id and style_id != "UNKNOWN":
                style_node = self._add_style_node(style_id=style_id)
                self._add_rel(event_node, style_node, "BELONGS_TO")
                style_events[style_id].append(evt)
                
                # 收集人员关联
                people_in_event = []
                for field in ["party_from", "party_to"]:
                    raw_name = evt.get(field, "")
                    norm_name = self._normalize_person_name(raw_name)
                    if norm_name:
                        people_in_event.append(norm_name)
                        style_people[style_id].add(norm_name)
                        person_events[norm_name].append(evt)
                        person_styles[norm_name].add(style_id)
                
                # 协作关系
                for i, p1 in enumerate(people_in_event):
                    for p2 in people_in_event[i+1:]:
                        if p1 != p2:
                            pair = tuple(sorted([p1, p2]))
                            collaboration_pairs[pair] += 1
            
            # 3. 关联 Category 节点
            if category:
                cat_node = self._add_category_node(category)
                self._add_rel(event_node, cat_node, "HAS_CATEGORY")
                category_events[category].append(evt)
            
            # 4. 关联 Email 节点
            filename = evt.get("source_filename", "")
            if filename:
                email_node = self._add_email_node(
                    filename=filename,
                    subject=evt.get("source_subject", "")
                )
                self._add_rel(event_node, email_node, "FROM_EMAIL")
                email_events[filename].append(evt)
            
            # 5. 创建 Person 节点和 PARTICIPATED_IN 关系
            for field in ["party_from", "party_to"]:
                raw_name = evt.get(field, "")
                norm_name = self._normalize_person_name(raw_name)
                if norm_name:
                    person_node = self._add_person_node(
                        person_id=norm_name,
                        name=norm_name,
                        is_from_email=True
                    )
                    self._add_rel(person_node, event_node, "PARTICIPATED_IN", role=field)
        
        # 6. 创建 INVOLVED_IN 关系（人员-款号）
        print("[INFO] 构建 Person-Style 关系...")
        for person_name, styles in person_styles.items():
            person_node = f"Person:{person_name}"
            for style_id in styles:
                style_node = f"Style:{style_id}"
                event_count = sum(1 for e in person_events[person_name] 
                                if e.get("style_id") == style_id)
                self._add_rel(person_node, style_node, "INVOLVED_IN", 
                            involvement_type="participant",
                            event_count=event_count)
        
        # 7. 创建 COLLABORATED_WITH 关系
        print("[INFO] 构建协作关系...")
        for (p1, p2), count in collaboration_pairs.items():
            p1_node = f"Person:{p1}"
            p2_node = f"Person:{p2}"
            common_styles = person_styles[p1] & person_styles[p2]
            self._add_rel(p1_node, p2_node, "COLLABORATED_WITH",
                        event_count=count,
                        style_count=len(common_styles))
            self._add_rel(p2_node, p1_node, "COLLABORATED_WITH",
                        event_count=count,
                        style_count=len(common_styles))
        
        # 8. 创建 FOLLOWS 时序关系
        print("[INFO] 构建时序关系...")
        for style_id, evts in style_events.items():
            # 按 category 分组，组内按日期排序
            cat_events = defaultdict(list)
            for e in evts:
                cat_events[e.get("category", "其他")].append(e)
            
            for cat, cat_evts in cat_events.items():
                sorted_evts = sorted(cat_evts, key=lambda x: x.get("date", ""))
                for i in range(len(sorted_evts) - 1):
                    e1_id = f"Event:evt_{events.index(sorted_evts[i])}"
                    e2_id = f"Event:evt_{events.index(sorted_evts[i+1])}"
                    
                    # 计算时间间隔
                    gap = None
                    d1 = sorted_evts[i].get("date", "")
                    d2 = sorted_evts[i+1].get("date", "")
                    if d1 and d2:
                        try:
                            gap = (datetime.strptime(d2, "%Y-%m-%d") - 
                                   datetime.strptime(d1, "%Y-%m-%d")).days
                        except:
                            pass
                    
                    self._add_rel(e1_id, e2_id, "FOLLOWS", time_gap_days=gap)
        
        # 9. 计算 Style 预计算属性
        print("[INFO] 计算 Style 预计算属性...")
        for style_id, evts in style_events.items():
            style_node = f"Style:{style_id}"
            dates = [e.get("date", "") for e in evts if e.get("date")]
            delays = [e.get("delay_days") for e in evts 
                     if e.get("delay_days") is not None and e.get("delay_days") != 0]
            
            if dates:
                self.G.nodes[style_node]["first_event_date"] = min(dates)
                self.G.nodes[style_node]["last_update"] = max(dates)
            
            self.G.nodes[style_node]["event_count"] = len(evts)
            self.G.nodes[style_node]["delay_event_count"] = len(delays)
            self.G.nodes[style_node]["total_delay_days"] = sum(d for d in delays if d is not None)
            
            # 推断最新阶段
            if dates:
                latest_evt = max(evts, key=lambda x: x.get("date", ""))
                self.G.nodes[style_node]["latest_category"] = latest_evt.get("category", "")
            
            # 聚合所有关联的 order_id
            order_ids = set()
            for e in evts:
                oid = e.get("order_id", "")
                if oid:
                    order_ids.add(oid)
            if order_ids:
                self.G.nodes[style_node]["order_ids"] = sorted(list(order_ids))
        
        # 10. 计算 Person 预计算属性
        print("[INFO] 计算 Person 预计算属性...")
        for person_name in person_styles:
            person_node = f"Person:{person_name}"
            self.G.nodes[person_node]["event_count"] = len(person_events[person_name])
            self.G.nodes[person_node]["style_count"] = len(person_styles[person_name])
        
        # 11. 计算 Category 预计算属性
        print("[INFO] 计算 Category 预计算属性...")
        for cat_name, evts in category_events.items():
            cat_node = f"Category:{cat_name}"
            delays = [e.get("delay_days") for e in evts 
                     if e.get("delay_days") is not None and e.get("delay_days") != 0]
            self.G.nodes[cat_node]["event_count"] = len(evts)
            self.G.nodes[cat_node]["delay_event_count"] = len(delays)
            if delays:
                self.G.nodes[cat_node]["avg_delay_days"] = round(sum(delays) / len(delays), 2)
        
        # 12. 计算 Email 预计算属性
        for filename, evts in email_events.items():
            email_node = f"Email:{filename}"
            self.G.nodes[email_node]["event_count"] = len(evts)
        
        print(f"[SUCCESS] 事件图谱构建完成")
        return {
            "style_events": style_events,
            "style_people": style_people,
            "person_events": person_events,
            "person_styles": person_styles,
        }
    
    def integrate_factory_data(self, factory_file: str):
        """整合工厂数据"""
        if not os.path.exists(factory_file):
            print(f"[WARN] 工厂数据文件不存在: {factory_file}")
            return
        
        print(f"[INFO] 导入工厂数据: {factory_file}")
        
        factories = {}  # factory_name -> factory_id
        style_factory_map = {}  # style_id -> factory_info
        
        with open(factory_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                style_id = row.get("style_id", "").strip()
                factory_name = row.get("factory_name", "").strip()
                factory_code = row.get("factory_code", "").strip()
                
                if not style_id or not factory_name:
                    continue
                
                # 生成 factory_id
                factory_id = factory_code if factory_code else re.sub(r'[^\w]', '_', factory_name)
                factories[factory_name] = factory_id
                style_factory_map[style_id] = {
                    "factory_id": factory_id,
                    "factory_name": factory_name,
                    "factory_code": factory_code,
                    "location": row.get("factory_location", "").strip(),
                    "contact_person": row.get("contact_person", "").strip(),
                    "status": row.get("status", "").strip(),
                    "order_id": row.get("order_id", "").strip(),
                    "start_date": row.get("start_date", "").strip(),
                }
        
        # 创建 Factory 节点
        for factory_name, factory_id in factories.items():
            info = next((v for v in style_factory_map.values() 
                        if v["factory_id"] == factory_id), {})
            self._add_factory_node(
                factory_id=factory_id,
                name=factory_name,
                code=info.get("factory_code", ""),
                location=info.get("location", ""),
                contact_person=info.get("contact_person", ""),
                status=info.get("status", "")
            )
        
        # 建立 Style-Factory 关系
        linked_count = 0
        for style_id, info in style_factory_map.items():
            style_node = f"Style:{style_id}"
            factory_node = f"Factory:{info['factory_id']}"
            
            if style_node in self.G and factory_node in self.G:
                self._add_rel(style_node, factory_node, "PRODUCED_BY",
                            order_id=info.get("order_id", ""),
                            start_date=info.get("start_date", ""))
                linked_count += 1
        
        # 计算 Factory 预计算属性
        factory_styles = defaultdict(list)
        for style_id, info in style_factory_map.items():
            factory_styles[info["factory_id"]].append(style_id)
        
        for factory_id, styles in factory_styles.items():
            factory_node = f"Factory:{factory_id}"
            if factory_node in self.G:
                self.G.nodes[factory_node]["style_count"] = len(styles)
                
                # 计算该工厂的延期统计
                total_delay = 0
                delay_count = 0
                for style_id in styles:
                    style_node = f"Style:{style_id}"
                    if style_node in self.G:
                        td = self.G.nodes[style_node].get("total_delay_days", 0) or 0
                        dc = self.G.nodes[style_node].get("delay_event_count", 0) or 0
                        total_delay += td
                        delay_count += dc
                
                self.G.nodes[factory_node]["total_delay_days"] = total_delay
                self.G.nodes[factory_node]["delay_event_count"] = delay_count
        
        print(f"[SUCCESS] 工厂数据导入完成: {len(factories)} 个工厂, {linked_count} 个款号关联")
    
    def integrate_org_data(self, org_file: str):
        """整合组织架构数据"""
        if not os.path.exists(org_file):
            print(f"[WARN] 组织架构文件不存在: {org_file}")
            return
        
        print(f"[INFO] 导入组织架构数据: {org_file}")
        
        with open(org_file, 'r', encoding='utf-8') as f:
            org_data = json.load(f)
        
        # 1. 创建 Department 节点
        departments = org_data.get("departments", [])
        dept_members = defaultdict(list)
        
        for dept in departments:
            dept_id = dept.get("id", "")
            if dept_id:
                self._add_department_node(
                    dept_id=dept_id,
                    name=dept.get("name", ""),
                    manager_id=dept.get("manager", "")
                )
        
        # 2. 创建/更新 Person 节点（从组织架构）
        users = org_data.get("users", [])
        user_map = {}  # user_id -> person_node
        
        for user in users:
            user_id = user.get("id", "")
            name = user.get("name", "").strip()
            if not user_id or not name:
                continue
            
            # 尝试匹配邮件中提取的人员
            norm_name = self._normalize_person_name(name)
            person_id = norm_name if norm_name else user_id
            
            person_node = self._add_person_node(
                person_id=person_id,
                name=norm_name or name,
                email=user.get("email", ""),
                department=user.get("department", ""),
                role=user.get("role", ""),
                is_from_email=False
            )
            user_map[user_id] = person_node
            
            dept_id = user.get("department", "")
            if dept_id:
                dept_members[dept_id].append(user_id)
                dept_node = f"Department:{dept_id}"
                if dept_node in self.G:
                    self._add_rel(person_node, dept_node, "BELONGS_TO_DEPT")
        
        # 3. 建立 REPORTS_TO 关系
        for user in users:
            user_id = user.get("id", "")
            reports_to = user.get("reports_to", "")
            if user_id and reports_to and user_id in user_map and reports_to in user_map:
                self._add_rel(user_map[user_id], user_map[reports_to], "REPORTS_TO")
        
        # 4. 建立 MANAGES 关系
        for dept in departments:
            manager_id = dept.get("manager", "")
            dept_id = dept.get("id", "")
            if manager_id and dept_id and manager_id in user_map:
                dept_node = f"Department:{dept_id}"
                self._add_rel(user_map[manager_id], dept_node, "MANAGES")
        
        # 5. 更新 Department member_count
        for dept_id, members in dept_members.items():
            dept_node = f"Department:{dept_id}"
            if dept_node in self.G:
                self.G.nodes[dept_node]["member_count"] = len(members)
        
        # 6. 处理 style_assignments（款号分配）
        assignments = org_data.get("style_assignments", [])
        for assign in assignments:
            style_id = assign.get("style_id", "")
            if not style_id:
                continue
            
            style_node = f"Style:{style_id}"
            if style_node not in self.G:
                continue
            
            # Primary owner -> RESPONSIBLE_FOR
            primary = assign.get("primary_owner", "")
            if primary and primary in user_map:
                self._add_rel(user_map[primary], style_node, "RESPONSIBLE_FOR",
                            assigned_date=assign.get("assigned_date", ""))
            
            # Secondary owners -> INVOLVED_IN (with type)
            for secondary in assign.get("secondary_owners", []):
                if secondary and secondary in user_map:
                    self._add_rel(user_map[secondary], style_node, "INVOLVED_IN",
                                involvement_type="secondary_owner")
            
            # Watchers -> INVOLVED_IN (with type)
            for watcher in assign.get("watchers", []):
                if watcher and watcher in user_map:
                    self._add_rel(user_map[watcher], style_node, "INVOLVED_IN",
                                involvement_type="watcher")
        
        print(f"[SUCCESS] 组织架构导入完成: {len(users)} 人, {len(departments)} 个部门, {len(assignments)} 个款号分配")
    
    def integrate_customer_data(self, email_summary_file: str):
        """整合客户数据（从 email_summary.json）"""
        if not os.path.exists(email_summary_file):
            print(f"[WARN] 邮件摘要文件不存在: {email_summary_file}")
            return
        
        print(f"[INFO] 导入客户数据: {email_summary_file}")
        
        with open(email_summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
        
        company_people = summary_data.get("company_people", {})
        
        # 收集客户邮箱
        customer_emails = {}  # email -> {name, source_field}
        
        for field_name in CUSTOMER_SOURCE_FIELDS:
            if field_name not in company_people:
                continue
            
            field_data = company_people[field_name]
            members = field_data.get("members", [])
            
            for member in members:
                email = member.get("email", "").strip().lower()
                name = member.get("name", "").strip()
                
                if not email:
                    continue
                
                # 如果同一个邮箱出现在多个字段，保留第一个名称
                if email not in customer_emails:
                    customer_emails[email] = {
                        "name": name if name and name != "(未识别)" else email.split("@")[0],
                        "source": field_name,
                    }
        
        # 创建 Customer 节点
        for email, info in customer_emails.items():
            self._add_customer_node(
                email=email,
                name=info["name"],
                source=info["source"],
            )
        
        print(f"[SUCCESS] 客户数据导入完成: {len(customer_emails)} 个客户")
        return customer_emails
    
    def build_customer_style_relations(self, email_summary_file: str, customer_emails: Dict[str, Dict]):
        """
        从 email_summary.json 中建立 Customer-Style 关系
        
        基于 top_senders 和 top_recipients 中的 style_list 字段，
        建立客户与款号之间的关联关系。
        """
        print("[INFO] 构建 Customer-Style 关系...")
        
        with open(email_summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
        
        customer_email_set = set(customer_emails.keys())
        customer_styles = defaultdict(set)   # customer_email -> set of style_ids
        style_customers = defaultdict(set)   # style_id -> set of customer_emails
        
        # 从 top_senders 提取客户-款号关联
        top_senders = summary_data.get("top_senders", {})
        for email, info in top_senders.items():
            email_lower = email.lower()
            if email_lower not in customer_email_set:
                continue
            for style_id in info.get("style_list", []):
                if style_id:
                    customer_styles[email_lower].add(style_id)
                    style_customers[style_id].add(email_lower)
        
        # 从 top_recipients 提取客户-款号关联
        top_recipients = summary_data.get("top_recipients", {})
        for email, info in top_recipients.items():
            email_lower = email.lower()
            if email_lower not in customer_email_set:
                continue
            for style_id in info.get("style_list", []):
                if style_id:
                    customer_styles[email_lower].add(style_id)
                    style_customers[style_id].add(email_lower)
        
        # 建立图谱关系
        relation_count = 0
        
        # 1. Customer -> HAS_STYLE -> Style
        for email, styles in customer_styles.items():
            customer_node = f"Customer:{email}"
            if customer_node not in self.G:
                continue
            for style_id in styles:
                style_node = f"Style:{style_id}"
                if style_node in self.G:
                    self._add_rel(customer_node, style_node, "HAS_STYLE")
                    relation_count += 1
        
        # 2. Style -> ORDERED_BY -> Customer (反向关系)
        for style_id, emails in style_customers.items():
            style_node = f"Style:{style_id}"
            if style_node not in self.G:
                continue
            for email in emails:
                customer_node = f"Customer:{email}"
                if customer_node in self.G:
                    self._add_rel(style_node, customer_node, "ORDERED_BY")
        
        # 3. 更新 Customer 节点属性
        for email, styles in customer_styles.items():
            customer_node = f"Customer:{email}"
            if customer_node in self.G:
                self.G.nodes[customer_node]["style_count"] = len(styles)
                self.G.nodes[customer_node]["style_list"] = sorted(list(styles))
        
        # 4. 更新 Style 节点属性（客户数）
        for style_id, emails in style_customers.items():
            style_node = f"Style:{style_id}"
            if style_node in self.G:
                self.G.nodes[style_node]["customer_count"] = len(emails)
        
        print(f"[SUCCESS] Customer-Style 关系构建完成: {relation_count} 条关系, "
              f"{len(customer_styles)} 个客户, {len(style_customers)} 个款号")
        
        return customer_styles, style_customers
    
    def build(self, events_file: str = None, factory_file: str = None, org_file: str = None,
              email_summary_file: str = None):
        """
        完整构建图谱
        
        Args:
            events_file: 事件 JSON 文件路径
            factory_file: 工厂映射 CSV 文件路径
            org_file: 组织架构 JSON 文件路径
            email_summary_file: 邮件摘要 JSON 文件路径（用于提取客户信息）
        """
        events_file = events_file or self.config["events_file"]
        factory_file = factory_file or self.config["factory_file"]
        org_file = org_file or self.config["org_file"]
        email_summary_file = email_summary_file or self.config.get("email_summary_file")
        
        # 1. 加载事件数据
        print(f"[INFO] 加载事件数据: {events_file}")
        with open(events_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
        print(f"[INFO] 加载了 {len(events)} 个事件")
        
        # 2. 从事件构建核心图谱
        self.build_from_events(events)
        
        # 3. 整合工厂数据
        self.integrate_factory_data(factory_file)
        
        # 4. 整合组织架构数据
        self.integrate_org_data(org_file)
        
        # 5. 整合客户数据
        customer_emails = {}
        if email_summary_file:
            customer_emails = self.integrate_customer_data(email_summary_file)
            # 建立 Customer-Style 关系（基于邮件共现）
            self.build_customer_style_relations(email_summary_file, customer_emails)
        
        # 6. 记录构建时间
        self._build_time = datetime.now().isoformat()
        
        # 6. 输出统计
        stats = self.get_stats()
        print(f"\n{'='*60}")
        print("图谱构建完成")
        print(f"{'='*60}")
        print(f"节点总数: {stats['total_nodes']}")
        print(f"关系总数: {stats['total_edges']}")
        print(f"节点类型分布: {stats['node_types']}")
        print(f"关系类型分布: {stats['edge_types']}")
        
        return stats
    
    def get_stats(self) -> Dict:
        """获取图谱统计信息"""
        node_types = Counter()
        for node, data in self.G.nodes(data=True):
            node_types[data.get("label", "Unknown")] += 1
        
        edge_types = Counter()
        for u, v, key, data in self.G.edges(keys=True, data=True):
            edge_types[data.get("rel_type", "Unknown")] += 1
        
        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
            "build_time": self._build_time,
        }
    
    def save(self, filepath: str = None):
        """保存图谱到文件"""
        filepath = filepath or self.config["graph_file"]
        # 确保目录存在（处理相对路径嵌套问题）
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        with open(filepath, 'wb') as f:
            pickle.dump({
                "graph": self.G,
                "config": self.config,
                "build_time": self._build_time,
                "person_name_map": self._person_name_map,
            }, f)
        
        # 同时保存统计信息
        stats = self.get_stats()
        stats_file = self.config.get("stats_file", filepath.replace(".pkl", "_stats.json"))
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        print(f"[SUCCESS] 图谱已保存: {filepath}")
        print(f"[SUCCESS] 统计已保存: {stats_file}")
    
    @classmethod
    def load(cls, filepath: str) -> "EmailKnowledgeGraph":
        """从文件加载图谱"""
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
        
        kg = cls(config=data.get("config", DEFAULT_CONFIG))
        kg.G = data["graph"]
        kg._build_time = data.get("build_time")
        kg._person_name_map = data.get("person_name_map", {})
        
        print(f"[SUCCESS] 图谱已加载: {filepath}")
        print(f"  节点数: {kg.G.number_of_nodes()}")
        print(f"  关系数: {kg.G.number_of_edges()}")
        return kg


# ============ 命令行入口 ============

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="邮件知识图谱构建工具")
    parser.add_argument("--events", default=DEFAULT_CONFIG["events_file"], help="事件 JSON 文件")
    parser.add_argument("--factory", default=DEFAULT_CONFIG["factory_file"], help="工厂映射 CSV 文件")
    parser.add_argument("--org", default=DEFAULT_CONFIG["org_file"], help="组织架构 JSON 文件")
    parser.add_argument("--email-summary", default=DEFAULT_CONFIG["email_summary_file"], help="邮件摘要 JSON 文件（用于客户数据）")
    parser.add_argument("--output", default=DEFAULT_CONFIG["graph_file"], help="输出图谱文件")
    parser.add_argument("--events-only", action="store_true", help="仅使用事件数据构建（跳过工厂、组织架构和客户数据）")
    
    args = parser.parse_args()
    
    kg = EmailKnowledgeGraph()
    
    # 如果只使用事件数据
    if args.events_only:
        print("[INFO] 仅使用事件数据构建图谱")
        with open(args.events, 'r', encoding='utf-8') as f:
            events = json.load(f)
        kg.build_from_events(events)
        kg._build_time = datetime.now().isoformat()
    else:
        kg.build(args.events, args.factory, args.org, args.email_summary)
    
    # 保存
    kg.config["graph_file"] = args.output
    kg.save(args.output)


if __name__ == "__main__":
    main()
