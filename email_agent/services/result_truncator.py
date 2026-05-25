"""
查询结果截取工具

职责：根据查询类型和用户意图，对原始结果做语义化截取
原则：只截数量，不截字段——item 要么完整保留，要么整个丢弃

使用：
    from email_agent.services.result_truncator import ResultTruncator
    
    truncator = ResultTruncator()
    result = truncator.truncate(
        raw_result={"styles": [...], "total": 253},
        query_type="kg_query.my_styles",
        user_intent="overview",
        max_items=15,
    )
    # result.truncated_data  # 截取后的数据
    # result.truncation_note  # "共253条，显示15条（按阶段采样）"
"""

from typing import Any, Dict, List, Callable, Optional
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict


class SampleStrategy(Enum):
    """采样策略"""
    HEAD = "head"              # 前N个
    BY_STAGE = "by_stage"      # 按阶段均匀采样
    BY_DELAY = "by_delay"      # 按延期天数排序取前N
    BY_SCORE = "by_score"      # 按相似度/分数排序取前N
    BY_DATE = "by_date"        # 按时间最近取前N
    STAT_ONLY = "stat_only"    # 只返回统计，不返回详情


@dataclass
class TruncationRule:
    """截取规则配置"""
    query_type: str            # "kg_query.my_styles"
    primary_field: str         # 主列表字段名 "styles"
    item_token_estimate: int   # 单个item预估token数
    summary_fields: List[str]  # 必须保留的统计字段
    default_strategy: SampleStrategy
    max_items: int = 20        # 默认最大返回数


@dataclass
class TruncationResult:
    """截取结果"""
    truncated_data: Dict       # 截取后的数据（结构完整，列表变短）
    omitted_data: List[Dict]   # 被省略的完整数据（用于续查存储）
    original_count: int        # 原始列表长度
    returned_count: int        # 返回列表长度（每个item完整）
    strategy: str              # 实际使用的策略
    omitted_summary: Dict      # 被省略部分的摘要
    truncation_note: str       # 截取说明文本
    conversation: Optional[Dict] = None  # 触发截断时的对话上下文
    query_type: Optional[str] = None     # 查询类型，用于续查
    remaining_data: Optional[Dict] = None  # 完整的剩余数据（用于续查）


class ResultTruncator:
    """
    结果截取器
    
    核心原则：只减少列表中的item数量，不修改任何item的内部字段。
    item要么完整保留，要么整个丢弃。
    """
    
    # 内置规则表
    RULES: Dict[str, TruncationRule] = {
        "kg_query.my_styles": TruncationRule(
            query_type="kg_query.my_styles",
            primary_field="styles",
            item_token_estimate=50,
            summary_fields=["total"],
            default_strategy=SampleStrategy.BY_STAGE,
        ),
        "kg_query.person_styles": TruncationRule(
            query_type="kg_query.person_styles",
            primary_field="styles",
            item_token_estimate=50,
            summary_fields=["total", "person"],
            default_strategy=SampleStrategy.BY_STAGE,
        ),
        "kg_query.factory_styles": TruncationRule(
            query_type="kg_query.factory_styles",
            primary_field="styles",
            item_token_estimate=50,
            summary_fields=["total", "factory"],
            default_strategy=SampleStrategy.BY_DELAY,
        ),
        "kg_query.style_summaries": TruncationRule(
            query_type="kg_query.style_summaries",
            primary_field="summaries",
            item_token_estimate=80,
            summary_fields=["total"],
            default_strategy=SampleStrategy.BY_DELAY,
        ),
        "kg_query.timeline": TruncationRule(
            query_type="kg_query.timeline",
            primary_field="events",
            item_token_estimate=120,
            summary_fields=["total", "style_id"],
            default_strategy=SampleStrategy.BY_DATE,
        ),
        "kg_query.collaborators": TruncationRule(
            query_type="kg_query.collaborators",
            primary_field="collaborators",
            item_token_estimate=40,
            summary_fields=["total", "person"],
            default_strategy=SampleStrategy.BY_SCORE,
        ),
        "kg_query.factory_delays": TruncationRule(
            query_type="kg_query.factory_delays",
            primary_field="factories",
            item_token_estimate=40,
            summary_fields=["total"],
            default_strategy=SampleStrategy.BY_DELAY,
        ),
        "rag_query.semantic_search": TruncationRule(
            query_type="rag_query.semantic_search",
            primary_field="events",
            item_token_estimate=150,
            summary_fields=["total", "query"],
            default_strategy=SampleStrategy.BY_SCORE,
        ),
        "rag_query.term_translation": TruncationRule(
            query_type="rag_query.term_translation",
            primary_field="translations",
            item_token_estimate=30,
            summary_fields=["query", "best_match"],
            default_strategy=SampleStrategy.HEAD,
        ),
    }
    
    # 用户意图 → 策略映射
    INTENT_STRATEGY_MAP: Dict[str, SampleStrategy] = {
        "overview": SampleStrategy.BY_STAGE,
        "risk": SampleStrategy.BY_DELAY,
        "recent": SampleStrategy.BY_DATE,
        "detail": SampleStrategy.HEAD,
        "count_only": SampleStrategy.STAT_ONLY,
    }
    
    def __init__(self):
        self._strategies: Dict[SampleStrategy, Callable] = {
            SampleStrategy.HEAD: self._sample_head,
            SampleStrategy.BY_STAGE: self._sample_by_stage,
            SampleStrategy.BY_DELAY: self._sample_by_delay,
            SampleStrategy.BY_SCORE: self._sample_by_score,
            SampleStrategy.BY_DATE: self._sample_by_date,
            SampleStrategy.STAT_ONLY: self._sample_stat_only,
        }
    
    def truncate(
        self,
        raw_result: Dict,
        query_type: str,
        user_intent: str = "overview",
        max_items: Optional[int] = None,
        custom_strategy: Optional[SampleStrategy] = None,
        conversation: Optional[Dict] = None,
    ) -> TruncationResult:
        """
        截取入口
        
        Args:
            raw_result: 查询工具的原始返回（完整结果）
            query_type: 查询类型标识，如 "kg_query.my_styles"
            user_intent: 用户意图，如 "overview"/"risk"/"recent"
            max_items: 最大返回数量（由上下文管理器根据剩余空间计算）
            custom_strategy: 强制指定策略（覆盖默认）
            
        Returns:
            TruncationResult: 截取后的结果，包含截断说明
        """
        rule = self.RULES.get(query_type)
        if not rule:
            # 未知类型，原样返回
            count = self._count_items(raw_result, "")
            return TruncationResult(
                truncated_data=raw_result,
                omitted_data=[],
                original_count=count,
                returned_count=count,
                strategy="no_rule",
                omitted_summary={},
                truncation_note="",
                conversation=conversation,
            )
        
        # 确定策略
        strategy = custom_strategy or self.INTENT_STRATEGY_MAP.get(user_intent, rule.default_strategy)
        
        # 确定数量
        limit = max_items or rule.max_items
        
        # 执行截取
        primary_field = rule.primary_field
        items = self._get_field(raw_result, primary_field, [])
        if not isinstance(items, list):
            items = []
        original_count = len(items)
        
        # STAT_ONLY 策略特殊处理
        if strategy == SampleStrategy.STAT_ONLY:
            sampled_items, omitted_data, omitted_summary = self._sample_stat_only(items, limit, raw_result)
        else:
            sampler = self._strategies.get(strategy, self._sample_head)
            sampled_items, omitted_data, omitted_summary = sampler(items, limit, raw_result)
        
        # 构造返回数据（结构完整，只减少列表长度）
        truncated_data = self._build_result(raw_result, rule, sampled_items)
        
        return TruncationResult(
            truncated_data=truncated_data,
            omitted_data=omitted_data,
            original_count=original_count,
            returned_count=len(sampled_items),
            strategy=strategy.value,
            omitted_summary=omitted_summary,
            truncation_note=self._build_note(original_count, len(sampled_items), strategy),
            conversation=conversation,
        )
    
    def estimate_tokens(self, result: TruncationResult) -> int:
        """
        估算截取结果的token数
        
        用于上下文管理器判断是否还需要进一步截取
        """
        rule = self.RULES.get(result.strategy)
        if not rule:
            return 0
        # 基础开销 + 每个item的估算token
        base_tokens = 100  # JSON结构、字段名等开销
        item_tokens = result.returned_count * rule.item_token_estimate
        return base_tokens + item_tokens
    
    # ============ 采样策略实现（只决定保留哪些完整item） ============
    
    def _sample_head(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """前N个——保留列表前limit个完整item"""
        sampled = items[:limit]
        omitted = items[limit:]
        return sampled, omitted, {"omitted_count": len(omitted)}
    
    def _sample_by_stage(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """按阶段均匀采样——每阶段至少保留1个完整item，轮询分配"""
        groups = defaultdict(list)
        for item in items:
            stage = item.get("latest_category") or item.get("category") or "其他"
            groups[stage].append(item)  # 整个item放入分组，不修改
        
        # 轮询取完整item
        result = []
        stages = list(groups.keys())
        while len(result) < limit and any(groups[s] for s in stages):
            for stage in stages:
                if len(result) >= limit:
                    break
                if groups[stage]:
                    result.append(groups[stage].pop(0))  # 取完整item
        
        # 被省略的是整个item，不是字段
        omitted = []
        for stage in stages:
            omitted.extend(groups[stage])
        return result, omitted, {"omitted_by_stage": {stage: len(g) for stage, g in groups.items() if g}}
    
    def _sample_by_delay(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """按延期天数降序——保留延期最严重的limit个完整item"""
        sorted_items = sorted(
            items,
            key=lambda x: x.get("total_delay_days", 0) or x.get("delay_days", 0),
            reverse=True
        )
        sampled = sorted_items[:limit]
        omitted = sorted_items[limit:]
        omitted_summary = {}
        if omitted:
            omitted_summary["max_delay_in_omitted"] = omitted[0].get("total_delay_days", 0) or omitted[0].get("delay_days", 0)
        return sampled, omitted, omitted_summary
    
    def _sample_by_score(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """按相似度/分数降序——保留分数最高的limit个完整item"""
        sorted_items = sorted(
            items,
            key=lambda x: x.get("score", 0) or x.get("event_count", 0),
            reverse=True
        )
        sampled = sorted_items[:limit]
        omitted = sorted_items[limit:]
        return sampled, omitted, {"omitted_count": len(omitted)}
    
    def _sample_by_date(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """按时间最近——保留时间最近的limit个完整item"""
        sorted_items = sorted(
            items,
            key=lambda x: x.get("date", "") or x.get("last_update", ""),
            reverse=True
        )
        sampled = sorted_items[:limit]
        omitted = sorted_items[limit:]
        return sampled, omitted, {"omitted_count": len(omitted)}
    
    def _sample_stat_only(self, items: List[Dict], limit: int, context: Dict) -> tuple:
        """只返回统计，不返回详情列表——item列表置空"""
        return [], items, {"total": len(items)}
    
    # ============ 辅助方法 ============
    
    def _get_field(self, data: Dict, path: str, default: Any) -> Any:
        """安全获取字段（支持扁平结构和嵌套结构）"""
        if not path:
            return data
        # 1. 先尝试直接取（扁平结构）
        if path in data:
            return data.get(path, default)
        # 2. 再尝试嵌套结构
        data_keys = [k for k in data.keys() if k not in ('status', '_errors', '_meta')]
        for key in data_keys:
            inner = data[key]
            if isinstance(inner, dict) and path in inner:
                return inner.get(path, default)
        return default
    
    def _count_items(self, data: Dict, field: str) -> int:
        """计算列表字段长度"""
        items = self._get_field(data, field, [])
        return len(items) if isinstance(items, list) else 0
    
    def _build_result(self, raw: Dict, rule: TruncationRule, sampled: List) -> Dict:
        """构造截取后的结果——结构完整，只替换主列表字段"""
        result = {}
        # 复制所有非列表字段（统计信息等）
        for key, value in raw.items():
            if key != rule.primary_field:
                result[key] = value
        # 设置截取后的完整列表
        result[rule.primary_field] = sampled
        return result
    
    def _build_note(self, original: int, returned: int, strategy: SampleStrategy) -> str:
        """生成截取说明"""
        if original <= returned:
            return ""
        strategy_desc = {
            SampleStrategy.HEAD: "前N个",
            SampleStrategy.BY_STAGE: "按阶段采样",
            SampleStrategy.BY_DELAY: "按延期优先",
            SampleStrategy.BY_SCORE: "按相关度优先",
            SampleStrategy.BY_DATE: "按时间最近",
            SampleStrategy.STAT_ONLY: "仅统计",
        }.get(strategy, "")
        return f"共{original}条，显示{returned}条（{strategy_desc}）"
