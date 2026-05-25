#!/usr/bin/env python3
"""
邮件事件型 RAG 构建流水线
功能：深度清洗 .eml → DeepSeek API 提取结构化事件 → 质量过滤 → 写入 ChromaDB

使用方法：
  1. 设置环境变量: export DEEPSEEK_API_KEY="your-api-key"
  2. 试运行 10 封样本: python email_rag_pipeline/build_email_event_rag.py --sample 10
  3. 全量运行: python email_rag_pipeline/build_email_event_rag.py
  4. 断点恢复: python email_rag_pipeline/build_email_event_rag.py --resume
"""

import os
# macOS 上 PyTorch/OpenMP 库冲突修复
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import re
import json
import time
import argparse
from datetime import datetime
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple

import email
from email import policy
from email.parser import BytesParser
from email.header import decode_header

# 检查第三方依赖
try:
    import chromadb
    from chromadb.config import Settings
    from openai import OpenAI
    from tqdm import tqdm
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip install chromadb openai tqdm")
    raise SystemExit(1)

import os
os.environ['HF_ENDPOINT'] = "https://hf-mirror.com"
# sentence_transformers 延迟导入，避免 PyTorch 版本问题影响 LLM 提取阶段
SentenceTransformer = None
def get_sentence_transformer(model_name: str):
    global SentenceTransformer
    if SentenceTransformer is None:
        try:
            from sentence_transformers import SentenceTransformer as ST
            SentenceTransformer = ST
            local_save_path = '/Users/potato/Documents/baseModel'
        except ImportError as e:
            print(f"[ERROR] 无法导入 sentence_transformers: {e}")
            print("请运行: pip install 'transformers<4.40' 'sentence-transformers<2.8'")
            raise SystemExit(1)
    return SentenceTransformer(model_name, cache_folder=local_save_path)


# ============ 配置 ============
CONFIG = {
    "eml_dir": "data/eml_files",
    "output_dir": "email_rag_pipeline/output/new",
    "collection_name": "email_events_new",
    "embedding_model": "BAAI/bge-large-zh-v1.5",
    "persist_dir": "vector_db",
    
    # DeepSeek API 配置
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com",
    #"deepseek_api_key": os.environ.get("DEEPSEEK_API_KEY"),
    "deepseek_api_key": 'sk-c056cef347f84bef95c4601c88ffc1f8',
    "max_workers": 10,
    "request_timeout": 60,
    "max_retries": 3,
    "retry_delay": 2,
    
    # 质量过滤阈值
    "confidence_pass": 0.7,
    "confidence_review": 0.5,
}

# 款号/订单号正则规则（基于全量 7359 封邮件分析结果）
STYLE_ID_PATTERNS = {
    'CCSS': r'\bCCSS\d{5,6}[A-Z]?\b',           # CCSS230021, CCSS240108S
    'INDO': r'\bINDO[A-Z]\d{3,6}\b',            # INDOT22861
    'AW': r'\bAW\d{2}-[A-Z]+\d+\b',             # AW25-KFWTT156
    'AW_SHORT': r'\bAW\d{2}[A-Z]+\d+\b',        # AW25KFWTS101
    'SS': r'\bSS\d{2}[A-Z]+\d+\b',              # SS25IACB201
    'CCAW': r'\bCCAW\d{5,6}\b',                 # CCAW230050
    'CDIB': r'\bCDIB\d+\b',
    'P_SERIES': r'\bP\d{3}-[A-Z0-9]+-\d+\b',
    'NL_STYLE': r'\b\d{7}\b',                   # New Look 系统常用 7 位纯数字款号
}

# 订单号正则规则（纯数字，通常 6-9 位）
ORDER_ID_PATTERNS = {
    'ORDER_6': r'\b\d{6}\b',
    'ORDER_7': r'\b\d{7}\b',
    'ORDER_8': r'\b\d{8}\b',
    'ORDER_9': r'\b\d{9}\b',
}

# 预编译正则
STYLE_ID_RE = {k: re.compile(v, re.IGNORECASE) for k, v in STYLE_ID_PATTERNS.items()}
ORDER_ID_RE = {k: re.compile(v) for k, v in ORDER_ID_PATTERNS.items()}

# 事件分类和类型（用于 LLM Prompt 约束）
# 基于业务流程四大阶段：开发(不涉及)→报价→下订单→出货
VALID_CATEGORIES = [
    # 报价阶段
    "调纸样", "核料", "面辅料价格", "工价",
    # 下订单阶段
    "试身样", "修改样", "封样", "产前样", "测试样", "船样", "定面料", "定辅料",
    # 出货阶段
    "产前会议", "开裁", "验货", "出货", "补货",
    # 原有/通用
    "Lab Dip", "大货样", "样衣", "面料", "大货订单", "一般沟通", "其他"
]

VALID_EVENT_TYPES = [
    "提交", "确认", "回传", "出货", "延期申请",
    "给意见", "批复", "打样", "修改", "完成",
    "邮寄", "等待反馈", "补货", "抽查", "其他"
]


# ============ 工具函数 ============

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def decode_header_text(raw_value: str) -> str:
    """正确解码邮件头中的 base64/quoted-printable 编码"""
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


def extract_text_from_eml(filepath: str) -> Tuple[str, Dict[str, Any]]:
    """
    从 .eml 文件中提取文本内容和元数据
    返回: (content, metadata_dict)
    """
    try:
        with open(filepath, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
    except Exception as e:
        return "", {"error": str(e)}
    
    # 解码主题
    raw_subject = msg.get("Subject", "")
    subject = decode_header_text(raw_subject)
    
    # 提取基本信息
    meta = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "subject": subject,
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "date": msg.get("Date", ""),
    }
    
    # 提取正文
    text_plain = ""
    text_html = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disp = part.get("Content-Disposition", "")
            
            if "attachment" in disp:
                continue
            
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                text = None
                for enc in ['utf-8', 'gb18030', 'gbk', 'gb2312', 'big5', 'latin-1']:
                    try:
                        text = payload.decode(enc, errors='ignore')
                        break
                    except:
                        continue
                if text:
                    if content_type == 'text/plain':
                        text_plain += text + "\n"
                    elif content_type == 'text/html':
                        text_html += text + "\n"
            except:
                pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                for enc in ['utf-8', 'gb18030', 'gbk', 'gb2312', 'big5', 'latin-1']:
                    try:
                        text_plain = payload.decode(enc, errors='ignore')
                        break
                    except:
                        continue
        except:
            pass
    
    # 优先纯文本，否则清理 HTML
    content = text_plain if text_plain.strip() else clean_html(text_html)
    return content, meta


def clean_html(html: str) -> str:
    """激进的 HTML 清理"""
    if not html:
        return ""
    # 移除 script/style
    html = re.sub(r'<(script|style)[^>]*>[^<]*</\1>', ' ', html, flags=re.I | re.S)
    # 移除所有标签
    html = re.sub(r'<[^>]+>', ' ', html)
    # 转换常见 HTML 实体
    entities = {
        '&nbsp;': ' ', '&lt;': '<', '&gt;': '>', '&amp;': '&',
        '&quot;': '"', '&apos;': "'", '&#160;': ' ',
        '&#10;': '\n', '&#13;': '\n',
    }
    for k, v in entities.items():
        html = html.replace(k, v)
    # 压缩空白
    html = re.sub(r'\s+', ' ', html)
    return html.strip()


def remove_email_noise(text: str) -> str:
    """
    去除邮件中的签名块、转发头、引用线等噪声
    """
    lines = text.split('\n')
    cleaned_lines = []
    in_signature = False
    in_forward_header = False
    
    # 签名块触发词
    signature_markers = [
        r'^\s*[-=_]{2,}\s*$',
        r'^\s*Best regards\s*[,.]?\s*$',
        r'^\s*Regards\s*[,.]?\s*$',
        r'^\s*Thanks\s*[,.]?\s*$',
        r'^\s*谢谢\s*[,.!?]?\s*$',
        r'^\s*此致\s*[,.]?\s*$',
        r'^\s*敬礼\s*[,.]?\s*$',
        r'^\s*顺祝商祺\s*[,.]?\s*$',
        r'^\s*Tel[:\s]',
        r'^\s*Phone[:\s]',
        r'^\s*Mobile[:\s]',
        r'^\s*Email[:\s]',
        r'^\s*地址[:\s]',
        r'^\s*发件人\s*[:：]',
    ]
    
    # 转发头触发词
    forward_markers = [
        r'^\s*[-]+\s*Original Message\s*[-]+',
        r'^\s*[-]+\s*Forwarded Message\s*[-]+',
        r'^\s*发件人\s*[:：]',
        r'^\s*From:\s*',
        r'^\s*To:\s*',
        r'^\s*Cc:\s*',
        r'^\s*Sent:\s*',
        r'^\s*Date:\s*',
        r'^\s*Subject:\s*',
        r'^\s*主题\s*[:：]',
        r'^\s*收件人\s*[:：]',
        r'^\s*抄送\s*[:：]',
        r'^\s*时间\s*[:：]',
    ]
    
    for line in lines:
        # 检测转发头开始
        if any(re.search(p, line, re.I) for p in forward_markers):
            in_forward_header = True
            continue
        
        # 检测签名块开始
        if any(re.search(p, line, re.I) for p in signature_markers):
            in_signature = True
            continue
        
        # 如果当前在签名块中，遇到空行可能结束签名块
        if in_signature and line.strip() == '':
            in_signature = False
            continue
        
        # 如果当前在转发头中，遇到连续空行可能结束
        if in_forward_header and line.strip() == '':
            # 再检查下一行是否还是转发头，这里简化处理：再看到非空行时结束
            pass
        
        if in_forward_header:
            # 转发头通常在一个固定格式后结束，这里简单规则：如果行不太像头信息了，就结束
            if not any(re.search(p, line, re.I) for p in forward_markers) and not re.match(r'^\s*\w+[:\s]', line):
                in_forward_header = False
            else:
                continue
        
        if in_signature:
            continue
        
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    
    # 去除图片引用
    text = re.sub(r'\[IMAGE\d+\]', '', text, flags=re.I)
    text = re.sub(r'\{[^}]*\.png[^}]*\}', '', text, flags=re.I)
    text = re.sub(r'\{[^}]*\.jpg[^}]*\}', '', text, flags=re.I)
    
    # 去除邮箱、电话（保留占位符或移除）
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', text)
    text = re.sub(r'(\+?86[-\s]?)?1[3-9]\d{9}|(\+?86[-\s]?)?\d{3,4}[-\s]?\d{7,8}', '[PHONE]', text)
    
    # 压缩空白
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()


def extract_style_ids(text: str) -> List[str]:
    """从文本中提取所有款号（字母开头）"""
    found = set()
    for name, pattern in STYLE_ID_RE.items():
        for match in pattern.findall(text):
            found.add(match.upper())
    return sorted(list(found))


def extract_order_ids(text: str) -> List[str]:
    """从文本中提取所有订单号（纯数字，6-9位）
    
    注意：会过滤掉常见的年份数字（如 2024, 2025）和明显不是订单号的数字
    """
    found = set()
    for name, pattern in ORDER_ID_RE.items():
        for match in pattern.findall(text):
            # 过滤年份数字
            if match.startswith('20') and len(match) == 4:
                continue
            # 过滤月份日期格式
            if len(match) == 6 and int(match[:2]) <= 12 and int(match[2:4]) <= 31:
                continue
            found.add(match)
    return sorted(list(found))


def classify_email_category(subject: str, content: str) -> str:
    """根据主题和内容对邮件进行分类"""
    text = (subject + " " + content).lower()
    
    categories = {
        # 报价阶段
        "调纸样": ["调纸样", "纸样", "pattern", "pattern making"],
        "核料": ["核料", "fabric booking", "material booking", "consumption"],
        "面辅料价格": ["面辅料价格", "fabric price", "trim price", "quotation", "quote"],
        "工价": ["工价", "cmc", "cut make cost", "factory price", "加工费"],
        # 下订单阶段
        "试身样": ["试身样", "fit sample", "fitting sample", "size set"],
        "修改样": ["修改样", "revised sample", "correction", " amended sample"],
        "封样": ["封样", "sealed sample", "pp sample", "pre-production sample", "top sample"],
        "产前样": ["产前样", "pre-production", "pilot run", "trial production"],
        "测试样": ["测试样", "test sample", "bulk sample", "production sample", "大货样"],
        "船样": ["船样", "shipment sample", "shipping sample", "final sample"],
        "定面料": ["定面料", "fabric order", "fabric po", "面料采购"],
        "定辅料": ["定辅料", "trim order", "accessory order", "辅料采购"],
        # 出货阶段
        "产前会议": ["产前会议", "pre-production meeting", "pp meeting"],
        "开裁": ["开裁", "cutting", "fabric cutting", "laying"],
        "验货": ["验货", "inspection", "qc", "quality check", "查货"],
        "出货": ["出货", "shipment", "delivery", "交期", "shipping", "dispatch"],
        "补货": ["补货", "replenishment", "reorder", "additional order"],
        # 原有/通用
        "Lab Dip": ["labdip", "lab dip", "色卡", "手刮", "颜色确认", "color dip"],
        "样衣": ["样衣", "sample", "prototype", "mock-up"],
        "面料": ["面料", "fabric", "里料", "辅料", "lining", "textile"],
        "大货订单": ["大货订单", "bulk order", "production order", "po"],
    }
    
    scores = {}
    for cat, keywords in categories.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[cat] = score
    
    if scores:
        return max(scores, key=scores.get)
    return "其他"


def parse_email_date(date_str: str) -> Optional[str]:
    """尝试将邮件日期字符串解析为 YYYY-MM-DD"""
    if not date_str:
        return None
    
    # 常见日期格式尝试
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            continue
    
    # 尝试提取纯数字日期 2025/6/9 或 2025-06-09
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', date_str)
    if m:
        y, mth, d = m.groups()
        try:
            return datetime(int(y), int(mth), int(d)).strftime("%Y-%m-%d")
        except:
            pass
    
    return None


# ============ DeepSeek API 事件提取 ============

def get_deepseek_client() -> OpenAI:
    """初始化 DeepSeek API 客户端"""
    api_key = CONFIG["deepseek_api_key"]
    if not api_key:
        raise ValueError("未设置 DEEPSEEK_API_KEY 环境变量")
    return OpenAI(
        api_key=api_key,
        base_url=CONFIG["deepseek_base_url"]
    )


def build_extraction_prompt(email_content: str, style_ids: List[str], order_ids: List[str], 
                                              email_date: str, email_subject: str) -> str:
    """构建 DeepSeek 事件提取 Prompt"""
    
    style_ids_str = ", ".join(style_ids) if style_ids else "未在邮件中明确识别到款号"
    order_ids_str = ", ".join(order_ids) if order_ids else "未识别到订单号"
    
    categories_str = "\n".join([f"- {c}" for c in VALID_CATEGORIES])
    event_types_str = "\n".join([f"- {e}" for e in VALID_EVENT_TYPES])
    
    prompt = f"""你是一个专业的服装行业业务数据提取助手。请从以下邮件内容中提取所有与款号、订单号、时间节点、业务阶段、延期相关的事件。

## 业务流程说明
服装生产分为四大阶段：
1. 开发（本系统不涉及）
2. 报价：调纸样 → 核料 → 面辅料价格 → 工价（可反复）
3. 下订单：试身样 → 修改样 → 封样(仅一次) → 产前样 → 测试样 → 船样(仅一次) → 定面料 → 定辅料（部分可反复）
4. 出货：产前会议 → 开裁 → 验货 → 出货（补货少见）

## 邮件信息
- 主题: {email_subject}
- 日期: {email_date}
- 邮件中识别到的款号: {style_ids_str}
- 邮件中识别到的订单号: {order_ids_str}

## 提取要求
1. 每个事件必须是 **款号/订单号-时间-事件** 的三元组。如果邮件中没有具体时间或事件，不要强行编造。
2. `style_id` 必须从上述款号列表中选择。如果没有明确对应的款号，可以填 "UNKNOWN"。
3. `order_id` 是订单号（纯数字），如有请在对应事件中填写。
4. `category` 必须是以下之一（请根据业务流程判断正确的阶段）：
{categories_str}
5. `event_type` 必须是以下之一：
{event_types_str}
6. `date` 格式必须是 YYYY-MM-DD。如果邮件中日期不明确，请根据邮件发送日期和相对描述（如"本月10号"、"下周三"）尽量推算。
7. `related_date` 是原计划日期或对比日期（如有）。
8. `delay_days` 是延期天数。如果实际比计划晚了 3 天，填 `3`；提前了填负数；没有延期填 `0` 或不填。
9. `party_from` 和 `party_to` 是事件参与方，如 "工厂"、"客人"、"供应商"。如果不明确可以填 "未知"。
10. `confidence` 是你对这个事件提取准确性的置信度，0.0~1.0。如果信息模糊，请给低分。

## 输出格式
必须输出 **纯 JSON 数组**，不要包含任何解释文字或 Markdown 代码块。格式如下：

[
  {{
    "style_id": "INDOT27551",
    "order_id": "",
    "category": "Lab Dip",
    "event_type": "确认",
    "date": "2025-05-15",
    "related_date": "2025-05-12",
    "delay_days": 3,
    "party_from": "客人",
    "party_to": "工厂",
    "description": "款号 INDOT27551 的 Lab Dip 于 5/15 获得客人确认，比原计划 5/12 晚了 3 天",
    "confidence": 0.92
  }}
]

如果邮件中没有可提取的事件，请输出空数组：[]

## 邮件正文
{email_content}
"""
    return prompt


def extract_events_with_deepseek(client: OpenAI, email_content: str, style_ids: List[str], 
                                  order_ids: List[str], email_date: str, email_subject: str) -> Tuple[List[Dict], str, float]:
    """
    调用 DeepSeek API 提取事件
    返回: (events_list, raw_response, cost_seconds)
    """
    prompt = build_extraction_prompt(email_content, style_ids, order_ids, email_date, email_subject)
    
    for attempt in range(CONFIG["max_retries"]):
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=CONFIG["deepseek_model"],
                messages=[
                    {"role": "system", "content": "你是一个专业的服装行业业务数据提取助手。请只输出 JSON 数组，不要有任何额外说明。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=CONFIG["request_timeout"],
            )
            elapsed = time.time() - start
            
            raw_content = response.choices[0].message.content.strip()
            
            # 解析 JSON
            try:
                parsed = json.loads(raw_content)
                # DeepSeek 可能直接返回数组，也可能包在 {"events": [...]} 里
                if isinstance(parsed, list):
                    events = parsed
                elif isinstance(parsed, dict):
                    # 尝试找到数组
                    events = None
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            events = v
                            break
                    if events is None:
                        events = []
                else:
                    events = []
            except json.JSONDecodeError:
                events = []
                raw_content = raw_content
            
            # 数据校验和清洗
            cleaned_events = []
            for evt in events:
                if not isinstance(evt, dict):
                    continue
                
                # 强制字段校验
                style_id = str(evt.get("style_id", "")).strip().upper()
                order_id = str(evt.get("order_id", "")).strip()
                category = str(evt.get("category", "")).strip()
                event_type = str(evt.get("event_type", "")).strip()
                
                # 款号修正：如果 style_id 是 UNKNOWN 或空，但有明确的邮件款号，尝试关联
                if style_id in ("", "UNKNOWN", "NONE") and len(style_ids) == 1:
                    style_id = style_ids[0]
                
                # 订单号修正：如果 order_id 为空，但有明确的邮件订单号，尝试关联
                if not order_id and len(order_ids) == 1:
                    order_id = order_ids[0]
                
                # category 和 event_type 规范化
                if category not in VALID_CATEGORIES:
                    # 尝试模糊匹配
                    for vc in VALID_CATEGORIES:
                        if category.lower() in vc.lower() or vc.lower() in category.lower():
                            category = vc
                            break
                    else:
                        category = "其他"
                
                if event_type not in VALID_EVENT_TYPES:
                    for ve in VALID_EVENT_TYPES:
                        if event_type.lower() in ve.lower() or ve.lower() in event_type.lower():
                            event_type = ve
                            break
                    else:
                        event_type = "其他"
                
                # 日期校验
                date_val = str(evt.get("date", "")).strip()
                if date_val and not re.match(r'^\d{4}-\d{2}-\d{2}$', date_val):
                    date_val = ""  # 格式不对则清空
                
                related_date = str(evt.get("related_date", "")).strip()
                if related_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', related_date):
                    related_date = ""
                
                # delay_days 校验
                delay_days = evt.get("delay_days")
                try:
                    delay_days = int(delay_days) if delay_days is not None else None
                except:
                    delay_days = None
                
                # confidence 校验
                conf = evt.get("confidence", 0.5)
                try:
                    conf = float(conf)
                    conf = max(0.0, min(1.0, conf))
                except:
                    conf = 0.5
                
                cleaned_events.append({
                    "style_id": style_id,
                    "order_id": order_id,
                    "category": category,
                    "event_type": event_type,
                    "date": date_val,
                    "related_date": related_date,
                    "delay_days": delay_days,
                    "party_from": str(evt.get("party_from", "")).strip() or "未知",
                    "party_to": str(evt.get("party_to", "")).strip() or "未知",
                    "description": str(evt.get("description", "")).strip(),
                    "confidence": conf,
                })
            
            return cleaned_events, raw_content, elapsed
            
        except Exception as e:
            if attempt < CONFIG["max_retries"] - 1:
                time.sleep(CONFIG["retry_delay"] * (attempt + 1))
                continue
            else:
                return [], f"API Error: {str(e)}", 0.0


# ============ 批量处理与质量控制 ============

def process_single_email(filepath: str, client: OpenAI) -> Dict[str, Any]:
    """处理单封邮件：清洗 → 提取款号 → LLM提取事件"""
    content, meta = extract_text_from_eml(filepath)
    
    if not content:
        return {
            "filename": meta.get("filename", os.path.basename(filepath)),
            "status": "error",
            "error": meta.get("error", "empty_content"),
            "events": [],
        }
    
    # 清洗
    cleaned_content = remove_email_noise(content)
    if len(cleaned_content) < 50:
        return {
            "filename": meta.get("filename"),
            "status": "skipped",
            "reason": "content_too_short_after_cleaning",
            "events": [],
        }
    
    # 提取款号（字母开头）
    style_ids = extract_style_ids(cleaned_content)
    style_ids_in_subject = extract_style_ids(meta.get("subject", ""))
    style_ids = sorted(list(set(style_ids + style_ids_in_subject)))
    
    # 提取订单号（纯数字）
    order_ids = extract_order_ids(cleaned_content)
    order_ids_in_subject = extract_order_ids(meta.get("subject", ""))
    order_ids = sorted(list(set(order_ids + order_ids_in_subject)))
    
    # 解析日期
    email_date = parse_email_date(meta.get("date", "")) or ""
    
    # 调用 DeepSeek
    events, raw_response, elapsed = extract_events_with_deepseek(
        client, cleaned_content, style_ids, order_ids, email_date, meta.get("subject", "")
    )
    
    return {
        "filename": meta.get("filename"),
        "status": "success",
        "style_ids": style_ids,
        "order_ids": order_ids,
        "subject": meta.get("subject", ""),
        "email_date": email_date,
        "events_count": len(events),
        "events": events,
        "api_response": raw_response,
        "api_time": elapsed,
    }


def batch_process_emails(eml_files: List[str], client: OpenAI, output_path: str, resume_path: Optional[str] = None):
    """批量处理邮件，支持断点恢复"""
    
    # 加载已处理记录
    processed = set()
    if resume_path and os.path.exists(resume_path):
        with open(resume_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    processed.add(rec["filename"])
                except:
                    pass
        print(f"[RESUME] 已加载 {len(processed)} 条处理记录")
    
    files_to_process = [f for f in eml_files if os.path.basename(f) not in processed]
    print(f"[INFO] 总邮件数: {len(eml_files)}, 待处理: {len(files_to_process)}")
    
    ensure_dir(os.path.dirname(output_path))
    
    stats = Counter()
    
    with open(output_path, 'a', encoding='utf-8') as out_f:
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            future_to_file = {
                executor.submit(process_single_email, fp, client): fp 
                for fp in files_to_process
            }
            
            for future in tqdm(as_completed(future_to_file), total=len(files_to_process), desc="Processing"):
                filepath = future_to_file[future]
                try:
                    result = future.result()
                    out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_f.flush()
                    
                    if result["status"] == "success":
                        stats["success"] += 1
                        stats["events"] += result["events_count"]
                    elif result["status"] == "error":
                        stats["error"] += 1
                    else:
                        stats["skipped"] += 1
                        
                except Exception as e:
                    stats["exception"] += 1
                    filepath = future_to_file[future]
                    print(f"[ERROR] 处理失败 {os.path.basename(filepath)}: {type(e).__name__}: {e}")
                    err_result = {
                        "filename": os.path.basename(filepath),
                        "status": "exception",
                        "error": str(e),
                        "events": [],
                    }
                    out_f.write(json.dumps(err_result, ensure_ascii=False) + "\n")
                    out_f.flush()
    
    print(f"\n[BATCH DONE] 统计: {dict(stats)}")
    return stats


# ============ 质量过滤与去重 ============

def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """基于复合键去重"""
    seen = set()
    unique = []
    for evt in events:
        key = (
            evt.get("style_id", ""),
            evt.get("category", ""),
            evt.get("event_type", ""),
            evt.get("date", ""),
            evt.get("description", "")[:30],  # 前30字作为辅助去重
        )
        if key not in seen:
            seen.add(key)
            unique.append(evt)
    return unique


def split_by_quality(events: List[Dict]) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    按置信度分级
    返回: (passed, review, discarded)
    """
    passed = []
    review = []
    discarded = []
    
    for evt in events:
        conf = evt.get("confidence", 0.0)
        if conf >= CONFIG["confidence_pass"]:
            passed.append(evt)
        elif conf >= CONFIG["confidence_review"]:
            review.append(evt)
        else:
            discarded.append(evt)
    
    return passed, review, discarded


# ============ ChromaDB 写入 ============

def build_event_document(evt: Dict) -> str:
    """将事件结构化为检索文档"""
    parts = []
    if evt.get("style_id"):
        parts.append(f"款号: {evt['style_id']}")
    if evt.get("order_id"):
        parts.append(f"订单号: {evt['order_id']}")
    if evt.get("category"):
        parts.append(f"阶段: {evt['category']}")
    if evt.get("event_type"):
        parts.append(f"事件: {evt['event_type']}")
    if evt.get("date"):
        parts.append(f"日期: {evt['date']}")
    if evt.get("related_date"):
        parts.append(f"计划日期: {evt['related_date']}")
    if evt.get("delay_days") is not None:
        parts.append(f"延期: {evt['delay_days']}天")
    if evt.get("party_from") and evt.get("party_from") != "未知":
        parts.append(f"发起方: {evt['party_from']}")
    if evt.get("party_to") and evt.get("party_to") != "未知":
        parts.append(f"接收方: {evt['party_to']}")
    if evt.get("description"):
        parts.append(f"描述: {evt['description']}")
    return " | ".join(parts)


def build_chroma_collection(events: List[Dict], embedding_model: str, collection_name: str, persist_dir: str):
    """将事件写入 ChromaDB"""
    print(f"\n[INFO] 初始化嵌入模型: {embedding_model}")
    model = get_sentence_transformer(embedding_model)
    
    print(f"[INFO] 连接 ChromaDB: {persist_dir}")
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False)
    )
    
    # 如果 collection 已存在，先删除重建（或选择追加）
    try:
        client.delete_collection(name=collection_name)
        print(f"[INFO] 已删除旧 collection: {collection_name}")
    except:
        pass
    
    collection = client.create_collection(
        name=collection_name,
        metadata={"description": "Email-based garment business events"}
    )
    
    total = len(events)
    batch_size = 100
    print(f"[INFO] 开始写入 {total} 个事件向量...")
    
    for i in tqdm(range(0, total, batch_size), desc="Building Vector DB"):
        batch = events[i:i+batch_size]
        
        ids = []
        documents = []
        metadatas = []
        
        for idx, evt in enumerate(batch):
            entry_id = f"evt_{i+idx}"
            ids.append(entry_id)
            documents.append(build_event_document(evt))
            metadatas.append({
                "style_id": evt.get("style_id", ""),
                "order_id": evt.get("order_id", ""),
                "category": evt.get("category", ""),
                "event_type": evt.get("event_type", ""),
                "date": evt.get("date", ""),
                "related_date": evt.get("related_date", ""),
                "delay_days": evt.get("delay_days") if evt.get("delay_days") is not None else -999,
                "party_from": evt.get("party_from", ""),
                "party_to": evt.get("party_to", ""),
                "confidence": evt.get("confidence", 0.0),
                "source_filename": evt.get("source_filename", ""),
                "source_subject": evt.get("source_subject", ""),
            })
        
        embeddings = model.encode(documents, show_progress_bar=False).tolist()
        
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
    
    print(f"[SUCCESS] 成功写入 {total} 个事件到 collection: {collection_name}")
    return collection


# ============ 主函数 ============

def main():
    parser = argparse.ArgumentParser(description="邮件事件型 RAG 构建流水线")
    parser.add_argument("--sample", type=int, default=0, help="先处理 N 封邮件做测试")
    parser.add_argument("--resume", action="store_true", help="从断点恢复处理")
    parser.add_argument("--skip-extraction", action="store_true", help="跳过 LLM 提取，直接处理已有中间文件")
    parser.add_argument("--skip-rag", action="store_true", help="跳过写入 ChromaDB")
    parser.add_argument("--use-filtered", action="store_true", help="使用 pre_filter_emails.py 生成的过滤清单")
    args = parser.parse_args()
    
    ensure_dir(CONFIG["output_dir"])
    raw_output = os.path.join(CONFIG["output_dir"], "events_raw.jsonl")
    passed_output = os.path.join(CONFIG["output_dir"], "events_passed.json")
    review_output = os.path.join(CONFIG["output_dir"], "events_review.jsonl")
    stats_output = os.path.join(CONFIG["output_dir"], "processing_stats.json")
    
    # 1. 获取邮件列表
    if args.use_filtered:
        manifest_path = os.path.join(CONFIG["output_dir"], "filtered_email_manifest.jsonl")
        if not os.path.exists(manifest_path):
            print(f"[ERROR] 过滤清单不存在: {manifest_path}")
            print("请先运行: python email_rag_pipeline/pre_filter_emails.py")
            raise SystemExit(1)
        eml_files = []
        with open(manifest_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    eml_files.append(rec["filepath"])
                except:
                    pass
        print(f"[FILTERED MODE] 从清单加载 {len(eml_files)} 封邮件")
    else:
        eml_files = sorted([
            os.path.join(CONFIG["eml_dir"], f) 
            for f in os.listdir(CONFIG["eml_dir"]) 
            if f.endswith('.eml')
        ])
    
    if args.sample > 0:
        eml_files = eml_files[:args.sample]
        print(f"[SAMPLE MODE] 仅处理前 {args.sample} 封邮件")
    else:
        print(f"[FULL MODE] 共 {len(eml_files)} 封邮件待处理")
    
    # 2. LLM 事件提取
    if not args.skip_extraction:
        print("\n[STEP 1/3] 开始清洗邮件并调用 DeepSeek API 提取事件...")
        client = get_deepseek_client()
        batch_process_emails(eml_files, client, raw_output, raw_output if args.resume else None)
    else:
        print("\n[STEP 1/3] 跳过提取，使用已有中间文件")
    
    # 3. 读取中间结果，进行质量过滤和去重
    print("\n[STEP 2/3] 质量过滤与去重...")
    all_events = []
    file_stats = Counter()
    
    if os.path.exists(raw_output):
        with open(raw_output, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    file_stats[rec.get("status", "unknown")] += 1
                    if rec.get("status") == "success" and rec.get("events"):
                        # 为每个事件添加来源信息
                        for evt in rec["events"]:
                            evt["source_filename"] = rec.get("filename", "")
                            evt["source_subject"] = rec.get("subject", "")
                        all_events.extend(rec["events"])
                except:
                    pass
    
    print(f"  原始事件总数: {len(all_events)}")
    
    # 去重
    all_events = deduplicate_events(all_events)
    print(f"  去重后事件数: {len(all_events)}")
    
    # 分级
    passed, review, discarded = split_by_quality(all_events)
    
    print(f"  高置信度通过: {len(passed)} (>= {CONFIG['confidence_pass']})")
    print(f"  待人工复核: {len(review)} ({CONFIG['confidence_review']} ~ {CONFIG['confidence_pass']})")
    print(f"  低置信度丢弃: {len(discarded)} (< {CONFIG['confidence_review']})")
    
    # 保存
    with open(passed_output, 'w', encoding='utf-8') as f:
        json.dump(passed, f, ensure_ascii=False, indent=2)
    
    with open(review_output, 'w', encoding='utf-8') as f:
        for evt in review:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    
    # 保存统计
    final_stats = {
        "timestamp": datetime.now().isoformat(),
        "total_emails": len(eml_files),
        "file_status": dict(file_stats),
        "total_events": len(all_events),
        "passed_events": len(passed),
        "review_events": len(review),
        "discarded_events": len(discarded),
        "unique_style_ids": len(set(e.get("style_id", "") for e in passed if e.get("style_id"))),
        "category_distribution": dict(Counter(e.get("category", "其他") for e in passed)),
    }
    with open(stats_output, 'w', encoding='utf-8') as f:
        json.dump(final_stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n  已保存:")
    print(f"    通过事件: {passed_output}")
    print(f"    待复核事件: {review_output}")
    print(f"    统计报告: {stats_output}")
    
    # 4. 写入 ChromaDB
    if not args.skip_rag and passed:
        print("\n[STEP 3/3] 构建邮件事件 RAG 向量库...")
        build_chroma_collection(
            passed,
            CONFIG["embedding_model"],
            CONFIG["collection_name"],
            CONFIG["persist_dir"]
        )
    else:
        if args.skip_rag:
            print("\n[STEP 3/3] 跳过 RAG 构建")
        else:
            print("\n[STEP 3/3] 无通过事件，跳过 RAG 构建")
    
    print("\n" + "="*60)
    print("流水线执行完成！")
    print(f"通过事件数: {len(passed)} | 待复核: {len(review)} | 丢弃: {len(discarded)}")
    print("="*60)


if __name__ == "__main__":
    main()
