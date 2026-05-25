#!/usr/bin/env python3
"""
RAG知识库与业务邮件系统集成
在邮件处理中自动识别和翻译专业术语
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from email_finetuning_pipeline.src.eml_data_processor import extract_text_from_eml
from email_term_rag_pipeline.src.rag_qa import ClothingRAG

# 注意：本文件已从 email_term_rag_pipeline/src/integrate_with_email.py 迁移到
# email_rag_pipeline/src/term_rag_integration.py
# 它是邮件系统调用术语 RAG 的集成接口，属于邮件流水线的一部分。
import re


class EmailTerminologyAssistant:
    """邮件术语助手"""
    
    def __init__(self):
        self.rag = ClothingRAG()
        print("邮件术语助手初始化完成")
    
    def extract_potential_terms(self, text: str) -> list:
        """
        从文本中提取可能的服装专业术语
        
        策略:
        1. 提取中英文词汇
        2. 提取大写字母缩写
        3. 提取引号内的词汇
        """
        terms = set()
        
        # 中文术语（2-10个字符）
        chinese_terms = re.findall(r'[\u4e00-\u9fa5]{2,10}', text)
        terms.update(chinese_terms)
        
        # 英文术语（可能包含连字符）
        english_terms = re.findall(r'\b[a-zA-Z][a-zA-Z\-]{2,20}\b', text)
        terms.update(english_terms)
        
        # 过滤常见非术语词汇
        stopwords = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 
                     'have', 'been', 'were', 'are', 'you', 'your', 'will',
                     '请', '谢谢', '您好', '关于', '如下', '如下所示'}
        terms = terms - stopwords
        
        return list(terms)
    
    def analyze_email(self, email_path: str) -> dict:
        """
        分析邮件，识别专业术语并提供翻译
        
        Args:
            email_path: 邮件文件路径
            
        Returns:
            分析结果
        """
        # 提取邮件内容
        email_data = extract_text_from_eml(email_path)
        
        if 'error' in email_data:
            return {'error': email_data['error']}
        
        content = email_data['content']
        subject = email_data.get('subject', '')
        
        # 提取可能的专业术语
        potential_terms = self.extract_potential_terms(content + ' ' + subject)
        
        # RAG查询术语
        terminology_dict = {}
        for term in potential_terms[:10]:  # 限制查询数量
            try:
                result = self.rag.answer(term, top_k=1)
                if result['total_found'] > 0 and result['sources']:
                    source = result['sources'][0]
                    # 只保留高置信度的结果
                    if source['confidence'] > 0.7:
                        terminology_dict[term] = {
                            'translation': source['english'] if any('\u4e00' <= c <= '\u9fff' for c in term) else source['chinese'],
                            'category': source['category'],
                            'confidence': source['confidence']
                        }
            except:
                continue
        
        return {
            'email_info': {
                'subject': subject,
                'from': email_data.get('from', ''),
                'category': email_data.get('category', '')
            },
            'terminology': terminology_dict,
            'term_count': len(terminology_dict)
        }
    
    def translate_email_terms(self, email_path: str) -> str:
        """
        翻译邮件中的专业术语并生成注释
        
        Args:
            email_path: 邮件文件路径
            
        Returns:
            带注释的邮件内容
        """
        result = self.analyze_email(email_path)
        
        if 'error' in result:
            return f"Error: {result['error']}"
        
        # 构建注释
        annotations = ["\n=== 术语注释 ===\n"]
        
        for term, info in result['terminology'].items():
            annotations.append(
                f"• {term} → {info['translation']} "
                f"(分类: {info['category']})"
            )
        
        return "\n".join(annotations)
    
    def batch_analyze_emails(self, email_dir: str = "data/eml_files") -> dict:
        """
        批量分析邮件目录
        
        Args:
            email_dir: 邮件目录路径
            
        Returns:
            汇总分析结果
        """
        import glob
        
        eml_files = glob.glob(os.path.join(email_dir, "*.eml"))
        
        all_terms = {}
        email_count = 0
        
        for eml_path in eml_files[:20]:  # 限制分析数量
            try:
                result = self.analyze_email(eml_path)
                if 'terminology' in result:
                    for term, info in result['terminology'].items():
                        if term not in all_terms:
                            all_terms[term] = info
                            all_terms[term]['count'] = 1
                        else:
                            all_terms[term]['count'] += 1
                    email_count += 1
            except:
                continue
        
        return {
            'email_count': email_count,
            'unique_terms': len(all_terms),
            'top_terms': sorted(
                all_terms.items(), 
                key=lambda x: x[1]['count'], 
                reverse=True
            )[:20]
        }


def demo():
    """演示"""
    print("="*60)
    print("邮件术语助手演示")
    print("="*60)
    
    assistant = EmailTerminologyAssistant()
    
    # 模拟分析
    test_content = """
    关于ASOS订单INDOB29034的核料确认。
    
    请确认以下面料：
    - 主面料：Cotton Twill，需做Lab Dip确认颜色
    - 里料： Polyester lining
    - 拉链：需要invisible zipper，5号规格
    
    请尽快安排。
    """
    
    print("\n测试内容:")
    print(test_content)
    
    print("\n提取的术语:")
    terms = assistant.extract_potential_terms(test_content)
    for term in terms[:10]:
        print(f"  - {term}")
    
    print("\n术语翻译:")
    for term in ['拉链', '里料', 'invisible zipper', 'Lab Dip']:
        result = assistant.rag.answer(term, top_k=1)
        if result['sources']:
            s = result['sources'][0]
            print(f"  {term} → {s['english'] if term.isascii() else s['chinese']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 分析指定邮件
        assistant = EmailTerminologyAssistant()
        result = assistant.analyze_email(sys.argv[1])
        
        print("邮件分析结果:")
        print(f"主题: {result['email_info']['subject']}")
        print(f"识别术语数: {result['term_count']}")
        print("\n术语详情:")
        for term, info in result['terminology'].items():
            print(f"  {term}: {info['translation']} ({info['category']})")
    else:
        demo()
