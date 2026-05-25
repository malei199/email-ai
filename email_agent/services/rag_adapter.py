"""
RAG适配器
封装术语RAG和邮件事件RAG的查询接口
"""
import sys
import json
from pathlib import Path
from typing import List, Optional, Dict

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# 延迟加载的客户端
_chroma_client = None


def _get_chroma_client():
    """懒加载ChromaDB客户端"""
    global _chroma_client
    if _chroma_client is None:
        try:
            import chromadb
            from chromadb.config import Settings
            from email_agent.config import VECTOR_DB_PATH
            
            _chroma_client = chromadb.PersistentClient(
                path=VECTOR_DB_PATH,
                settings=Settings(anonymized_telemetry=False)
            )
        except Exception as e:
            print(f"[WARN] ChromaDB加载失败: {e}")
    return _chroma_client


# ============ 术语RAG（直接查ChromaDB，绕过ClothingRAG） ============

_clothing_terms_collection = None
_embedding_function = None


def _get_embedding_function():
    """懒加载embedding函数（使用本地缓存的BAAI/bge-large-zh-v1.5）"""
    global _embedding_function
    if _embedding_function is None:
        try:
            import os
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            
            # 使用本地缓存路径
            model_path = "/Users/potato/.cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/snapshots/79e7739b6ab944e86d6171e44d24c997fc1e0116"
            _embedding_function = SentenceTransformerEmbeddingFunction(model_name=model_path)
        except Exception as e:
            print(f"[WARN] Embedding函数加载失败: {e}")
    return _embedding_function


def _get_clothing_terms_collection():
    """懒加载术语RAG collection（直接查ChromaDB）"""
    global _clothing_terms_collection
    if _clothing_terms_collection is None:
        client = _get_chroma_client()
        if client:
            try:
                _clothing_terms_collection = client.get_collection("clothing_terms")
            except Exception as e:
                print(f"[WARN] 术语collection加载失败: {e}")
    return _clothing_terms_collection


def query_terms(query: str, top_k: int = 5) -> List[dict]:
    """
    查询服装术语（直接查ChromaDB，绕过ClothingRAG依赖）
    
    Args:
        query: 查询文本（中文或英文术语）
        top_k: 返回数量
        
    Returns:
        术语列表，每个包含chinese/english/category
    """
    collection = _get_clothing_terms_collection()
    if not collection:
        return []
    
    try:
        # 使用本地embedding函数生成查询向量（绕过ChromaDB默认的384维模型）
        ef = _get_embedding_function()
        if not ef:
            return []
        
        query_embeddings = ef([query])
        results = collection.query(
            query_embeddings=query_embeddings,
            n_results=top_k,
            include=["metadatas", "documents", "distances"]
        )
        
        terms = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 1.0
                terms.append({
                    "chinese": meta.get("chinese", ""),
                    "english": meta.get("english", ""),
                    "category": meta.get("category", ""),
                    "score": 1 - dist,  # 距离转相似度
                })
        return terms
    except Exception as e:
        print(f"[WARN] 术语查询失败: {e}")
        return []


def translate_term(query: str, top_k: int = 3) -> Dict:
    """
    术语翻译：中英文互查
    
    Args:
        query: 查询词（中文或英文）
        top_k: 返回数量
        
    Returns:
        {
            "query": 原始查询,
            "translations": [
                {"chinese": "...", "english": "...", "category": "...", "score": 0.95}
            ],
            "best_match": {"chinese": "...", "english": "..."}
        }
    """
    terms = query_terms(query, top_k=top_k)
    
    if not terms:
        return {"query": query, "translations": [], "best_match": None}
    
    # 找最佳匹配（score最高）
    best = max(terms, key=lambda x: x["score"])
    
    return {
        "query": query,
        "translations": terms,
        "best_match": {
            "chinese": best["chinese"],
            "english": best["english"],
        } if best else None
    }


def enhance_query_with_terms(query_text: str) -> str:
    """
    用术语翻译增强查询文本
    
    例: "invisible zipper 问题" → "invisible zipper 隐形拉链 问题"
    
    Args:
        query_text: 原始查询文本
        
    Returns:
        增强后的查询文本（中英文混合）
    """
    import re
    
    # 提取可能的英文术语（连续字母）
    english_words = re.findall(r'\b[a-zA-Z\s]+\b', query_text)
    
    enhanced = query_text
    for word in english_words:
        word = word.strip()
        if len(word) < 3:  # 跳过短词
            continue
        result = translate_term(word, top_k=1)
        if result["best_match"]:
            chinese = result["best_match"]["chinese"]
            if chinese and chinese not in enhanced:
                # 在英文术语后追加中文
                enhanced = enhanced.replace(word, f"{word} {chinese}")
    
    return enhanced


# ============ 邮件事件RAG ============

# 内存缓存的事件数据（从 JSON 文件加载）
_events_cache = None


def _load_events_from_json() -> list:
    """从 events_passed.json 加载事件数据到内存"""
    global _events_cache
    if _events_cache is not None:
        return _events_cache
    
    try:
        from email_agent.config import KG_EVENTS_PATH
        if KG_EVENTS_PATH.exists():
            with open(KG_EVENTS_PATH, "r", encoding="utf-8") as f:
                _events_cache = json.load(f)
            print(f"[INFO] 已从 JSON 加载 {len(_events_cache)} 条事件")
        else:
            _events_cache = []
    except Exception as e:
        print(f"[WARN] 从 JSON 加载事件失败: {e}")
        _events_cache = []
    
    return _events_cache


def query_email_events(
    style_id: Optional[str] = None,
    style_ids: Optional[List[str]] = None,
    query_text: Optional[str] = None,
    top_k: int = 10,
    include_full_fields: bool = True
) -> List[dict]:
    """
    查询邮件事件（增强版）
    
    支持三种模式：
    1. 单款号精确查询: style_id="CCAW240015"
    2. 多款号范围查询: style_ids=["CCAW240015", "CCAW240016"]
    3. 语义检索: query_text="拉链问题"
    4. 款号+语义联合: style_id="CCAW240015" + query_text="船样"
    
    Args:
        style_id: 单款号过滤
        style_ids: 多款号范围过滤（列表）
        query_text: 语义查询文本
        top_k: 返回数量
        include_full_fields: 是否返回完整字段（source_filename等）
        
    Returns:
        事件列表
            "id",
            "description"
            "style_id"
            "order_id"
            "category"
            "event_type"
            "date"
            "related_date"
            "delay_days"
            "party_from"
            "party_to"
            "confidence"
            "score"
            "source_filename"
            "source_subject"
    """
    # 模式1: 多款号精确查询（走JSON）
    if style_ids and not query_text:
        events = _load_events_from_json()
        style_id_set = set(style_ids)
        filtered = [e for e in events if e.get("style_id") in style_id_set]
        return filtered[:top_k] if top_k else filtered
    
    # 模式2: 单款号精确查询（走JSON）
    if style_id and not query_text:
        events = _load_events_from_json()
        filtered = [e for e in events if e.get("style_id") == style_id]
        return filtered[:top_k] if top_k else filtered
    
    # 模式3&4: 语义检索（走ChromaDB）
    if query_text:
        client = _get_chroma_client()
        if not client:
            return []
        
        try:
            collection = client.get_collection("email_events_new")
            
            # 构建where过滤
            where_filter = None
            if style_ids:
                # 多款号: 用 $in 操作符
                where_filter = {"style_id": {"$in": style_ids}}
            elif style_id:
                # 单款号
                where_filter = {"style_id": style_id}
            
            # 术语增强（如果查询包含英文术语）
            enhanced_query = enhance_query_with_terms(query_text)
            
            # 使用本地embedding函数（1024维，与collection一致）
            ef = _get_embedding_function()
            if not ef:
                return []
            
            query_embeddings = ef([enhanced_query])
            results = collection.query(
                query_embeddings=query_embeddings,
                where=where_filter,
                n_results=top_k,
                include=["metadatas", "documents", "distances"]
            )
            
            events = []
            if results and results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    doc = results["documents"][0][i] if results["documents"] else ""
                    dist = results["distances"][0][i] if results["distances"] else 1.0
                    
                    event = {
                        "id": doc_id,
                        "description": doc,
                        "style_id": meta.get("style_id", ""),
                        "order_id": meta.get("order_id", ""),
                        "category": meta.get("category", ""),
                        "event_type": meta.get("event_type", ""),
                        "date": meta.get("date", ""),
                        "related_date": meta.get("related_date", ""),
                        "delay_days": meta.get("delay_days", 0),
                        "party_from": meta.get("party_from", ""),
                        "party_to": meta.get("party_to", ""),
                        "confidence": meta.get("confidence", 0),
                        "score": 1 - dist,
                    }
                    
                    # 完整字段模式追加 source 信息
                    if include_full_fields:
                        event["source_filename"] = meta.get("source_filename", "")
                        event["source_subject"] = meta.get("source_subject", "")
                    
                    events.append(event)
            return events
        except Exception as e:
            print(f"[WARN] ChromaDB 语义检索失败: {e}")
            return []
    
    return []


def query_email_events_by_date(
    style_id: Optional[str] = None,
    style_ids: Optional[List[str]] = None,
    days: int = 7
) -> List[dict]:
    """
    查询最近N天的事件（支持多款号）
    
    Args:
        style_id: 单款号
        style_ids: 多款号列表
        days: 最近N天
        
    Returns:
        事件列表（按日期降序）
            "id",
            "description"
            "style_id"
            "order_id"
            "category"
            "event_type"
            "date"
            "related_date"
            "delay_days"
            "party_from"
            "party_to"
            "confidence"
            "score"
            "source_filename"
            "source_subject"
    """
    try:
        events = _load_events_from_json()
        
        # 确定款号过滤集合
        target_styles = None
        if style_ids:
            target_styles = set(style_ids)
        elif style_id:
            target_styles = {style_id}
        
        # 过滤款号和日期
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        
        filtered = []
        for e in events:
            # 款号过滤
            if target_styles and e.get("style_id") not in target_styles:
                continue
            
            # 日期过滤
            event_date = e.get("date", "")
            if event_date:
                try:
                    ed = datetime.strptime(event_date, "%Y-%m-%d")
                    if ed >= cutoff:
                        filtered.append(e)
                except ValueError:
                    continue
        
        return sorted(filtered, key=lambda x: x.get("date", ""), reverse=True)
    except Exception as e:
        print(f"[WARN] 日期过滤查询失败: {e}")
        return []


def query_email_events_by_conditions(
    style_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    event_types: Optional[List[str]] = None,
    min_delay_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_k: int = 100
) -> List[dict]:
    """
    多条件组合查询事件（基于JSON数据，ChromaDB where不支持复杂条件）
    
    Args:
        style_ids: 款号范围
        categories: 业务阶段列表
        event_types: 事件类型列表
        min_delay_days: 最小延期天数
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        top_k: 返回数量限制
        
    Returns:
        符合条件的事件列表
            "id",
            "description"
            "style_id"
            "order_id"
            "category"
            "event_type"
            "date"
            "related_date"
            "delay_days"
            "party_from"
            "party_to"
            "confidence"
            "score"
            "source_filename"
            "source_subject"
    """
    events = _load_events_from_json()
    filtered = []
    
    for e in events:
        # 款号过滤
        if style_ids and e.get("style_id") not in style_ids:
            continue
        
        # 阶段过滤
        if categories and e.get("category") not in categories:
            continue
        
        # 事件类型过滤
        if event_types and e.get("event_type") not in event_types:
            continue
        
        # 延期过滤
        if min_delay_days is not None:
            delay = e.get("delay_days") or 0
            if delay < min_delay_days:
                continue
        
        # 日期范围过滤
        event_date = e.get("date", "")
        if start_date and event_date < start_date:
            continue
        if end_date and event_date > end_date:
            continue
        
        filtered.append(e)
    
    # 按日期降序，限制数量
    filtered.sort(key=lambda x: x.get("date", ""), reverse=True)
    return filtered[:top_k] if top_k else filtered
