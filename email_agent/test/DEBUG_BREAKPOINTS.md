# 关键 Debug 断点（按数据流向排序）

> 本文档记录从前端页面输入开始，一步步详细数据流转的调试断点位置。
> 基于 email_agent 完整代码结构整理，具体到代码行。

---

## 📊 数据流转全景图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  前端 (static/js/app.js)                                                        │
│  sendMessage() → fetch('/api/chat') → SSE流接收                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    ↓ POST /api/chat
┌─────────────────────────────────────────────────────────────────────────────────┐
│  路由层 (routers/chat.py)                                                       │
│  chat_endpoint() → sse_stream()                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Agent主入口 (agents/chat_agent.py)                                              │
│  process_message() → V3路由 → 分支处理                                           │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
              route_v1         route_v2       direct_answer
                    ↓               ↓
        ┌─────────────────┐  ┌─────────────────────────────┐
        │ v1_orchestrator │  │ v2_orchestrator             │
        │ 查ChromaDB→V1   │  │ 多轮: V2→Executor→Truncate  │
        └─────────────────┘  └─────────────────────────────┘
                                    ↓
                          ┌─────────┴─────────┐
                          ↓                   ↓
                    v2_executor.py      kg_adapter.py
                    (33种查询链)         rag_adapter.py
                    (KG+RAG调用)         (ChromaDB查询)
```

---

## 一、前端层 `static/js/app.js`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **270** | `sendMessage()` 函数入口 | 用户点击发送，捕获原始输入内容 `text` |
| **286-297** | `fetch('/api/chat', {...})` | 查看 POST 请求的 body（session_id, message, mode） |
| **309** | `const reader = res.body.getReader()` | SSE 流开始接收 |
| **315-318** | `while(true) { reader.read() }` | 逐块接收 SSE 数据，查看 event + data |
| **333** | `const parsed = JSON.parse(data)` | 解析后的 delta/done/error 事件数据 |
| **339-340** | `assistantContent += parsed.content` | 累积最终回答内容 |

---

## 二、路由层 `routers/chat.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **147-148** | `chat_endpoint()` | FastAPI 入口，查看 `req` 对象（message, session_id, mode） |
| **59-61** | `sse_stream()` 参数提取 | 确认 user_message, session_id, mode |
| **64-77** | Session 创建/复用逻辑 | 查看 chat_session.id |
| **80-86** | 保存 user_message 到 DB | 确认消息已持久化 |
| **92** | `is_continuation(user_message)` | 检测是否为"继续"/"剩下的"等续查关键词 |
| **103** | `process_message()` 调用 | 进入 Agent 核心，这是最重要的断点 |
| **107-115** | event 类型分发（delta/done） | 查看 process_message 返回的事件 |
| **113** | `session_flow = event_data.get("session_flow", [])` | 提取完整对话流程用于保存 |
| **126-135** | 保存 session_flow 到 Message 表 | 查看每条 role + content |
| **137-138** | `_save_truncation_info()` | 如有截断，保存到 OmittedData |

---

## 三、Agent 主入口 `agents/chat_agent.py` ⭐核心

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **193** | `process_message()` 入口 | 整个对话处理的核心入口 |
| **216** | `v3_result = route(text)` | **V3 意图路由决策**，查看返回的 decision |
| **217** | `decision = v3_result["decision"]` | 关键分支判断：direct_answer / route_v1 / route_v2 |
| **218** | `style_id = v3_result.get("style_id")` | 提取款号 |
| **224-241** | if-elif 分支处理 | 查看进入哪个分支 |
| **225** | `_handle_direct_answer()` | 直接回答分支 |
| **228-231** | `_handle_route_v1()` | V1 时间线分析分支 |
| **234** | `_handle_route_v2()` | V2 多轮查询分支（最复杂） |
| **244** | `_build_session_flow()` | 构建完整 session_flow |
| **254** | `yield {"event": "delta", ...}` | SSE 输出最终回答 |
| **257-271** | `yield {"event": "done", ...}` | 输出完成事件，含 session_flow 和 truncation_info |

---

## 四、V3 意图路由 `agents/intent_router.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **181** | `route()` 入口 | 完整路由函数 |
| **195** | `is_continuation(text)` | 检测续查意图 |
| **203** | `classify_intent(text, session_style_id)` | 调用 V3 模型进行意图识别 |
| **86** | `extract_style_id(text)` | 从文本中提取款号（正则匹配） |
| **98** | `call_v3(text)` | **调用 V3 模型**，查看返回的原始 JSON |
| **101** | `decision = v3_result.get("decision")` | V3 决策结果 |
| **206-211** | 决策映射逻辑 | general_chat→direct_answer, 有款号→route_v1, 其他→route_v2 |

---

## 五、V2 多轮编排 `agents/v2_orchestrator.py` ⭐最复杂

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **39** | `orchestrate_v2_query()` 入口 | V2 多轮查询核心 |
| **62-70** | messages 初始化 | 查看 system prompt + 用户问题 |
| **75** | `for round_num in range(MAX_V2_ROUNDS)` | 多轮循环开始 |
| **77** | `v2_output = call_v2_messages(messages)` | **调用 V2 模型**，查看输出 |
| **79-80** | `v2_content = json.dumps(v2_output)` | V2 输出的 thought + satisfied + function_calls |
| **83** | `if v2_output.get("satisfied", False)` | 判断是否满足停止条件 |
| **86-89** | `function_calls[0].get("name") == "generate_answer"` | V2 决定生成最终回答 |
| **93-97** | `function_calls` 为空处理 | 降级处理 |
| **100** | `raw_result = executor.execute(function_calls)` | **执行查询工具** |
| **107-108** | `cm.check_content_overflow()` | 上下文溢出检测 |
| **110-129** | 需要截断时的处理 | 调用 ResultTruncator |
| **124-129** | `truncator.truncate()` | 结果截取 |
| **136-144** | messages 追加 | 将 assistant + tool 结果加入上下文 |

---

## 六、V2 执行引擎 `services/v2_executor.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **233** | `execute()` 入口 | 执行 V2 的 function_calls |
| **251-257** | `generate_answer` 快速路径 | V2 直接要求生成回答 |
| **260** | `_match_chain_rule()` | 匹配查询链配置（一级+二级） |
| **271** | `_execute_chain()` | 执行查询链 |
| **277** | `_execute_call(primary_call)` | 执行一级查询 |
| **289-292** | `_extract_dependency_value()` | 从一级结果提取依赖值（如 style_ids） |
| **302-304** | `_expand_secondary_calls()` | 批量展开二级调用 |
| **310-336** | `ThreadPoolExecutor` 并行执行二级 | 查看每个二级查询结果 |
| **356** | `_execute_single()` | 单轮独立执行（无依赖关系） |
| **387-400** | `_execute_call()` | 根据 name 分发到 kg_query / rag_query |
| **402-460** | `_execute_kg()` | KG 查询分发（11种 type） |
| **462-515** | `_execute_rag()` | RAG 查询分发（4种 type） |

---

## 七、KG 适配器 `services/kg_adapter.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **17** | `_get_kg_engine()` | 懒加载 KG 引擎，查看是否成功加载 |
| **64-75** | `query_styles_by_person()` | 查人员款号 |
| **78-89** | `query_timeline()` | 查款号时间线 |
| **147-169** | `query_collaborators()` | 查协作对象 |
| **172-194** | `query_styles_by_factory()` | 查工厂款号 |
| **221-262** | `find_styles_with_conditions()` | 多条件筛选 |
| **265-296** | `query_person_styles_with_stats()` | 人员款号统计（V2 款号列表） |
| **299-338** | `get_style_overview()` | 款号综合概览 |

---

## 八、RAG 适配器 `services/rag_adapter.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **17** | `_get_chroma_client()` | 懒加载 ChromaDB |
| **41** | `_get_embedding_function()` | 加载 Embedding 模型 |
| **74-116** | `query_terms()` | 术语查询（直接查 ChromaDB） |
| **119-151** | `translate_term()` | 术语翻译 |
| **213-335** | `query_email_events()` | **邮件事件查询**（最常用） |
| **254-265** | 模式1/2: 款号精确查询（走 JSON） | 查看 filtered 结果 |
| **268-333** | 模式3/4: 语义检索（走 ChromaDB） | 查看向量检索结果 |
| **293** | `query_embeddings = ef([enhanced_query])` | 生成查询向量 |
| **294-299** | `collection.query()` | ChromaDB 向量查询 |
| **302-329** | 结果组装 | 查看每条 event 的字段 |

---

## 九、V1 编排器 `agents/v1_orchestrator.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **34** | `orchestrate_v1_analysis()` 入口 | V1 时间线分析 |
| **51** | `events = query_email_events(style_id)` | 查 ChromaDB 获取事件 |
| **57** | `events = sorted(events, key=lambda e: e.get("date", ""))` | 按日期排序 |
| **60** | `_split_into_rounds()` | 分轮（每轮60个事件） |
| **65-73** | `for round_num, round_events in enumerate(rounds)` | 串行调 V1 |
| **66** | `call_v1_model(...)` | **调用 V1 模型** |
| **76** | `_merge_reports()` | 合并多轮报告 |

---

## 十、V1 模型适配器 `services/v1_model_adapter.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **67** | `call_v1_model()` 入口 | 调用 V1 本地模型 |
| **90-95** | `build_v1_input_json() + build_v1_prompt()` | 构造 V1 输入 |
| **99** | `call_v1(prompt)` | **调用 vLLM V1 模型** |
| **102-104** | 异常降级 | V1 调用失败时返回降级报告 |

---

## 十一、上下文管理 `services/context_manager.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **69-90** | `estimate_tokens()` | token 估算（中文按字符） |
| **100-127** | `check_overflow()` | 检查上下文是否溢出 |
| **129-146** | `check_content_overflow()` | 添加新内容后检查 |
| **148-176** | `calculate_max_items()` | 计算剩余空间允许的最大 item 数 |
| **217-248** | `build_truncation_feedback()` | 构建带警告的反馈文本 |

---

## 十二、结果截断 `services/result_truncator.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **155** | `truncate()` 入口 | 截取入口 |
| **177** | `rule = self.RULES.get(query_type)` | 获取截取规则 |
| **198-203** | 提取主列表字段 | 查看原始数据长度 |
| **206-210** | 采样策略执行 | HEAD / BY_STAGE / BY_DELAY / BY_SCORE / BY_DATE |
| **213** | `_build_result()` | 构造截取后的数据 |
| **215-224** | 返回 TruncationResult | 查看 truncated_data, omitted_data, truncation_note |

---

## 十三、回答生成 `services/answer_generator.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **181** | `generate_answer()` 入口 | 根据模板生成 Markdown |
| **193-200** | 模板匹配 + 渲染 | 查看 template 和 data |
| **14-49** | `_render_my_styles_summary()` | 我的款号汇总模板 |
| **109-126** | `_render_term_translation()` | 术语翻译模板 |
| **145-164** | `_render_not_found()` | 未找到模板 |

---

## 十四、续查处理 `routers/chat.py`

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **174** | `_handle_continuation_stream()` 入口 | 续查 SSE 流处理 |
| **195-198** | 查找 OmittedData | 读取剩余数据 |
| **211** | `remaining_data = json.loads(omitted.remaining_data)` | 剩余数据列表 |
| **235-245** | `truncator.truncate()` | 截取下一页 |
| **248** | `_build_continuation_answer()` | 构建续查回答 |
| **262** | `omitted.remaining_data = json.dumps(...)` | 更新剩余数据 |

---

## 十五、vLLM 客户端 `services/vllm_client.py` ⭐模型调用

| 行号 | 函数 | 断点理由 |
|------|------|----------|
| **25** | `get_client()` | 获取 OpenAI 客户端 |
| **40** | `call_model()` | 通用模型调用 |
| **79** | `_call_model_with_messages()` | 传入完整 messages |
| **108-118** | `client.chat.completions.create()` | **实际 HTTP 调用 vLLM** |
| **157** | `call_v3()` | 调用 V3（意图路由） |
| **168** | `call_v2_messages()` | 调用 V2（多轮查询） |
| **194** | `call_v1()` | 调用 V1（时间线分析） |

---

## 🎯 推荐的最小断点集（快速定位问题）

如果你只想打最关键的断点，建议按以下顺序：

| 优先级 | 文件 | 行号 | 说明 |
|--------|------|------|------|
| ⭐⭐⭐ | `agents/chat_agent.py` | **216** | V3 路由决策 |
| ⭐⭐⭐ | `agents/v2_orchestrator.py` | **77** | V2 模型输出 |
| ⭐⭐⭐ | `services/v2_executor.py` | **233** | 查询执行入口 |
| ⭐⭐⭐ | `services/vllm_client.py` | **118** | 实际模型 HTTP 调用 |
| ⭐⭐⭐ | `services/kg_adapter.py` | **17** | KG 引擎加载 |
| ⭐⭐⭐ | `services/rag_adapter.py` | **17** | ChromaDB 加载 |
| ⭐⭐ | `routers/chat.py` | **103** | Agent 入口 |
| ⭐⭐ | `agents/intent_router.py` | **98** | V3 模型调用 |
| ⭐⭐ | `services/v2_executor.py` | **100** | 工具执行结果 |
| ⭐ | `services/result_truncator.py` | **155** | 结果截断 |

---

## 💡 调试技巧

1. **打印 session_flow**：在 `chat_agent.py:244` 处打印 `session_flow`，可以看到完整的 user→v3→v2→tool→assistant 链路。

2. **查看数据库**：对话完成后查 SQLite 的 `messages` 表，可以看到所有中间步骤：
   ```bash
   sqlite3 email_agent/agent.db "SELECT role, substr(content,1,100) FROM messages WHERE session_id='xxx' ORDER BY created_at;"
   ```

3. **模拟 V3 决策**：在 `intent_router.py:216` 处临时修改 `v3_result` 来测试不同分支。

4. **V2 多轮追踪**：在 `v2_orchestrator.py:75` 的循环内打印 `round_num` 和 `messages` 长度，观察多轮累积。

5. **工具执行时间**：在 `v2_executor.py:310` 的 ThreadPoolExecutor 处记录耗时，排查慢查询。
