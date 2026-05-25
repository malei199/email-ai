#!/usr/bin/env python3
"""
邮件前置过滤脚本
功能：去重 / 黑名单过滤 / 短内容过滤 / 系统邮件降采样
输出：生成待处理的邮件清单 JSONL

使用方法：
  python email_rag_pipeline/pre_filter_emails.py
  python email_rag_pipeline/pre_filter_emails.py --min-length 300
"""

import os
import re
import json
import argparse
from datetime import datetime
from collections import defaultdict, Counter
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import email
from email.parser import BytesParser
from email.header import decode_header
from glob import glob


# ============ 配置 ============
CONFIG = {
    "eml_dir": "data/eml_files",
    "output_dir": "email_rag_pipeline/output/new",
    
    # 内容长度阈值：清洗后正文少于该字符数的邮件直接过滤
    "min_content_length": 200,
    
    # 同主题去重：保留每个主题的 N 封最新邮件
    "max_per_subject": 1,
    
    # 系统邮件域名/发件人白名单中的内容质量阈值
    "system_sender_min_length": 300,
}

# 黑名单：主题关键词（直接过滤）
SUBJECT_BLACKLIST = [
    r'^\s*Undeliverable\b',
    r'^\s*Delivery Status Notification\b',
    r'^\s*Out of Office\b',
    r'^\s*Automatic\s+Reply\b',
    r'^\s*Auto\s*Reply\b',
    r'^\s*系统自动回复\b',
    r'^\s*您的验证码\b',
    r'^\s*Verify\s+your\b',
    r'^\s*Security\s+alert\b',
    r'^\s*安全提醒\b',
    r'^\s*订阅确认\b',
    r'^\s*Unsubscribe\b',
    r'^\s*退信\b',
    r'^\s*Mail Delivery Subsystem\b',
]

# 黑名单：发件人关键词（直接过滤）
# 注意：donotreply@ / noreply@ 是很多业务系统的合法发件人（如 ediTRACK），
# 此处只过滤明确的系统/退信地址，不过滤通用 no-reply 地址
SENDER_BLACKLIST = [
    r'postmaster@',
    r'mailer-daemon@',
]

# 系统发送域名（不直接过滤，但适用更严格的内容长度阈值）
SYSTEM_DOMAINS = [
    'editrack.com',
]

# 款号正则（与 build_email_event_rag.py 保持一致）
STYLE_ID_PATTERNS = {
    'CCSS': r'\bCCSS\d{5,6}[A-Z]?\b',
    'INDO': r'\bINDO[A-Z]\d{3,6}\b',
    'AW': r'\bAW\d{2}-[A-Z]+\d+\b',
    'AW_SHORT': r'\bAW\d{2}[A-Z]+\d+\b',
    'SS': r'\bSS\d{2}[A-Z]+\d+\b',
    'CCAW': r'\bCCAW\d{5,6}\b',
    'CDIB': r'\bCDIB\d+\b',
    'NL_STYLE': r'\b\d{7}\b',  # New Look 系统常用 7 位纯数字款号
}

# 业务关键词（短邮件保护）
BUSINESS_KEYWORDS = [
    # 款号前缀
    'CCSS', 'INDO', 'AW', 'SS', 'CCAW', 'CDIB',
    # 阶段关键词
    '样衣', '面料', '出货', '延期', '封样', '核料', '纸样',
    '试身', '修改', '产前', '测试', '船样', '验货', '开裁',
    # 动作关键词
    '确认', '提交', '批复', '给意见', '回传', '查货',
    # 英文关键词
    'sample', 'fabric', 'shipment', 'fitting', 'pattern',
    'lab dip', 'pp sample', 'bulk', 'delivery', 'qc',
]

# 预编译正则
SUBJECT_BLACKLIST_RE = [re.compile(p, re.IGNORECASE) for p in SUBJECT_BLACKLIST]
SENDER_BLACKLIST_RE = [re.compile(p, re.IGNORECASE) for p in SENDER_BLACKLIST]
STYLE_ID_RE = {k: re.compile(v, re.IGNORECASE) for k, v in STYLE_ID_PATTERNS.items()}
BUSINESS_KEYWORDS_RE = re.compile('|'.join(BUSINESS_KEYWORDS), re.IGNORECASE)


def decode_subject(raw_value: str) -> str:
    """正确解码邮件头"""
    if not raw_value:
        return ""
    parts = []
    for part, charset in decode_header(raw_value):
        if isinstance(part, bytes):
            try:
                parts.append(part.decode(charset or 'utf-8', errors='ignore'))
            except:
                parts.append(part.decode('utf-8', errors='ignore'))
        else:
            parts.append(part)
    return "".join(parts)


def clean_html(html: str) -> str:
    """简单 HTML 清理"""
    if not html:
        return ""
    html = re.sub(r'<(script|style)[^>]*>[^<]*</\1>', ' ', html, flags=re.I | re.S)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    html = re.sub(r'\s+', ' ', html)
    return html.strip()


def extract_content(filepath: str) -> Tuple[str, str, str, str, Optional[datetime]]:
    """快速提取邮件内容：只读取前 16KB 加速解析，同时返回解析后的日期"""
    try:
        with open(filepath, 'rb') as f:
            raw = f.read(16384)  # 只读前 16KB，足够覆盖邮件头+正文开头
        msg = BytesParser().parsebytes(raw)
    except:
        return "", "", "", "", None
    
    subject = decode_subject(msg.get("Subject", ""))
    sender = msg.get("From", "")
    date_str = msg.get("Date", "")
    
    # 解析日期
    mail_date = None
    if date_str:
        for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z"]:
            try:
                mail_date = datetime.strptime(date_str.strip(), fmt)
                break
            except:
                continue
    
    text_plain = ""
    text_html = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in part.get("Content-Disposition", ""):
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                ctype = part.get_content_type()
                text = None
                for enc in ['utf-8', 'gb18030', 'gbk', 'gb2312', 'latin-1']:
                    try:
                        text = payload.decode(enc, errors='ignore')
                        break
                    except:
                        continue
                if text:
                    if ctype == 'text/plain':
                        text_plain += text + "\n"
                    elif ctype == 'text/html':
                        text_html += text + "\n"
            except:
                pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                for enc in ['utf-8', 'gb18030', 'gbk', 'gb2312', 'latin-1']:
                    try:
                        text_plain = payload.decode(enc, errors='ignore')
                        break
                    except:
                        continue
        except:
            pass
    
    return text_plain, text_html, subject, sender, mail_date


def remove_email_noise(text: str) -> str:
    """去除签名、转发头等"""
    lines = text.split('\n')
    cleaned = []
    in_sig = False
    in_forward = False
    
    markers_sig = [
        r'^\s*[-=_]{2,}\s*$',
        r'^\s*Best regards\s*[,.]?\s*$',
        r'^\s*Regards\s*[,.]?\s*$',
        r'^\s*Thanks\s*[,.]?\s*$',
        r'^\s*谢谢\s*[,.!?]?\s*$',
        r'^\s*此致\s*[,.]?\s*$',
        r'^\s*Tel[:\s]',
        r'^\s*Email[:\s]',
        r'^\s*地址[:\s]',
        r'^\s*发件人\s*[:：]',
    ]
    markers_forward = [
        r'^\s*[-]+\s*Original Message\s*[-]+',
        r'^\s*From:\s*',
        r'^\s*To:\s*',
        r'^\s*Sent:\s*',
        r'^\s*Subject:\s*',
        r'^\s*主题\s*[:：]',
        r'^\s*收件人\s*[:：]',
    ]
    
    for line in lines:
        if any(re.search(p, line, re.I) for p in markers_forward):
            in_forward = True
            continue
        if any(re.search(p, line, re.I) for p in markers_sig):
            in_sig = True
            continue
        if in_sig and line.strip() == '':
            in_sig = False
            continue
        if in_forward and line.strip() and not re.match(r'^\s*\w+[:\s]', line):
            in_forward = False
        if in_forward or in_sig:
            continue
        cleaned.append(line)
    
    text = '\n'.join(cleaned)
    text = re.sub(r'\[IMAGE\d+\]', '', text, flags=re.I)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def extract_style_ids_from_text(text: str) -> List[str]:
    """从文本中提取款号"""
    found = set()
    for name, pattern in STYLE_ID_RE.items():
        for match in pattern.findall(text):
            found.add(match.upper())
    return sorted(list(found))


def normalize_subject(subject: str) -> str:
    """移除回复/转发前缀，用于去重"""
    s = re.sub(r'^(回复:|Re:|RE:|答复:|Fw:|FW:|转发:)\s*', '', subject, flags=re.I)
    return s.strip()


def is_blacklisted(subject: str, sender: str) -> Tuple[bool, str]:
    """判断是否在黑名单中"""
    for pat in SUBJECT_BLACKLIST_RE:
        if pat.search(subject):
            return True, f"subject_blacklist:{pat.pattern}"
    for pat in SENDER_BLACKLIST_RE:
        if pat.search(sender):
            return True, f"sender_blacklist:{pat.pattern}"
    return False, ""


def is_system_sender(sender: str) -> bool:
    sender_lower = sender.lower()
    for domain in SYSTEM_DOMAINS:
        if domain in sender_lower:
            return True
    return False


def parse_email_date(filepath: str) -> Optional[datetime]:
    """尝试解析邮件日期（备用函数，已内联到 extract_content 中）"""
    return None


def has_business_keywords(text: str) -> bool:
    """检查是否包含业务关键词"""
    return bool(BUSINESS_KEYWORDS_RE.search(text))


def process_one_file(filepath: str, min_length: int) -> Optional[Dict]:
    """处理单封邮件，返回记录或过滤原因"""
    filename = os.path.basename(filepath)
    text_plain, text_html, subject, sender, mail_date = extract_content(filepath)
    
    # 黑名单检查
    is_black, reason = is_blacklisted(subject, sender)
    if is_black:
        return {"status": "blacklist_filtered", "reason": reason}
    
    # 内容清洗和长度计算
    content = text_plain if text_plain.strip() else clean_html(text_html)
    cleaned = remove_email_noise(content)
    content_length = len(cleaned)
    
    # 提取款号
    style_ids = extract_style_ids_from_text(subject + " " + cleaned[:500])  # 只检查前500字符
    has_style_id = len(style_ids) > 0
    
    # 检查是否包含业务关键词
    has_business = has_business_keywords(cleaned[:300])  # 检查前300字符
    
    # 长度过滤（业务邮件放宽阈值）
    effective_min_length = CONFIG["system_sender_min_length"] if is_system_sender(sender) else min_length
    
    # 保护规则：包含款号或业务关键词的短邮件不过滤
    if content_length < effective_min_length:
        if has_style_id or has_business:
            # 业务邮件，放宽到 50 字符
            if content_length < 50:
                return {"status": "too_short_filtered", "length": content_length, "protected": False}
        else:
            return {"status": "too_short_filtered", "length": content_length}
    
    return {
        "status": "passed",
        "record": {
            "filename": filename,
            "filepath": filepath,
            "subject": subject,
            "normalized_subject": normalize_subject(subject),
            "sender": sender,
            "content_length": content_length,
            "style_ids": style_ids,
            "has_business_keywords": has_business,
            "is_system_sender": is_system_sender(sender),
            "mail_date": mail_date.isoformat() if mail_date else None,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="邮件前置过滤")
    parser.add_argument("--min-length", type=int, default=CONFIG["min_content_length"],
                        help=f"清洗后最小内容长度阈值（默认 {CONFIG['min_content_length']}）")
    parser.add_argument("--max-per-subject", type=int, default=CONFIG["max_per_subject"],
                        help=f"同主题保留最大数量（默认 {CONFIG['max_per_subject']}）")
    args = parser.parse_args()
    
    min_length = args.min_length
    max_per_subject = args.max_per_subject
    
    eml_files = sorted(glob(os.path.join(CONFIG["eml_dir"], "*.eml")))
    print(f"[INFO] 发现 {len(eml_files)} 封邮件")
    
    # 第一步：多线程并发评估
    records = []
    stats = Counter()
    
    with ThreadPoolExecutor(max_workers=16) as executor:
        future_to_file = {executor.submit(process_one_file, fp, min_length): fp for fp in eml_files}
        results = []
        for future in as_completed(future_to_file):
            results.append(future.result())
    
    # 单线程聚合结果（避免 Counter 线程安全问题）
    for result in results:
        if result is None:
            stats["error"] += 1
            continue
        
        status = result["status"]
        stats[status] += 1
        
        if status == "passed":
            records.append(result["record"])
    
    print(f"[INFO] 第一轮过滤后保留: {len(records)} 封")
    print(f"  黑名单过滤: {stats['blacklist_filtered']}")
    print(f"  短内容过滤: {stats['too_short_filtered']}")
    
    # 第二步：智能去重
    # 策略：
    # 1. 有款号的邮件：按款号+阶段分组，同一款号的同一阶段保留最新1封
    # 2. 无款号的邮件：按主题去重，保留最新 N 封
    style_id_groups = defaultdict(list)   # 有款号的邮件
    no_style_records = []                  # 无款号的邮件
    
    for rec in records:
        style_ids = rec.get("style_ids", [])
        if style_ids:
            # 按款号分组（一封邮件可能包含多个款号，归入第一个）
            style_id_groups[style_ids[0]].append(rec)
        else:
            no_style_records.append(rec)
    
    final_records = []
    
    # 处理有款号的邮件：每款号保留最新 3 封（覆盖不同阶段）
    for style_id, group in style_id_groups.items():
        group.sort(key=lambda x: x["mail_date"] or "1970-01-01T00:00:00", reverse=True)
        kept = group[:3]  # 同一款号保留最多3封
        final_records.extend(kept)
        if len(group) > 3:
            stats["style_id_deduplicated"] += len(group) - 3
    
    # 处理无款号的邮件：按主题去重
    subject_groups = defaultdict(list)
    for rec in no_style_records:
        subject_groups[rec["normalized_subject"]].append(rec)
    
    for norm_subj, group in subject_groups.items():
        group.sort(key=lambda x: x["mail_date"] or "1970-01-01T00:00:00", reverse=True)
        kept = group[:max_per_subject]
        final_records.extend(kept)
        if len(group) > max_per_subject:
            stats["subject_deduplicated"] += len(group) - max_per_subject
    
    print(f"[INFO] 智能去重后保留: {len(final_records)} 封")
    print(f"  款号去重移除: {stats.get('style_id_deduplicated', 0)}")
    print(f"  主题去重移除: {stats.get('subject_deduplicated', 0)}")
    
    # 统计
    with_style = sum(1 for r in final_records if r.get("style_ids"))
    system_count = sum(1 for r in final_records if r["is_system_sender"])
    print(f"  其中含款号邮件: {with_style}")
    print(f"  其中系统邮件(editrack): {system_count}")
    
    # 保存结果
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    output_file = os.path.join(CONFIG["output_dir"], "filtered_email_manifest.jsonl")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for rec in final_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    
    # 保存统计
    stats_file = os.path.join(CONFIG["output_dir"], "filter_stats.json")
    final_stats = {
        "timestamp": datetime.now().isoformat(),
        "total_emails": len(eml_files),
        "passed_first_round": stats["passed"],
        "blacklist_filtered": stats["blacklist_filtered"],
        "too_short_filtered": stats["too_short_filtered"],
        "style_id_deduplicated": stats.get("style_id_deduplicated", 0),
        "subject_deduplicated": stats.get("subject_deduplicated", 0),
        "final_count": len(final_records),
        "emails_with_style_id": with_style,
        "system_emails_in_final": system_count,
        "top_style_ids": Counter(
            r["style_ids"][0] for r in final_records if r.get("style_ids")
        ).most_common(20),
        "top_subjects": Counter(r["normalized_subject"] for r in final_records).most_common(20),
    }
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(final_stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n[SUCCESS] 过滤完成！")
    print(f"  原始: {len(eml_files)} 封 → 最终: {len(final_records)} 封")
    print(f"  过滤比例: {(1 - len(final_records)/len(eml_files))*100:.1f}%")
    print(f"  输出清单: {output_file}")
    print(f"  统计报告: {stats_file}")


if __name__ == "__main__":
    main()
