#!/usr/bin/env python3
"""
原始邮件详情提取脚本
功能：根据款号和关键词，找到原始 .eml 邮件并提取表格等详细信息

用法:
    python kg_email_detail.py --style AW25-KFWTS101 --keyword 拉链
    python kg_email_detail.py --style CCSS230021 --keyword 尺寸
    python kg_email_detail.py --filename 5441.eml              # 直接打开指定邮件
"""

import sys
import os
import json
import re
import email
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_events(events_path="email_rag_pipeline/output/events_passed.json"):
    """加载事件数据"""
    with open(events_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_eml_file(filename):
    """查找邮件文件"""
    eml_dir = "data/eml_files"
    
    # 直接匹配
    direct_path = os.path.join(eml_dir, filename)
    if os.path.exists(direct_path):
        return direct_path
    
    # 尝试前缀匹配
    name_part = filename.replace('.eml', '')
    for f in os.listdir(eml_dir):
        if f.startswith(name_part):
            return os.path.join(eml_dir, f)
    
    return None


def extract_html_tables(html_content):
    """从HTML中提取表格，只保留包含数据的表格"""
    tables = []
    table_pattern = r'<table[^>]*>(.*?)</table>'
    raw_tables = re.findall(table_pattern, html_content, re.DOTALL | re.IGNORECASE)
    
    for table_html in raw_tables:
        rows = []
        row_pattern = r'<tr[^>]*>(.*?)</tr>'
        raw_rows = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)
        
        for row in raw_rows:
            cell_pattern = r'<t[dh][^>]*>(.*?)</t[dh]>'
            cells = re.findall(cell_pattern, row, re.DOTALL | re.IGNORECASE)
            
            clean_cells = []
            for cell in cells:
                clean = re.sub('<[^<]+?>', '', cell)
                clean = clean.replace('&nbsp;', ' ')
                clean = clean.replace('&amp;', '&')
                clean = clean.strip()
                if clean:
                    clean_cells.append(clean)
            
            if clean_cells:
                rows.append(clean_cells)
        
        # 只保留有实际数据的表格（至少2行，且包含数字或Size等关键词）
        if rows and len(rows) > 1:
            has_data = any(
                re.search(r'\d', str(cell)) or 
                any(k in str(cell) for k in ['Size', 'Zipper', 'POCKET', 'Length', 'Core', 'Tall', 'Petite', 'Curve'])
                for row in rows for cell in row
            )
            if has_data:
                tables.append(rows)
    
    return tables


def print_table(table, title=""):
    """打印表格"""
    if title:
        print(f"\n【{title}】")
    
    if not table:
        return
    
    # Calculate column widths
    col_count = max(len(row) for row in table)
    col_widths = [0] * col_count
    
    for row in table:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Print table
    for i, row in enumerate(table):
        # Pad row to col_count
        padded_row = list(row) + [''] * (col_count - len(row))
        line = "  |  ".join(str(cell).ljust(col_widths[j]) for j, cell in enumerate(padded_row))
        print(f"  {line}")
        
        # Print separator after header
        if i == 0:
            sep = "-+-".join("-" * w for w in col_widths)
            print(f"  {sep}")


def analyze_email(eml_path, keyword=None):
    """分析邮件内容"""
    with open(eml_path, 'rb') as f:
        msg = email.message_from_binary_file(f)
    
    # Decode subject
    subject = msg.get('Subject', 'N/A')
    try:
        from email.header import decode_header
        decoded = decode_header(subject)
        subject_parts = []
        for part, charset in decoded:
            if isinstance(part, bytes):
                subject_parts.append(part.decode(charset or 'utf-8', errors='ignore'))
            else:
                subject_parts.append(part)
        subject = ''.join(subject_parts)
    except:
        pass
    
    # Print headers
    print(f"{'='*70}")
    print(f"邮件主题: {subject}")
    print(f"发件人: {msg.get('From', 'N/A')}")
    print(f"收件人: {msg.get('To', 'N/A')}")
    print(f"日期: {msg.get('Date', 'N/A')}")
    print(f"文件: {eml_path}")
    print(f"{'='*70}")
    
    # Extract HTML and find tables
    html = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
    
    if html:
        tables = extract_html_tables(html)
        
        if tables:
            print(f"\n找到 {len(tables)} 个数据表格:\n")
            
            for idx, table in enumerate(tables, 1):
                # Check if keyword is in table
                if keyword:
                    table_text = ' '.join(' '.join(str(c) for c in row) for row in table)
                    if keyword.lower() not in table_text.lower():
                        continue
                
                print_table(table, f"表格 {idx}")
        else:
            print("\n[未找到数据表格]")
    else:
        print("\n[邮件无HTML内容]")


def search_events_and_open(events, style_id, keyword):
    """搜索事件并打开相关邮件"""
    matched = []
    for e in events:
        if e.get('style_id') != style_id:
            continue
        desc = e.get('description', '')
        subj = e.get('source_subject', '')
        if keyword.lower() in desc.lower() or keyword.lower() in subj.lower():
            matched.append(e)
    
    if not matched:
        print(f"[未找到款号 {style_id} 包含 \"{keyword}\" 的事件]")
        return
    
    print(f"找到 {len(matched)} 条相关事件:\n")
    
    for i, e in enumerate(matched, 1):
        print(f"{i}. [{e['date']}] {e['category']}")
        print(f"   描述: {e['description']}")
        print(f"   来源: {e['source_filename']}")
        print()
    
    # Open the most relevant one (highest confidence with keyword in description)
    best = max(matched, key=lambda x: x.get('confidence', 0))
    filename = best['source_filename']
    
    print(f"正在打开最相关邮件: {filename} (置信度: {best['confidence']})\n")
    
    eml_path = find_eml_file(filename)
    if eml_path:
        analyze_email(eml_path, keyword)
    else:
        print(f"[ERROR] 找不到邮件文件: {filename}")


def main():
    parser = argparse.ArgumentParser(description="原始邮件详情提取")
    parser.add_argument("--style", help="款号（如 AW25-KFWTS101）")
    parser.add_argument("--keyword", help="关键词（如 拉链、尺寸）")
    parser.add_argument("--filename", help="直接指定邮件文件名（如 5441.eml）")
    parser.add_argument("--events", default="email_rag_pipeline/output/events_passed.json")
    
    args = parser.parse_args()
    
    if args.filename:
        # Direct open
        eml_path = find_eml_file(args.filename)
        if eml_path:
            analyze_email(eml_path, args.keyword)
        else:
            print(f"[ERROR] 找不到邮件: {args.filename}")
    
    elif args.style and args.keyword:
        # Search and open
        events = load_events(args.events)
        search_events_and_open(events, args.style, args.keyword)
    
    else:
        parser.print_help()
        print("\n示例:")
        print("  python kg_email_detail.py --style AW25-KFWTS101 --keyword 拉链")
        print("  python kg_email_detail.py --filename 5441.eml")


if __name__ == "__main__":
    main()
