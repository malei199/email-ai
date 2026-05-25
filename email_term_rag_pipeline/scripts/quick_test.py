#!/usr/bin/env python3
"""
快速测试RAG系统
无需下载模型，仅测试PDF提取
"""

import sys
import os

# 测试PDF提取
def test_extraction():
    print("="*60)
    print("测试PDF提取")
    print("="*60)
    
    pdf_path = "data/pdf/汉英英汉服装分类词汇.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF文件不存在: {pdf_path}")
        return False
    
    try:
        import pdfplumber
        
        with pdfplumber.open(pdf_path) as pdf:
            print(f"✓ PDF总页数: {len(pdf.pages)}")
            
            # 测试提取第一页
            page = pdf.pages[2]  # 跳过封面
            text = page.extract_text()
            
            if text:
                print(f"✓ 文本提取成功")
                print(f"  首行: {text.split(chr(10))[0][:50]}...")
                return True
            else:
                print("❌ 文本提取失败")
                return False
                
    except ImportError:
        print("❌ 未安装pdfplumber，请运行: pip install pdfplumber")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


# 测试数据结构
def test_data_structure():
    print("\n" + "="*60)
    print("测试数据文件")
    print("="*60)
    
    json_path = "email_term_rag_pipeline/output/filtered_terms.json"
    
    if not os.path.exists(json_path):
        print(f"⚠️ 数据文件不存在: {json_path}")
        print("  请先运行: python email_term_rag_pipeline/src/extract_pdf_terms.py")
        return False
    
    try:
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"✓ 数据文件加载成功")
        print(f"  条目数: {len(data)}")
        
        if data:
            sample = data[0]
            print(f"  示例: {sample.get('chinese')} | {sample.get('english')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


# 测试向量数据库
def test_vector_db():
    print("\n" + "="*60)
    print("测试向量数据库")
    print("="*60)
    
    index_path = "vector_db"
    
    if not os.path.exists(index_path) or not os.listdir(index_path):
        print(f"⚠️ 向量数据库未创建")
        print("  请先运行: python email_term_rag_pipeline/src/build_term_kb.py")
        return False
    
    try:
        import chromadb
        
        client = chromadb.PersistentClient(path=index_path)
        collection = client.get_collection("clothing_terms")
        count = collection.count()
        
        print(f"✓ 向量数据库加载成功")
        print(f"  条目数: {count}")
        
        return True
        
    except ImportError:
        print("❌ 未安装chromadb，请运行: pip install chromadb")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def main():
    print("RAG系统快速测试\n")
    
    results = []
    
    # 测试1: PDF提取
    results.append(("PDF提取", test_extraction()))
    
    # 测试2: 数据结构
    results.append(("数据结构", test_data_structure()))
    
    # 测试3: 向量数据库
    results.append(("向量数据库", test_vector_db()))
    
    # 汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✓ 所有测试通过！可以运行RAG系统")
        print("  命令: python email_term_rag_pipeline/src/rag_qa.py")
    else:
        print("\n⚠️ 部分测试未通过，请根据提示修复")


if __name__ == "__main__":
    main()
