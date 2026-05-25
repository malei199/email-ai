#!/usr/bin/env python3
"""
邮件事件型 RAG 端到端检索测试脚本
功能：按款号检索事件 -> 时间线聚合 -> DeepSeek 生成结构化表格和根因分析

使用方法：
  export DEEPSEEK_API_KEY="your-api-key"
  python email_rag_pipeline/test_timeline_rag.py INDOT27551
  python email_rag_pipeline/test_timeline_rag.py AW25-KFWTS101 --top-k 20
"""

import os
import re
import sys
import json
import argparse
from typing import List, Dict
from collections import defaultdict
from datetime import datetime

# macOS OpenMP 兼容修复
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

try:
    import chromadb
    from chromadb.config import Settings
    from openai import OpenAI
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip install chromadb openai")
    raise SystemExit(1)


# ============ 配置 ============
CONFIG = {
    "collection_name": "email_events_new",
    "persist_dir": "vector_db",
    "embedding_model": "BAAI/bge-large-zh-v1.5",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com",
    #"deepseek_api_key": os.environ.get("DEEPSEEK_API_KEY"),
    "deepseek_api_key": 'sk-c056cef347f84bef95c4601c88ffc1f8',
}

# 延迟导入的 embedding 模型
SentenceTransformer = None

def get_sentence_transformer(model_name: str):
    global SentenceTransformer
    if SentenceTransformer is None:
        try:
            from sentence_transformers import SentenceTransformer as ST
            SentenceTransformer = ST
        except ImportError as e:
            print(f"[ERROR] 无法导入 sentence_transformers: {e}")
            raise SystemExit(1)
    return SentenceTransformer(model_name)


def get_chroma_collection(collection_name: str, persist_dir: str):
    """连接 ChromaDB 并返回 collection"""
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False)
    )
    return client.get_collection(name=collection_name)


def get_deepseek_client() -> OpenAI:
    """初始化 DeepSeek API 客户端"""
    api_key = CONFIG["deepseek_api_key"]
    if not api_key:
        raise ValueError("未设置 DEEPSEEK_API_KEY 环境变量")
    return OpenAI(api_key=api_key, base_url=CONFIG["deepseek_base_url"])


def retrieve_events_by_style_id(style_id: str, collection, top_k: int = 50) -> List[Dict]:
    """
    两阶段检索第一阶段：按 style_id 元数据精确过滤召回
    """
    try:
        results = collection.get(
            where={"style_id": style_id.upper()},
            include=["documents", "metadatas"]
        )
    except Exception as e:
        print(f"[ERROR] 检索失败: {e}")
        return []
    
    events = []
    if results and results.get("ids"):
        for doc, meta in zip(results["documents"], results["metadatas"]):
            events.append({
                "document": doc,
                "metadata": meta,
            })
    
    return events


def retrieve_events_by_vector(query: str, style_id: str, collection, top_k: int = 50) -> List[Dict]:
    """
    两阶段检索第二阶段（备选）：如果 style_id 过滤召回为空，尝试向量语义检索
    """
    model = get_sentence_transformer(CONFIG["embedding_model"])
    query_emb = model.encode(query).tolist()
    
    results = collection.query(
        query_embeddings=[query_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    
    events = []
    if results and results.get("ids") and len(results["ids"][0]) > 0:
        for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
            # 只保留匹配到该 style_id 或高置信度的结果
            if meta.get("style_id", "").upper() == style_id.upper() or (1 - dist) > 0.75:
                events.append({
                    "document": doc,
                    "metadata": meta,
                    "score": 1 - dist,
                })
    
    return events


def aggregate_timeline(events: List[Dict]) -> Dict[str, List[Dict]]:
    """
    按 category 聚合，并按 date 排序
    """
    def parse_date(d):
        if not d:
            return datetime.min
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except:
            return datetime.min
    
    # 按 category 分组
    groups = defaultdict(list)
    for evt in events:
        meta = evt.get("metadata", {})
        cat = meta.get("category", "其他")
        groups[cat].append({
            "category": cat,
            "event_type": meta.get("event_type", "其他"),
            "date": meta.get("date", ""),
            "related_date": meta.get("related_date", ""),
            "delay_days": meta.get("delay_days"),
            "party_from": meta.get("party_from", "未知"),
            "party_to": meta.get("party_to", "未知"),
            "description": meta.get("description", evt.get("document", "")),
            "confidence": meta.get("confidence", 0.0),
        })
    
    # 每个 category 内按 date 排序
    for cat in groups:
        groups[cat].sort(key=lambda x: parse_date(x["date"]))
    
    return dict(groups)


def build_analysis_prompt(style_id: str, timeline: Dict[str, List[Dict]]) -> str:
    """构建 DeepSeek 分析 Prompt"""
    
    event_lines = []
    for cat in sorted(timeline.keys()):
        event_lines.append(f"\n【{cat}】")
        for evt in timeline[cat]:
            delay_info = f"，延期 {evt['delay_days']} 天" if evt.get('delay_days') is not None and evt['delay_days'] != 0 else ""
            related = f"，原计划 {evt['related_date']}" if evt.get('related_date') else ""
            event_lines.append(
                f"- {evt['event_type']} | 实际: {evt['date']}{related}{delay_info} | "
                f"{evt['party_from']} → {evt['party_to']} | {evt['description']}"
            )
    
    events_text = "\n".join(event_lines)
    
    prompt = f"""你是一个专业的服装行业业务分析师。请根据以下款号的邮件事件记录，整理成结构化的时间线表格，并分析延期根因。

## 款号
{style_id}

## 事件记录
{events_text}

## 输出要求
1. 使用 Markdown 表格输出
2. 必须包含"面料部分"和"样衣部分"两大块（如果某块无数据，表格中标注"未找到记录"）
3. 如果有延期，在"延期"列中标注天数
4. 最后给出"根因结论"：指出最关键的时间延误点及影响
5. 如果某阶段完全没有记录，请明确说明，不要编造
"""
    return prompt


def generate_analysis(client: OpenAI, style_id: str, timeline: Dict[str, List[Dict]]) -> str:
    """调用 DeepSeek API 生成分析"""
    prompt = build_analysis_prompt(style_id, timeline)
    
    try:
        response = client.chat.completions.create(
            model=CONFIG["deepseek_model"],
            messages=[
                {"role": "system", "content": "你是服装行业业务分析师。请基于给定的事件记录整理时间线表格并分析延期根因。不要编造未提供的信息。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            timeout=60,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[ERROR] DeepSeek API 调用失败: {e}"


def print_raw_timeline(timeline: Dict[str, List[Dict]]):
    """打印原始时间线（不调用 LLM）"""
    print("\n" + "=" * 60)
    print("原始时间线聚合")
    print("=" * 60)
    
    for cat in sorted(timeline.keys()):
        print(f"\n【{cat}】")
        for evt in timeline[cat]:
            delay = f" [延期 {evt['delay_days']} 天]" if evt.get('delay_days') is not None and evt['delay_days'] != 0 else ""
            related = f" (原计划 {evt['related_date']})" if evt.get('related_date') else ""
            print(f"  {evt['date']}{related} | {evt['event_type']}{delay} | {evt['party_from']} → {evt['party_to']}")
            print(f"    {evt['description']}")


def main():
    parser = argparse.ArgumentParser(description="邮件事件型 RAG 端到端检索测试")
    parser.add_argument("style_id", help="要查询的款号，如 INDOT27551 或 AW25-KFWTS101")
    parser.add_argument("--top-k", type=int, default=50, help="最大召回事件数")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分析，只打印原始时间线")
    args = parser.parse_args()
    
    style_id = args.style_id.upper()
    
    print(f"[INFO] 正在检索款号: {style_id}")
    
    # 1. 连接 ChromaDB
    try:
        collection = get_chroma_collection(CONFIG["collection_name"], CONFIG["persist_dir"])
        print(f"[INFO] 连接知识库成功: {CONFIG['collection_name']}")
    except Exception as e:
        print(f"[ERROR] 无法连接知识库: {e}")
        print("请确保已经运行过邮件事件入库脚本: python email_rag_pipeline/build_email_event_rag.py")
        raise SystemExit(1)
    
    # 2. 检索事件
    events = retrieve_events_by_style_id(style_id, collection, args.top_k)
    
    if not events:
        print(f"[WARN] 按 style_id 精确过滤未找到记录，尝试向量语义检索...")
        events = retrieve_events_by_vector(f"{style_id} 延期 出货", style_id, collection, args.top_k)
    
    if not events:
        print(f"[WARN] 未找到款号 {style_id} 的任何邮件事件记录")
        raise SystemExit(0)
    
    print(f"[INFO] 共检索到 {len(events)} 个事件")
    
    # 3. 聚合时间线
    timeline = aggregate_timeline(events)
    print(f"[INFO] 涉及业务阶段: {', '.join(sorted(timeline.keys()))}")
    
    # 4. 打印原始时间线
    print_raw_timeline(timeline)
    
    # 5. LLM 生成分析
    if not args.skip_llm:
        print("\n" + "=" * 60)
        print("LLM 结构化分析")
        print("=" * 60)
        
        try:
            client = get_deepseek_client()
            analysis = generate_analysis(client, style_id, timeline)
            print(analysis)
        except ValueError as e:
            print(f"[ERROR] {e}")
            print("如只需查看原始时间线，请添加 --skip-llm 参数")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
