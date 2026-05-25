#!/usr/bin/env python3
"""
RAG问答系统
结合检索和生成，回答服装术语相关问题

使用方法:
  python email_term_rag_pipeline/src/rag_qa.py
"""

import os
import sys
import json
from typing import List, Dict

# macOS OpenMP 兼容修复
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

try:
    import chromadb
    from chromadb.config import Settings
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip install chromadb")
    raise SystemExit(1)


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


class ClothingKnowledgeBase:
    """服装术语知识库（直接操作 ChromaDB）"""
    
    def __init__(self, collection_name: str = "clothing_terms", 
                 persist_dir: str = "vector_db",
                 embedding_model: str = "BAAI/bge-large-zh-v1.5"):
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_collection(name=collection_name)
        self.model = get_sentence_transformer(embedding_model)
        print(f"知识库初始化完成，包含 {self.collection.count()} 条术语")
    
    def get_stats(self) -> Dict:
        return {"total_entries": self.collection.count()}
    
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义检索"""
        emb = self.model.encode(query).tolist()
        results = self.collection.query(
            query_embeddings=[emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        
        out = []
        for i in range(len(results['ids'][0])):
            out.append({
                "id": results['ids'][0][i],
                "document": results['documents'][0][i],
                "metadata": results['metadatas'][0][i],
                "score": 1 - results['distances'][0][i]
            })
        return out


class ClothingRAG:
    """服装术语RAG问答系统"""
    
    def __init__(self, kb: ClothingKnowledgeBase = None):
        """初始化RAG系统"""
        if kb is None:
            self.kb = ClothingKnowledgeBase()
        else:
            self.kb = kb
        
        print(f"RAG系统初始化完成，知识库包含 {self.kb.get_stats()['total_entries']} 条术语")
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        检索相关术语
        
        Args:
            query: 查询文本
            top_k: 返回数量
            
        Returns:
            相关术语列表
        """
        return self.kb.search(query, top_k=top_k)
    
    def answer(self, query: str, top_k: int = 5) -> Dict:
        """
        回答查询
        
        Args:
            query: 用户问题
            top_k: 检索数量
            
        Returns:
            包含答案和来源的字典
        """
        # 检索相关术语
        results = self.retrieve(query, top_k=top_k)
        
        # 构建回答
        sources = []
        
        if not results:
            answer = "抱歉，在知识库中没有找到相关信息。"
        else:
            # 根据查询类型构建回答
            query_lower = query.lower()
            
            # 判断查询意图
            if any(w in query_lower for w in ['翻译', '英文', 'english', '怎么']):
                answer = self._build_translation_answer(query, results)
            elif any(w in query_lower for w in ['解释', '什么是', 'meaning', '是什么']):
                answer = self._build_explanation_answer(query, results)
            else:
                answer = self._build_general_answer(query, results)
            
            # 记录来源
            for r in results:
                sources.append({
                    "chinese": r['metadata']['chinese'],
                    "english": r['metadata']['english'],
                    "category": r['metadata']['category'],
                    "score": r['score']
                })
        
        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "total_found": len(results)
        }
    
    def _build_translation_answer(self, query: str, results: List[Dict]) -> str:
        """构建翻译类回答"""
        if not results:
            return "未找到对应的翻译。"
        
        top = results[0]['metadata']
        
        # 判断是中译英还是英译中
        if any('\u4e00' <= c <= '\u9fff' for c in query):
            # 中译英
            answer = f"\"{top['chinese']}\" 的英文翻译是：\n"
            answer += f"  {top['english']}\n"
            answer += f"  分类：{top['category']}"
        else:
            # 英译中
            answer = f"\"{top['english']}\" 的中文翻译是：\n"
            answer += f"  {top['chinese']}\n"
            answer += f"  分类：{top['category']}"
        
        # 添加其他可能的结果
        if len(results) > 1:
            answer += "\n\n其他相关术语："
            for r in results[1:3]:
                meta = r['metadata']
                answer += f"\n- {meta['chinese']} | {meta['english']}"
        
        return answer
    
    def _build_explanation_answer(self, query: str, results: List[Dict]) -> str:
        """构建解释类回答"""
        if not results:
            return "未找到相关术语的解释。"
        
        top = results[0]['metadata']
        
        answer = f"关于 \"{top['chinese']}\" ({top['english']}):\n\n"
        answer += f"分类：{top['category']}\n"
        answer += f"中英对照：{top['chinese']} | {top['english']}\n"
        
        # 添加相关术语
        if len(results) > 1:
            answer += "\n相关术语："
            for r in results[1:4]:
                meta = r['metadata']
                answer += f"\n- {meta['chinese']} ({meta['english']})"
        
        return answer
    
    def _build_general_answer(self, query: str, results: List[Dict]) -> str:
        """构建通用回答"""
        if not results:
            return "未找到相关信息。"
        
        answer = f"为您找到以下相关术语：\n\n"
        
        for i, r in enumerate(results[:5], 1):
            meta = r['metadata']
            answer += f"{i}. {meta['chinese']}\n"
            answer += f"   英文: {meta['english']}\n"
            answer += f"   分类: {meta['category']}\n\n"
        
        return answer.strip()
    
    def batch_translate(self, terms: List[str], direction: str = "zh2en") -> List[Dict]:
        """
        批量翻译术语
        
        Args:
            terms: 术语列表
            direction: 翻译方向 zh2en/en2zh
            
        Returns:
            翻译结果列表
        """
        results = []
        for term in terms:
            search_results = self.retrieve(term, top_k=1)
            if search_results:
                meta = search_results[0]['metadata']
                results.append({
                    "source": term,
                    "translation": meta['english'] if direction == "zh2en" else meta['chinese'],
                    "category": meta['category'],
                    "confidence": search_results[0]['score']
                })
            else:
                results.append({
                    "source": term,
                    "translation": "未找到",
                    "confidence": 0
                })
        return results
    
    def interactive_mode(self):
        """交互式问答模式"""
        print("\n" + "="*60)
        print("服装术语RAG问答系统")
        print("输入 'quit' 或 'exit' 退出")
        print("="*60 + "\n")
        
        while True:
            query = input("您的问题: ").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                print("再见!")
                break
            
            if not query:
                continue
            
            result = self.answer(query)
            
            print(f"\n回答:\n{result['answer']}\n")
            print(f"(基于知识库中 {result['total_found']} 条相关术语)")
            print("-" * 40)


def main():
    """主函数"""
    # 初始化RAG系统
    rag = ClothingRAG()
    
    # 运行交互模式
    rag.interactive_mode()


if __name__ == "__main__":
    main()
