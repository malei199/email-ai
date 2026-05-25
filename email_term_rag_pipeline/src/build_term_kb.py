#!/usr/bin/env python3
"""
服装术语 RAG 知识库构建脚本
与 email_rag_pipeline 风格对齐：
  - 延迟导入 SentenceTransformer（兼容 PyTorch 2.2.2）
  - 覆盖重建 ChromaDB collection
  - 输出统计报告
"""

import os
import json
import argparse
from typing import List, Dict
from collections import Counter

# macOS OpenMP 兼容修复
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

try:
    import chromadb
    from chromadb.config import Settings
    from tqdm import tqdm
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip install chromadb tqdm")
    raise SystemExit(1)


# ============ 配置 ============
CONFIG = {
    "input_json": "email_term_rag_pipeline/output/filtered_terms.json",
    "fallback_json": "email_term_rag_pipeline/data/clothing_dictionary.json",
    "collection_name": "clothing_terms",
    "embedding_model": "BAAI/bge-large-zh-v1.5",
    "persist_dir": "vector_db",
    "output_dir": "email_term_rag_pipeline/output",
    "batch_size": 100,
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
            print("请运行: pip install 'transformers<4.40' 'sentence-transformers<2.8'")
            raise SystemExit(1)
    return SentenceTransformer(model_name)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def build_document(entry: Dict) -> str:
    """构建检索文档"""
    parts = []
    if entry.get('chinese'):
        parts.append(f"CN: {entry['chinese']}")
    if entry.get('english'):
        parts.append(f"EN: {entry['english']}")
    if entry.get('category'):
        parts.append(f"CAT: {entry['category']}")
    return " | ".join(parts)


def build_kb(entries: List[Dict], embedding_model: str, collection_name: str, persist_dir: str):
    """将术语条目写入 ChromaDB"""
    print(f"\n[INFO] 初始化嵌入模型: {embedding_model}")
    model = get_sentence_transformer(embedding_model)
    
    print(f"[INFO] 连接 ChromaDB: {persist_dir}")
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False)
    )
    
    # 如果 collection 已存在，删除重建
    try:
        client.delete_collection(name=collection_name)
        print(f"[INFO] 已删除旧 collection: {collection_name}")
    except Exception:
        pass
    
    collection = client.create_collection(
        name=collection_name,
        metadata={"description": "Clothing terms knowledge base"}
    )
    
    total = len(entries)
    print(f"[INFO] 开始写入 {total} 个术语向量...")
    
    for i in tqdm(range(0, total, CONFIG["batch_size"]), desc="Building Vector DB"):
        batch = entries[i:i+CONFIG["batch_size"]]
        
        ids = []
        documents = []
        metadatas = []
        
        for idx, entry in enumerate(batch):
            entry_id = f"term_{entry.get('page', 0)}_{i+idx}"
            ids.append(entry_id)
            documents.append(build_document(entry))
            metadatas.append({
                "chinese": entry.get('chinese', ''),
                "english": entry.get('english', ''),
                "category": entry.get('category', ''),
                "page": entry.get('page', 0),
                "type": entry.get('type', '')
            })
        
        embeddings = model.encode(documents, show_progress_bar=False).tolist()
        
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
    
    print(f"[SUCCESS] 成功写入 {total} 个术语到 collection: {collection_name}")
    return collection.count()


def main():
    parser = argparse.ArgumentParser(description="服装术语 RAG 建库")
    parser.add_argument("--input", type=str, default=CONFIG["input_json"],
                        help=f"输入术语 JSON 路径（默认: {CONFIG['input_json']}）")
    args = parser.parse_args()
    
    input_path = args.input
    
    # 优先使用指定输入，否则回退到旧数据
    if not os.path.exists(input_path):
        if os.path.exists(CONFIG["fallback_json"]):
            print(f"[WARN] 未找到 {input_path}，回退使用旧数据: {CONFIG['fallback_json']}")
            print("[WARN] 旧数据可能缺少分类信息，建议先运行 extract_pdf_terms.py")
            input_path = CONFIG["fallback_json"]
        else:
            print(f"[ERROR] 未找到输入文件: {input_path}")
            print("请确保已运行: python email_term_rag_pipeline/src/extract_pdf_terms.py")
            raise SystemExit(1)
    
    print(f"[INFO] 加载术语数据: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)
    
    print(f"[INFO] 共加载 {len(entries)} 条术语")
    
    # 基本质量过滤（对旧数据做兜底）
    filtered = [e for e in entries if len(e.get('chinese', '')) >= 2 and len(e.get('english', '')) >= 3]
    if len(filtered) < len(entries):
        print(f"[INFO] 过滤后: {len(filtered)} 条（移除 {len(entries) - len(filtered)} 条过短记录）")
        entries = filtered
    
    if not entries:
        print("[ERROR] 没有有效术语可入库")
        raise SystemExit(1)
    
    # 建库
    total_in_db = build_kb(
        entries,
        CONFIG["embedding_model"],
        CONFIG["collection_name"],
        CONFIG["persist_dir"]
    )
    
    # 生成统计报告
    ensure_dir(CONFIG["output_dir"])
    stats = {
        "collection_name": CONFIG["collection_name"],
        "total_entries": total_in_db,
        "embedding_model": CONFIG["embedding_model"],
        "category_distribution": dict(Counter(e.get("category", "未分类") for e in entries).most_common()),
    }
    stats_path = os.path.join(CONFIG["output_dir"], "term_kb_stats.json")
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n[SUCCESS] 术语知识库构建完成！")
    print(f"  总词条数: {total_in_db}")
    print(f"  统计报告: {stats_path}")
    
    # 快速测试
    print(f"\n[INFO] 执行快速检索测试...")
    model = get_sentence_transformer(CONFIG["embedding_model"])
    client = chromadb.PersistentClient(path=CONFIG["persist_dir"], settings=Settings(anonymized_telemetry=False))
    collection = client.get_collection(CONFIG["collection_name"])
    
    test_queries = ["拉链", "zipper", "暗门襟", "coat"]
    for query in test_queries:
        emb = model.encode(query).tolist()
        results = collection.query(query_embeddings=[emb], n_results=2, include=["documents", "metadatas", "distances"])
        if results['ids'][0]:
            meta = results['metadatas'][0][0]
            score = 1 - results['distances'][0][0]
            print(f"  {query} -> {meta['chinese']} | {meta['english']} ({score:.3f})")
        else:
            print(f"  {query} -> 未找到")


if __name__ == "__main__":
    main()
