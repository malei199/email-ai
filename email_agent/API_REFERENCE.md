# 本地查询接口总览

> 生成日期：2026-05-04
> 对应文档：`email_finetuning_pipeline/V2_CAPABILITY_DESIGN.md`

---

## 一、KG 适配器 (`services/kg_adapter.py`) — 12 个接口

| # | 函数 | 功能 | 核心入参 | 核心出参 |
|---|------|------|---------|---------|
| 1 | `query_person_by_email(email)` | 邮箱查人员 | `email` | `{"name", "id"}` / `None` |
| 2 | `query_styles_by_person(person_name)` | 人员查款号列表 | `person_name` | `{"styles": [...]}` |
| 3 | `query_timeline(style_id)` | 款号时间线 | `style_id` | `[{event}]` 列表 |
| 4 | `query_last_update(style_id)` | 最后更新时间 | `style_id` | `{"last_update", "days_since_update"}` |
| 5 | `query_people_by_style(style_id)` | 款号涉及人员 | `style_id` | `{"people": [...]}` |
| 6 | `query_customers_by_style(style_id)` | 款号关联客户 | `style_id` | `{"style_id", "customers": [{name, email}], "total_customers"}` |
| 7 | `query_collaborators(person_name, top_k=10)` | 人员协作对象 | `person_name`, `top_k?` | `{"person", "collaborators": [{name, event_count, style_count}], "total_unique"}` |
| 8 | `query_styles_by_factory(factory_name)` | 工厂查款号 | `factory_name_or_code` | `{"factory", "styles": [{style_id, order_id, total_delay_days}], "total_styles"}` |
| 9 | `query_factory_delays(top_k=10)` | 工厂延期统计 | `top_k?` | `{"factories": [{name, total_delay_days, avg_delay}], "total_factories"}` |
| 10 | `find_styles_with_conditions(...)` | 多条件筛选款号 | `categories?`, `min_delay_days?`, `factory_name?`, `person_name?`, `customer_email?` | `{"conditions", "styles": [{style_id, matched_categories, total_delay_days}], "total"}` |
| 11 | `query_person_styles_with_stats(person_name)` | 人员款号完整统计 | `person_name` | `{"person", "styles": [{style_id, role, event_count, last_update, latest_category, total_delay_days}], "total_styles", "as_primary_owner", "as_participant"}` |
| 12 | `get_style_overview(style_id)` | 款号综合概览 | `style_id` | `{"style_id", "people", "primary_owner", "customers", "timeline", "by_category", "total_events", "last_update", "latest_category", "days_since_update"}` |

---

## 二、RAG 适配器 (`services/rag_adapter.py`) — 6 个接口

| # | 函数 | 功能 | 核心入参 | 核心出参 |
|---|------|------|---------|---------|
| 1 | `query_terms(query, top_k=5)` | 查服装术语 | `query`, `top_k?` | `[{chinese, english, category, score}]` |
| 2 | `translate_term(query, top_k=3)` | 术语翻译 | `query`, `top_k?` | `{"query", "translations": [...], "best_match": {chinese, english}}` |
| 3 | `enhance_query_with_terms(query_text)` | 术语增强查询 | `query_text` | `str: 增强后的文本` |
| 4 | `query_email_events(style_id?, style_ids?, query_text?, top_k=10, include_full_fields=True)` | 邮件事件语义检索 | `style_id?`, `style_ids?`, `query_text?`, `top_k?`, `include_full_fields?` | `[{id, description, style_id, order_id, category, event_type, date, related_date, delay_days, party_from, party_to, confidence, score, source_filename, source_subject}]` |
| 5 | `query_email_events_by_date(style_id?, style_ids?, days=7)` | 最近N天事件 | `style_id?`, `style_ids?`, `days?` | `[{id, description, style_id, order_id, category, event_type, date, related_date, delay_days, party_from, party_to, confidence, score, source_filename, source_subject}]` |
| 6 | `query_email_events_by_conditions(style_ids?, categories?, event_types?, min_delay_days?, start_date?, end_date?, top_k=100)` | 多条件组合查询 | 多个可选过滤条件 | `[{id, description, style_id, order_id, category, event_type, date, related_date, delay_days, party_from, party_to, confidence, score, source_filename, source_subject}]` |

---

## 三、查询编排器 (`services/query_orchestrator.py`) — 9 个接口

| # | 函数 | 功能 | 核心入参 | 核心出参 |
|---|------|------|---------|---------|
| 1 | `resolve_style_ambiguity(...)` | 款号歧义消解 | `person_name?`, `customer_email?`, `factory_name?`, `context_style_ids?`, `max_suggestions=5` | `{"resolved", "style_ids", "style_count", "reason", "needs_clarification", "suggestions"}` |
| 2 | `narrow_style_scope(style_ids, query_text?, category_hint?, date_hint?)` | 缩小款号范围 | `style_ids`, `query_text?`, `category_hint?`, `date_hint?` | `List[str]: 过滤后的款号列表` |
| 3 | `route_query(query_text, person_name?, style_id?, style_ids?)` | 查询路由（5类问题） | `query_text`, `person_name?`, `style_id?`, `style_ids?` | `{"strategy", "confidence", "reason", "params"}` |
| 4 | `execute_kg_overview(style_id)` | 执行 KG 款号总览 | `style_id` | `{"type", "style_id", "data": {people, customers, timeline_summary, last_update, stats}}` |
| 5 | `execute_rag_semantic(query_text, style_ids?, person_name?, top_k=10)` | 执行 RAG 语义检索 | `query_text`, `style_ids?`, `person_name?`, `top_k?` | `{"type", "query", "style_ids", "event_count", "events"}` |
| 6 | `execute_hybrid(query_text, style_ids, person_name?, top_k=10)` | 执行 KG+RAG 联合 | `query_text`, `style_ids`, `person_name?`, `top_k?` | `{"type", "query", "style_ids", "kg_summary", "rag_events", "events_by_style", "total_events"}` |
| 7 | `execute_kg_temporal(query_type, person_name?, style_ids?, top_k=10)` | 执行 KG 时序/延期 | `query_type`, `person_name?`, `style_ids?`, `top_k?` | `{"type", "subtype", "factories/delayed_styles/timelines"}` |
| 8 | `execute_kg_relational(query_type, person_name, top_k=10)` | 执行 KG 关系查询 | `query_type`, `person_name`, `top_k?` | `{"type", "subtype", "person", "collaborators", "total_unique"}` |
| 9 | `execute_query(query_text, person_name?, customer_email?, style_id?, style_ids?, context_style_ids?, top_k=10)` | **主入口**：自动路由执行 | 综合参数 | `{"query", "routing", "ambiguity", "result", "metadata"}` |

---

## 四、结果截取器 (`services/result_truncator.py`) — 1 个主入口 + 6 种策略

| # | 方法 | 功能 | 核心入参 | 核心出参 |
|---|------|------|---------|---------|
| 1 | `ResultTruncator.truncate(raw_result, query_type, user_intent="overview", max_items=None, custom_strategy=None)` | **主入口**：语义化截取 | `raw_result`, `query_type`, `user_intent?`, `max_items?`, `custom_strategy?` | `{"truncated_data", "original_count", "returned_count", "strategy", "omitted_summary", "truncation_note"}` |
| 2 | `_sample_head(items, limit, context)` | 前N个采样 | — | — |
| 3 | `_sample_by_stage(items, limit, context)` | 按阶段均匀采样 | — | — |
| 4 | `_sample_by_delay(items, limit, context)` | 按延期降序采样 | — | — |
| 5 | `_sample_by_score(items, limit, context)` | 按相似度降序采样 | — | — |
| 6 | `_sample_by_date(items, limit, context)` | 按时间最近采样 | — | — |
| 7 | `_sample_stat_only(items, limit, context)` | 只返回统计 | — | — |

**配置规则**（9 种查询类型）：
- `kg_query.my_styles` → `styles` 列表字段
- `kg_query.style_summaries` → `summaries` 列表字段
- `kg_query.style_overview` → `timeline` 列表字段
- `rag_query.semantic_search` → `events` 列表字段
- 等等...

---

## 五、上下文管理器 (`services/context_manager.py`) — 9 个方法

| # | 方法 | 功能 | 核心入参 | 核心出参 |
|---|------|------|---------|---------|
| 1 | `ContextManager.__init__(max_tokens=8000, reserve_tokens=1000, warning_threshold=0.8)` | 初始化 | `max_tokens?`, `reserve_tokens?`, `warning_threshold?` | — |
| 2 | `estimate_tokens(text)` | 估算文本 token | `text` | `int` |
| 3 | `estimate_message_tokens(message)` | 估算消息 token | `message` | `int` |
| 4 | `check_overflow(messages)` | 检查上下文溢出 | `messages` | `ContextCheckResult: {status, used_tokens, remaining_tokens, max_tokens, warning_threshold}` |
| 5 | `check_content_overflow(messages, new_content)` | 模拟添加后检查 | `messages`, `new_content` | `ContextCheckResult` |
| 6 | `calculate_max_items(item_token_estimate, remaining_tokens, min_items=1)` | 计算最大 item 数 | `item_token_estimate`, `remaining_tokens`, `min_items?` | `int` |
| 7 | `add_warning(content, original_count, returned_count, item_type="条")` | 添加警告标记 | `content`, `original_count`, `returned_count`, `item_type?` | `str` |
| 8 | `build_truncation_feedback(truncation_result)` | 构建反馈文本 | `truncation_result` | `str` |
| 9 | `get_status_summary(check)` | 状态摘要 | `check` | `str` |

---

## 六、回答生成器 (`services/answer_generator.py`) — 6 个模板 + 2 个入口

| # | 函数 | 功能 | 模板名 | 所需 data 字段 |
|---|------|------|--------|--------------|
| 1 | `_render_my_styles_summary(data, mode)` | 我的款号进度汇总 | `my_styles_summary` | `summaries`, `total`, `truncated?`, `has_more?` |
| 2 | `_render_person_styles_summary(data, mode)` | 人员款号汇总 | `person_styles_summary` | `person`, `summaries` |
| 3 | `_render_factory_styles_summary(data, mode)` | 工厂款号汇总 | `factory_styles_summary` | `factory`, `styles`, `delays?` |
| 4 | `_render_term_translation(data, mode)` | 术语翻译 | `term_translation` | `term`, `translation`, `category` |
| 5 | `_render_style_list(data, mode)` | 款号列表 | `style_list` | `styles`, `count?` |
| 6 | `_render_not_found(data, mode)` | 未找到 | `not_found` | `query`, `suggestions?` |
| 7 | `generate_answer(template, data, mode="detailed")` | **主入口** | — | `template`, `data` → `Markdown str` |
| 8 | `generate_from_v2_call(template, context, mode)` | V2 调用入口 | — | 自动从 context 提取数据 |

---

## 七、接口映射到 V2 function_calls

| V2 function_call | 对应本地接口 | 说明 |
|-----------------|-------------|------|
| `kg_query.my_styles` | `kg_adapter.query_person_styles_with_stats(default_person)` | "我"=默认高频人员 |
| `kg_query.person_styles` | `kg_adapter.query_person_styles_with_stats(person_name)` | |
| `kg_query.factory_styles` | `kg_adapter.query_styles_by_factory(factory_name)` | |
| `kg_query.style_summaries` | 循环 `kg_adapter.get_style_overview(sid)` | 批量查 |
| `kg_query.style_overview` | `kg_adapter.get_style_overview(style_id)` | |
| `kg_query.timeline` | `kg_adapter.query_timeline(style_id)` | |
| `kg_query.collaborators` | `kg_adapter.query_collaborators(person_name)` | |
| `kg_query.factory_delays` | `kg_adapter.query_factory_delays()` | |
| `rag_query.term_translation` | `rag_adapter.translate_term(query)` | |
| `rag_query.semantic_search` | `rag_adapter.query_email_events(query_text, style_ids)` | |
| `generate_answer` | `answer_generator.generate_from_v2_call(template, context)` | |

---

## 八、缺失能力（与 V2 新设计对比）

| V2 新设计需求 | 当前本地接口状态 | 需补充 |
|-------------|---------------|--------|
| `result` 字段过滤 | ❌ 不支持 | KG/RAG 适配器需支持按字段路径过滤返回 |
| 查询链（一级+二级） | ❌ 不支持 | 编排器需支持依赖解析和批量展开 |
| `by_category` 子字段过滤 | ❌ 不支持 | `style_overview` 需支持 `by_category.面料` 等 |
| 聚合统计（事件数>30） | ❌ 不支持 | KG 层需新增聚合查询或外部系统处理 |
| 上下文警告训练格式 | ⚠️ 简单截断 | 待外部系统完善 |
