"""
上下文长度管理工具

职责：
  1. 检测消息列表是否接近或超过上下文上限
  2. 计算剩余可用空间
  3. 添加标准化的 [上下文警告] 标记
  4. 不决策，只检测和标记

使用：
    from email_agent.services.context_manager import ContextManager
    
    cm = ContextManager(max_tokens=8000, reserve_tokens=1000)
    
    # 检查当前上下文
    check = cm.check_overflow(messages)
    # check["status"] -> "ok" | "warning" | "overflow"
    # check["remaining_tokens"] -> 剩余可用token数
    
    # 计算工具结果允许的最大长度
    max_items = cm.calculate_max_items(rule.item_token_estimate, check["remaining_tokens"])
    
    # 添加上下文警告标记
    warned_message = cm.add_warning(truncated_result, original_count=253, returned_count=15)
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ContextCheckResult:
    """上下文检查结果"""
    status: str              # "ok" | "warning" | "overflow"
    used_tokens: int         # 已使用token数
    remaining_tokens: int    # 剩余可用token数
    max_tokens: int          # 总上限
    warning_threshold: float # 警告阈值比例


class ContextManager:
    """
    上下文管理器
    
    核心原则：
      - 只检测长度、计算空间、添加标记
      - 不决定截取策略（交给 ResultTruncator）
      - 不决定 satisfied（交给 V2 模型）
    """
    
    def __init__(
        self,
        max_tokens: int = 8000,
        reserve_tokens: int = 1000,
        warning_threshold: float = 0.8,
    ):
        """
        Args:
            max_tokens: 上下文总token上限
            reserve_tokens: 给 V2 输出预留的token数
            warning_threshold: 警告阈值（使用比例超过此值触发warning）
        """
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.warning_threshold = warning_threshold
        self.effective_limit = max_tokens - reserve_tokens  # 实际可用上限
    
    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的token数
        
        简化估算：
          - 中文：1 字符 ≈ 1 token
          - 英文：按空格分词，1 词 ≈ 1 token
          
        实际部署时可替换为 tiktoken 等精确计算
        """
        if not text:
            return 0
        
        # 中文字符数
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        # 英文单词数（粗略）
        english_words = len([w for w in text.split() if any(c.isalpha() for c in w)])
        # 其他字符（标点、数字等）
        other_chars = len(text) - chinese_chars - sum(len(w) for w in text.split() if any(c.isalpha() for c in w))
        
        # 中文按字符，英文按词，其他按字符的一半估算
        return chinese_chars + english_words + other_chars // 2
    
    def estimate_message_tokens(self, message: Dict[str, str]) -> int:
        """估算单条消息的token数"""
        role_tokens = self.estimate_tokens(message.get("role", ""))
        content_tokens = self.estimate_tokens(message.get("content", ""))
        # 加上JSON格式开销
        overhead = 20
        return role_tokens + content_tokens + overhead
    
    def check_overflow(self, messages: List[Dict[str, str]]) -> ContextCheckResult:
        """
        检查当前消息列表是否接近或超过上限
        
        Args:
            messages: 当前会话的消息列表
            
        Returns:
            ContextCheckResult: 检查结果
        """
        total_used = sum(self.estimate_message_tokens(m) for m in messages)
        remaining = self.effective_limit - total_used
        usage_ratio = total_used / self.effective_limit if self.effective_limit > 0 else 1.0
        
        if total_used >= self.effective_limit:
            status = "overflow"
        elif usage_ratio >= self.warning_threshold:
            status = "warning"
        else:
            status = "ok"
        
        return ContextCheckResult(
            status=status,
            used_tokens=total_used,
            remaining_tokens=max(0, remaining),
            max_tokens=self.max_tokens,
            warning_threshold=self.warning_threshold,
        )
    
    def check_content_overflow(
        self,
        messages: List[Dict[str, str]],
        new_content: str,
    ) -> ContextCheckResult:
        """
        检查添加新内容后是否会超限
        
        Args:
            messages: 当前消息列表
            new_content: 待添加的新内容（工具返回文本）
            
        Returns:
            ContextCheckResult: 检查结果
        """
        # 模拟添加后的消息列表
        simulated = messages + [{"role": "user", "content": new_content}]
        return self.check_overflow(simulated)
    
    def calculate_max_items(
        self,
        item_token_estimate: int,
        remaining_tokens: int,
        min_items: int = 1,
    ) -> int:
        """
        计算剩余空间允许返回的最大item数
        
        Args:
            item_token_estimate: 单个item预估token数（来自 TruncationRule）
            remaining_tokens: 剩余可用token数（来自 check_overflow）
            min_items: 最少返回数量（保证至少返回几个）
            
        Returns:
            int: 允许返回的最大item数
        """
        if remaining_tokens <= 0:
            return min_items
        
        # 预留一些空间给JSON结构和字段名
        structure_overhead = 100
        available = remaining_tokens - structure_overhead
        
        if available <= 0:
            return min_items
        
        max_items = available // item_token_estimate
        return max(min_items, max_items)
    
    def add_warning(
        self,
        content: Any,
        original_count: int,
        returned_count: int,
        item_type: str = "条",
    ) -> str:
        """
        添加标准化的上下文警告标记
        
        Args:
            content: 截取后的内容（dict 或 str）
            original_count: 原始总数
            returned_count: 返回数
            item_type: 计量单位（条/个/款等）
            
        Returns:
            str: 带警告标记的完整文本
        """
        # 内容转字符串
        if isinstance(content, dict):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = str(content)
        
        # 构造警告文本
        if original_count <= returned_count:
            # 未截断，不加警告
            return content_str
        
        warning = (
            f"[上下文警告] 结果已截断。"
            f"原始{original_count}{item_type}，"
            f"仅返回{returned_count}{item_type}（达到上下文上限）。"
            f"如需查看剩余内容，请说\"继续\"或\"剩下的\"。"
        )
        
        return f"{content_str}\n{warning}"
    
    def build_truncation_feedback(
        self,
        truncation_result: Any,
    ) -> str:
        """
        从 TruncationResult 构建带警告的反馈文本
        
        和 ResultTruncator 配合使用的便捷方法
        """
        # 尝试从 TruncationResult 提取信息
        if hasattr(truncation_result, 'truncated_data'):
            data = truncation_result.truncated_data
            original = truncation_result.original_count
            returned = truncation_result.returned_count
            note = truncation_result.truncation_note
        else:
            # 兼容普通dict
            data = truncation_result
            original = 0
            returned = 0
            note = ""
        
        content_str = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
        
        if original > returned and returned > 0:
            warning = (
                f"[上下文警告] {note}，达到上下文上限。"
                f"如需查看剩余内容，请说\"继续\"。"
            )
            return f"[工具返回] {content_str}\n{warning}"
        
        return f"[工具返回] {content_str}"
    
    def get_status_summary(self, check: ContextCheckResult) -> str:
        """获取状态摘要（用于日志）"""
        usage_pct = check.used_tokens / self.effective_limit * 100 if self.effective_limit > 0 else 100
        return (
            f"上下文状态: {check.status} | "
            f"已用: {check.used_tokens}/{self.effective_limit} ({usage_pct:.1f}%) | "
            f"剩余: {check.remaining_tokens} tokens"
        )
