#!/usr/bin/env python3
"""
知识图谱查询测试脚本 (V2 - 含 Customer 节点)
支持：款号时间线、相关人员、工厂信息、客户信息、延期统计等查询

用法:
    # 款号查询
    python email_kg_pipeline/scripts/test_queries.py --style AW25-KFWTS101
    python email_kg_pipeline/scripts/test_queries.py --style CCSS230021 --detail

    # 人员查询
    python email_kg_pipeline/scripts/test_queries.py --person "Paula Cheng"

    # 工厂查询
    python email_kg_pipeline/scripts/test_queries.py --factory HF001
    python email_kg_pipeline/scripts/test_queries.py --delays

    # 客户查询 (新增)
    python email_kg_pipeline/scripts/test_queries.py --customer heidi@curated-collective.co.uk
    python email_kg_pipeline/scripts/test_queries.py --customers

    # 关键词搜索
    python email_kg_pipeline/scripts/test_queries.py --style AW25-KFWTS101 --question 拉链
"""

import sys
import os
import json
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
from email_kg_pipeline.src.kg_query import KGQueryEngine


def load_graph(graph_path="email_kg_pipeline/output/kg_graph_with_customers.pkl"):
    """加载知识图谱"""
    if not os.path.exists(graph_path):
        # 尝试备用路径
        alt_paths = [
            "email_kg_pipeline/output/kg_graph.pkl",
            "email_kg_pipeline/email_kg_pipeline/output/kg_graph_with_customers.pkl",
        ]
        for alt in alt_paths:
            if os.path.exists(alt):
                graph_path = alt
                break
        else:
            print(f"[ERROR] 图谱文件不存在: {graph_path}")
            print("请先运行: python email_kg_pipeline/src/kg_builder.py")
            sys.exit(1)

    kg = EmailKnowledgeGraph.load(graph_path)
    engine = KGQueryEngine(kg)
    return kg, engine


def load_events(events_path="email_rag_pipeline/output/new/events_passed.json"):
    """加载事件数据"""
    # 尝试多个路径
    alt_paths = [
        events_path,
        "email_rag_pipeline/output/events_passed.json",
    ]
    for path in alt_paths:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    print(f"[WARN] 事件文件不存在")
    return []


def print_section(title):
    """打印分隔标题"""
    print()
    print(f"{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def query_style_timeline(engine, style_id):
    """查询款号时间线"""
    print_section(f"款号 {style_id} - 时间线")

    result = engine.get_timeline(style_id)
    events = result.get('timeline', [])

    if not events:
        print("  [无事件记录]")
        return

    print(f"  共 {len(events)} 个事件:\n")

    for i, evt in enumerate(events, 1):
        date = evt.get('date', 'N/A')
        category = evt.get('category', 'N/A')
        event_type = evt.get('event_type', 'N/A')
        desc = evt.get('description', '')
        delay = evt.get('delay_days', 0)
        party_from = evt.get('party_from', '')
        party_to = evt.get('party_to', '')

        delay_str = f" [延期{delay}天]" if delay and delay > 0 else ""

        print(f"  {i}. [{date}] {category} | {event_type}{delay_str}")
        print(f"     {desc[:100]}{'...' if len(desc) > 100 else ''}")
        if party_from or party_to:
            print(f"     参与方: {party_from or '?'} → {party_to or '?'}")
        print()


def query_style_people(engine, style_id):
    """查询款号相关人员"""
    print_section(f"款号 {style_id} - 相关人员")

    result = engine.get_people_by_style(style_id)
    people = result.get('people', [])
    primary = result.get('primary_owner')
    customers = result.get('customers', [])

    if primary:
        print(f"  [主要负责人] {primary}")

    if not people:
        print("  [无人员记录]")
    else:
        print(f"\n  共 {len(people)} 人参与:\n")

        for p in people:
            name = p.get('name', 'N/A')
            role = p.get('role', 'N/A')
            event_count = p.get('event_count', 0)
            org_role = p.get('org_role', '')
            dept = p.get('department', '')

            extra = []
            if org_role:
                extra.append(f"职务:{org_role}")
            if dept:
                dept_names = {'dept_biz': '业务部', 'dept_tech': '技术部', 'dept_fabric': '面料部',
                             'dept_qc': 'QC部', 'dept_logistics': '物流部', 'dept_admin': '行政部'}
                extra.append(f"部门:{dept_names.get(dept, dept)}")

            extra_str = f" ({', '.join(extra)})" if extra else ""
            print(f"  - {name} | {role} | 参与{event_count}个事件{extra_str}")

    # 新增：显示客户信息
    if customers:
        print(f"\n  [关联客户] {len(customers)} 个:")
        for c in customers:
            print(f"    - {c.get('name', 'N/A')} ({c.get('email', '')})")


def query_style_factory(kg, style_id):
    """查询款号所属工厂"""
    print_section(f"款号 {style_id} - 工厂信息")

    G = kg.G
    style_node = f"Style:{style_id}"

    if style_node not in G:
        print("  [款号不存在]")
        return

    # 查找 PRODUCED_BY 关系
    factory_found = False
    for v in G.successors(style_node):
        edge_data = G.get_edge_data(style_node, v)
        if edge_data:
            for key, ed in edge_data.items():
                if ed.get('rel_type') == 'PRODUCED_BY':
                    factory_data = G.nodes[v]
                    name = factory_data.get('name', v)
                    code = factory_data.get('code', '')
                    location = factory_data.get('location', '')
                    contact = factory_data.get('contact_person', '')
                    status = factory_data.get('status', '')
                    style_count = factory_data.get('style_count', 0)
                    total_delay = factory_data.get('total_delay_days', 0)

                    print(f"  工厂名称: {name}")
                    print(f"  工厂代码: {code}")
                    print(f"  所在地: {location}")
                    print(f"  联系人: {contact}")
                    print(f"  合作状态: {status}")
                    print(f"  该工厂款号数: {style_count}")
                    print(f"  该工厂总延期: {total_delay}天")
                    factory_found = True

    if not factory_found:
        print("  [未关联工厂]")


def query_style_customers(engine, style_id):
    """查询款号关联客户 (新增)"""
    print_section(f"款号 {style_id} - 关联客户")

    result = engine.get_customers_by_style(style_id)
    customers = result.get('customers', [])

    if not customers:
        print("  [无客户关联]")
        return

    print(f"  共 {len(customers)} 个客户:\n")
    for c in customers:
        print(f"  - {c.get('name', 'N/A')}")
        print(f"    邮箱: {c.get('email', '')}")
        print(f"    来源: {c.get('source', '')}")


def query_style_last_update(engine, style_id):
    """查询款号最后更新"""
    print_section(f"款号 {style_id} - 最后更新")

    result = engine.get_last_update(style_id)
    print(f"  最后更新日期: {result.get('last_update', 'N/A')}")
    print(f"  距今天数: {result.get('days_since_update', 'N/A')}天")


def search_events_by_keyword(events, style_id, keyword):
    """在事件中搜索关键词"""
    print_section(f"款号 {style_id} - 关键词 \"{keyword}\" 搜索")

    matched = []
    for e in events:
        if e.get('style_id') != style_id:
            continue

        desc = e.get('description', '')
        subj = e.get('source_subject', '')

        if keyword.lower() in desc.lower() or keyword.lower() in subj.lower():
            matched.append(e)

    if not matched:
        print(f"  [未找到包含 \"{keyword}\" 的事件]")
        return

    print(f"  找到 {len(matched)} 条相关事件:\n")

    for i, e in enumerate(matched, 1):
        date = e.get('date', 'N/A')
        category = e.get('category', 'N/A')
        desc = e.get('description', '')
        party_from = e.get('party_from', '')
        party_to = e.get('party_to', '')
        filename = e.get('source_filename', '')
        subject = e.get('source_subject', '')
        confidence = e.get('confidence', 0)

        print(f"  {i}. [{date}] {category} (置信度:{confidence})")
        print(f"     描述: {desc}")
        if party_from or party_to:
            print(f"     方向: {party_from or '?'} → {party_to or '?'}")
        print(f"     来源邮件: {filename}")
        if subject:
            print(f"     邮件主题: {subject}")
        print()


def query_person_styles(engine, person_name):
    """查询人员参与的款号"""
    print_section(f"人员 {person_name} - 参与款号")

    result = engine.get_styles_by_person(person_name)
    styles = result.get('styles', [])

    if not styles:
        print("  [无款号记录]")
        return

    print(f"  共参与 {len(styles)} 个款号:\n")

    for s in styles[:20]:
        sid = s.get('style_id', 'N/A')
        role = s.get('role', 'N/A')
        last_update = s.get('last_update', 'N/A')
        delay = s.get('total_delay_days', 0)

        delay_str = f" [延期{delay}天]" if delay and delay > 0 else ""
        print(f"  - {sid} | {role} | 最后更新:{last_update}{delay_str}")

    if len(styles) > 20:
        print(f"\n  ... 还有 {len(styles) - 20} 个款号")


def query_factory_delays(engine, top_k=10):
    """查询工厂延期排名"""
    print_section("工厂延期统计")

    result = engine.get_factory_delays(top_k=top_k)
    factories = result.get('factories', [])

    if not factories:
        print("  [无工厂数据]")
        return

    print(f"  {'排名':<4} {'工厂':<30} {'款号数':>6} {'延期天数':>10} {'平均延期':>10}")
    print(f"  {'-'*64}")

    for i, f in enumerate(factories, 1):
        name = f.get('name', 'N/A')[:28]
        styles = f.get('style_count', 0)
        delay = f.get('total_delay_days', 0)
        avg = f.get('avg_delay', 0)

        print(f"  {i:<4} {name:<30} {styles:>6} {delay:>10} {avg:>10.1f}")


# ============ 新增客户查询接口 ============

def query_customer_styles(engine, customer_email):
    """查询客户关联的所有款号 (新增)"""
    print_section(f"客户 {customer_email} - 关联款号")

    result = engine.get_styles_by_customer(customer_email)
    styles = result.get('styles', [])
    customer_name = result.get('customer_name', '')

    print(f"  客户名称: {customer_name}")
    print(f"  共关联 {len(styles)} 个款号:\n")

    for s in styles[:20]:
        sid = s.get('style_id', 'N/A')
        category = s.get('latest_category', 'N/A')
        last_update = s.get('last_update', 'N/A')
        event_count = s.get('event_count', 0)
        delay = s.get('total_delay_days', 0)

        delay_str = f" [延期{delay}天]" if delay and delay > 0 else ""
        print(f"  - {sid} | {category} | {event_count}事件 | 更新:{last_update}{delay_str}")

    if len(styles) > 20:
        print(f"\n  ... 还有 {len(styles) - 20} 个款号")


def query_customer_details(engine, customer_email):
    """查询客户详细信息 (新增)"""
    print_section(f"客户 {customer_email} - 详细信息")

    result = engine.get_customer_details(customer_email)
    customer = result.get('customer', {})

    if not customer:
        print("  [客户不存在]")
        return

    print(f"  名称: {customer.get('name', 'N/A')}")
    print(f"  邮箱: {customer.get('email', 'N/A')}")
    print(f"  来源: {customer.get('source', 'N/A')}")
    print(f"  关联款号数: {customer.get('style_count', 0)}")

    related_people = result.get('related_people', [])
    if related_people:
        print(f"\n  [关联内部人员] {len(related_people)} 人:")
        for name in related_people[:15]:
            print(f"    - {name}")
        if len(related_people) > 15:
            print(f"    ... 还有 {len(related_people) - 15} 人")

    related_factories = result.get('related_factories', [])
    if related_factories:
        print(f"\n  [关联工厂] {len(related_factories)} 家:")
        for fname in related_factories:
            print(f"    - {fname}")


def query_all_customers(engine, min_styles=0):
    """查询所有客户列表 (新增)"""
    print_section(f"客户列表 (最少{min_styles}个款号)")

    result = engine.get_all_customers(min_styles=min_styles)
    customers = result.get('customers', [])

    if not customers:
        print("  [无客户记录]")
        return

    print(f"  共 {result.get('total', 0)} 个客户，其中 {result.get('active_count', 0)} 个有款号关联:\n")

    print(f"  {'名称':<25} {'邮箱':<40} {'款号数':>6} {'来源':<20}")
    print(f"  {'-'*95}")

    for c in customers:
        name = c.get('name', 'N/A')[:23]
        email = c.get('email', 'N/A')[:38]
        style_count = c.get('style_count', 0)
        source = c.get('source', 'N/A')[:18]
        print(f"  {name:<25} {email:<40} {style_count:>6} {source:<20}")


def query_full_style_info(kg, engine, events, style_id, detail=False):
    """查询款号完整信息"""
    print(f"\n{'#'*70}")
    print(f"# 款号查询报告: {style_id}")
    print(f"{'#'*70}")

    # 1. 基本信息
    query_style_last_update(engine, style_id)

    # 2. 工厂信息
    query_style_factory(kg, style_id)

    # 3. 客户信息 (新增)
    query_style_customers(engine, style_id)

    # 4. 相关人员
    query_style_people(engine, style_id)

    # 5. 时间线
    query_style_timeline(engine, style_id)

    # 6. 如果需要详细信息，搜索原始邮件
    if detail:
        print_section(f"款号 {style_id} - 原始事件数据")
        style_events = [e for e in events if e.get('style_id') == style_id]
        print(f"  共 {len(style_events)} 个原始事件")

        if style_events:
            print("\n  按分类汇总:")
            from collections import Counter
            cats = Counter(e.get('category', '未知') for e in style_events)
            for cat, count in cats.most_common():
                print(f"    {cat}: {count}个")


def main():
    parser = argparse.ArgumentParser(description="知识图谱查询测试脚本 (V2 - 含 Customer)")

    # 原有参数
    parser.add_argument("--style", help="查询款号（如 AW25-KFWTS101）")
    parser.add_argument("--person", help="查询人员（如 \"Paula Cheng\"）")
    parser.add_argument("--factory", help="查询工厂代码（如 HF001）")
    parser.add_argument("--question", help="关键词搜索（如 拉链、尺寸、延期）")
    parser.add_argument("--delays", action="store_true", help="工厂延期排名")
    parser.add_argument("--detail", action="store_true", help="显示详细信息（含原始事件统计）")

    # 新增客户查询参数
    parser.add_argument("--customer", help="查询客户邮箱（如 heidi@curated-collective.co.uk）")
    parser.add_argument("--customers", action="store_true", help="列出所有客户")
    parser.add_argument("--min-styles", type=int, default=0, help="客户最少款号数筛选（配合 --customers）")
    parser.add_argument("--customer-detail", action="store_true", help="显示客户详细信息（含关联人员/工厂）")

    parser.add_argument("--graph", default="email_kg_pipeline/output/kg_graph_with_customers.pkl",
                        help="图谱文件路径")

    args = parser.parse_args()

    # 加载数据
    print("[INFO] 加载知识图谱...")
    kg, engine = load_graph(args.graph)

    events = []
    if args.detail or args.question:
        events = load_events()

    # 执行查询
    if args.style:
        query_full_style_info(kg, engine, events, args.style, args.detail)

        # 如果有关键词，额外搜索
        if args.question:
            search_events_by_keyword(events, args.style, args.question)

    elif args.person:
        query_person_styles(engine, args.person)

    elif args.factory:
        print_section(f"工厂 {args.factory} - 款号列表")
        result = engine.get_styles_by_factory(args.factory)
        styles = result.get('styles', [])

        if not styles:
            print("  [无款号记录]")
        else:
            print(f"  共 {len(styles)} 个款号:\n")
            for s in styles[:30]:
                sid = s.get('style_id', 'N/A')
                order = s.get('order_id', 'N/A')
                print(f"  - {sid} (订单:{order})")
            if len(styles) > 30:
                print(f"\n  ... 还有 {len(styles) - 30} 个款号")

    elif args.delays:
        query_factory_delays(engine)

    # 新增客户查询
    elif args.customer:
        if args.customer_detail:
            query_customer_details(engine, args.customer)
        else:
            query_customer_styles(engine, args.customer)

    elif args.customers:
        query_all_customers(engine, min_styles=args.min_styles)

    elif args.question and not args.style:
        print("[ERROR] 关键词搜索需要配合 --style 参数使用")
        print("示例: python test_queries.py --style AW25-KFWTS101 --question 拉链")

    else:
        parser.print_help()
        print("\n" + "="*60)
        print("常用查询示例:")
        print("="*60)
        print("  款号查询:    python test_queries.py --style CCSS230021")
        print("  人员查询:    python test_queries.py --person \"Paula Cheng\"")
        print("  工厂查询:    python test_queries.py --factory HF001")
        print("  客户列表:    python test_queries.py --customers")
        print("  活跃客户:    python test_queries.py --customers --min-styles 1")
        print("  客户款号:    python test_queries.py --customer heidi@curated-collective.co.uk")
        print("  客户详情:    python test_queries.py --customer heidi@curated-collective.co.uk --customer-detail")
        print("  工厂延期:    python test_queries.py --delays")
        print("="*60)


if __name__ == "__main__":
    main()
