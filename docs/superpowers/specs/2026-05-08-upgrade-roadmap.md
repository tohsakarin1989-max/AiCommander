# AiCommander 升级路线图

> 生成日期：2026-05-08
> 来源：头脑风暴 + 业务场景深度拆解

---

## 总览

本次升级聚焦三个方向，按依赖关系分四个阶段落地：

```
Phase 1  地图与数据基础设施补全          （前置，其余功能依赖此阶段）
Phase 2  犯罪链条自动关联引擎            （核心新功能，业务价值最高）
Phase 3  AI 辅助案件录入                （降低录入门槛，提升数据质量）
Phase 4  分析知识沉淀与检索              （积累经验，提升圆桌会议质量）
```

---

## Phase 1：地图与数据基础设施补全

### 业务目标

犯罪链条功能依赖两个前提：
1. 案件必须有坐标，否则无法计算地理距离
2. 地图必须能区分三类案件（盗采 / 运输 / 囤储），否则链条可视化无意义

这一阶段不新增业务功能，只补全基础能力缺口。

---

### 1-A  坐标数据补全

**问题**：`CasesMap` 页面已显示"标记点：X / Y 件含坐标"，说明大量历史案件缺少经纬度。

**方案**：在案件列表页新增"批量补录坐标"入口，管理员可批量筛选无坐标案件，逐一在地图上点选位置保存。

**实现细节**

后端：
- `PATCH /api/cases/{id}/location` 接口，只更新 `latitude` / `longitude`，不触碰其他字段
- 新增 `GET /api/cases?missing_location=true` 筛选参数，方便前端拉取无坐标案件列表

前端：
- Cases 列表页顶部新增"坐标补录"按钮，仅管理员可见
- 进入补录模式：左侧列出无坐标案件，右侧显示地图，点击列表项 → 地图进入拾取模式 → 点击地图确认坐标 → 自动跳下一条
- 进度提示：已补录 X / 待补录 Y

**注意细节**
- `MapPicker` 组件已存在，可直接复用，不要重新写地图拾取逻辑
- 保存时做坐标合法性校验（经度 73~135，纬度 18~53，覆盖中国范围）
- 补录操作记录操作人和时间，写入 case 的 updated_at

**TODO**
- [ ] 后端：`PATCH /api/cases/{id}/location` 接口
- [ ] 后端：`missing_location` 筛选参数
- [ ] 前端：补录模式入口（仅管理员）
- [ ] 前端：补录列表 + 地图拾取联动 UI
- [ ] 前端：进度显示
- [ ] 校验：坐标范围合法性

---

### 1-B  案件类型与链条位置映射

**问题**：三类案件（盗采 / 运输 / 囤储）在系统里没有统一的"链条位置"字段，需要从现有字段推断。

**映射规则**（基于 `facility_type` 字段）：

| facility_type | 链条位置 | 地图图标 |
|--------------|---------|---------|
| 管线 | 盗采（upstream） | 红色六边形 |
| 油罐车 | 运输（midstream） | 黄色菱形 |
| 油库 | 囤储（downstream） | 蓝色方形 |
| 加油站 | 囤储（downstream） | 蓝色方形 |
| 其他 / 未知 | 未分类 | 灰色圆形 |

**实现细节**

后端：
- `app/utils/chain_classifier.py`：纯函数 `classify_chain_position(case) -> Literal['upstream', 'midstream', 'downstream', 'unknown']`
- 不新增数据库字段，分类结果在运行时计算，避免数据冗余

前端：
- `frontend/src/utils/chainType.ts`：同样的映射逻辑，供地图图标渲染使用
- 案件详情页在案件类型旁显示链条位置标签（"盗采环节" / "运输环节" / "囤储环节"）

**注意细节**
- `facility_type` 可能为空或"其他"，分类器必须对 `unknown` 情况有明确处理，不能崩溃
- 未来如果业务定义扩展（如新增"炼制"环节），只改映射表，不改调用方

**TODO**
- [ ] 后端：`app/utils/chain_classifier.py`
- [ ] 前端：`chainType.ts` 映射工具函数
- [ ] 前端：案件详情页链条位置标签
- [ ] 测试：覆盖所有 facility_type 枚举值的分类结果

---

### 1-C  地图图标分类

**问题**：`LeafletMap` 目前所有标记点外观只按 `riskLevel` 着色，三类案件在地图上无法区分。

**实现细节**

修改 `LeafletMap.tsx`：
- 新增 `chainPosition?: 'upstream' | 'midstream' | 'downstream' | 'unknown'` 到 `CaseMarker` 类型
- `makeCircleIcon` 升级为 `makeCaseIcon`，根据 `chainPosition` 返回不同形状 + 颜色的 `DivIcon`：
  - upstream：红色六边形 SVG
  - midstream：黄色菱形 SVG
  - downstream：蓝色方形 SVG
  - unknown：灰色圆形（保留现有样式）
- 图例同步更新，显示三类案件说明

修改 `CasesMap.tsx`：
- 构建 `markers` 时，调用 `chainType.ts` 补充 `chainPosition` 字段
- 图层控制区增加三个复选框，可分别显示 / 隐藏三类案件

**注意细节**
- 图标不要只靠颜色区分（考虑色盲用户），形状也必须不同
- 图标尺寸保持一致（18px），避免视觉混乱
- `LeafletMap` 是通用组件，改动要向后兼容——`chainPosition` 为可选字段，不传时降级为原有圆形图标

**TODO**
- [ ] `types/index.ts`：`CaseMarker` 增加 `chainPosition` 可选字段
- [ ] `LeafletMap.tsx`：`makeCaseIcon` 按类型生成不同形状图标
- [ ] `CasesMap.tsx`：构建 markers 时补充 `chainPosition`
- [ ] `CasesMap.tsx`：图层控制增加三类案件开关
- [ ] 图例更新

---

## Phase 2：犯罪链条自动关联引擎

### 业务目标

涉油犯罪存在固定操作链：**盗采现场 → 运输车辆 → 囤储点**。

每当新案件入库，系统自动在链条上下游寻找关联案件，生成推断假设，无需任何人工触发。有关联就提示，没有就静默。侦查人员可确认或驳回推断，确认后形成正式串案记录。

---

### 2-A  后端：链条关联服务

**数据模型**：新增 `ChainLink` 表

```python
class ChainLink(Base):
    id: int
    case_id_a: int          # 上游案件
    case_id_b: int          # 下游案件
    link_type: str          # 'upstream_transport' | 'transport_storage'
    status: str             # 'inferred' | 'confirmed' | 'rejected'
    confidence: float       # 0~1，基于距离和时间差计算
    distance_km: float      # 两案件间直线距离
    time_diff_days: int     # 时间差（天）
    created_at: datetime
    confirmed_by: str       # 确认人（status=confirmed 时填写）
    confirmed_at: datetime
```

**服务**：`app/services/chain_analysis_service.py`

核心方法：
```python
def scan_chain_links(case_id: int, db: Session) -> list[ChainLink]:
    """案件入库后调用，扫描并生成推断链接"""

def confirm_link(link_id: int, operator: str, db: Session) -> ChainLink:
    """人工确认推断为真实关联"""

def reject_link(link_id: int, db: Session) -> ChainLink:
    """人工驳回推断"""

def get_chain_context(case_id: int, db: Session) -> dict:
    """获取案件的完整链条上下文，供圆桌会议使用"""
```

**匹配算法**：

```python
# 扫描逻辑（伪代码）
position = classify_chain_position(new_case)

if position == 'midstream':  # 运输车辆
    # 向上：找周边盗采案件
    candidates = query_cases(
        position='upstream',
        within_km=config.chain_radius_km,        # 默认 20，可配置
        within_days=config.chain_time_window_days # 默认 180，可配置
    )
    # 向下：找周边囤储案件
    candidates += query_cases(position='downstream', ...)

elif position == 'upstream':  # 盗采现场
    # 向下：找周边运输车辆
    candidates = query_cases(position='midstream', ...)

elif position == 'downstream':  # 囤储点
    # 向上：找周边运输车辆
    candidates = query_cases(position='midstream', ...)
```

**置信度计算**：
```
confidence = 1 - (distance_km / max_radius) * 0.5
           - (time_diff_days / max_days) * 0.3
           - (已被驳回同类推断次数) * 0.2
```
距离越近、时间差越小、同类推断被驳回次数越少 → 置信度越高

**触发时机**：在 `POST /api/cases` 和 `PUT /api/cases/{id}` 成功后异步触发，不阻塞响应。用现有 Celery 任务队列异步执行。

**配置参数**（写入 system_config 表，可在设置页面调整）：
- `chain_radius_km`：默认 20
- `chain_time_window_days`：默认 180
- `chain_min_confidence`：默认 0.3（低于此值的推断不显示）

**API 接口**：
```
GET  /api/chain-links?case_id={id}         获取案件的所有链条关联
POST /api/chain-links/{id}/confirm         确认推断
POST /api/chain-links/{id}/reject          驳回推断
GET  /api/chain-links/map-data             获取地图用链条连线数据
```

**注意细节**
- `scan_chain_links` 必须幂等：重复调用不生成重复记录（用 case_id_a + case_id_b + link_type 做唯一约束）
- 无坐标的案件直接跳过，不报错
- 驳回的链接不重复生成（记录驳回状态，下次扫描跳过）
- 链条扫描失败不影响案件保存，异步任务失败记日志即可

**TODO**
- [ ] 数据库：`ChainLink` 模型 + Alembic 迁移
- [ ] `chain_classifier.py`：链条位置分类工具
- [ ] `chain_analysis_service.py`：`scan_chain_links` 核心算法
- [ ] `chain_analysis_service.py`：`confirm_link` / `reject_link`
- [ ] `chain_analysis_service.py`：`get_chain_context`（供圆桌会议注入）
- [ ] Celery Task：案件保存后异步触发扫描
- [ ] API：`/api/chain-links` 全套接口
- [ ] `system_config`：写入三个可配置参数默认值
- [ ] 唯一约束：防止重复生成相同链接
- [ ] 单元测试：覆盖距离/时间边界条件

---

### 2-B  前端：案件详情页链条面板

**位置**：案件详情页新增"链条关联"Tab 或折叠区块

**展示内容**：

```
⚠️  疑似链条关联（系统自动推断）

  ┌─ 上游关联
  │  [盗采] 2024-09-21  XX管线 km23    距离 8.2km  时间差 12天
  │  推断：本案运输车辆可能从该盗采点取油
  │  [确认]  [驳回]
  │
  └─ 下游关联
     [囤储] 2024-11-03  某村屯囤油点   距离 15.1km  时间差 43天
     推断：本案运输车辆可能为该囤储点供货
     [确认]  [驳回]

✅  已确认关联（1 条）
  [囤储] 2024-08-15  XX油库    距离 6.3km
```

**交互**：
- 点击关联案件 → 跳转到该案件详情页
- "确认"按钮 → 乐观更新 UI，后台调用 confirm API
- "驳回"按钮 → 该条推断消失，不再出现

**注意细节**
- 确认/驳回操作要有 loading 状态，防止重复提交
- 驳回后前端立即移除该条目（乐观更新），失败时恢复
- 置信度低于 0.5 的推断加灰色标注"低可信度"，提醒用户谨慎参考

**TODO**
- [ ] 案件详情页：链条关联 UI 区块
- [ ] `caseApi`：新增 `getChainLinks(caseId)` / `confirmLink(id)` / `rejectLink(id)`
- [ ] 确认/驳回的乐观更新逻辑
- [ ] 低置信度视觉标注

---

### 2-C  前端：地图链条可视化

**在现有 `LeafletMap` 基础上扩展**：

新增 `chainLinks` prop：
```typescript
interface ChainLinkLine {
  fromCaseId: number
  toCaseId: number
  status: 'inferred' | 'confirmed'
  confidence: number
}
```

渲染规则：
- `inferred`：橙色虚线，透明度随置信度变化（置信度越低越淡）
- `confirmed`：绿色实线，带箭头指向下游

**交互**：
- 点击地图上的案件标记 → 高亮该案件的所有链条连线，其余标记变暗
- 同时显示以该案件为圆心的搜索半径圆（灰色虚线圆，半径 = `chain_radius_km`）
- 再次点击 → 取消高亮，恢复全图

**CasesMap 页面**：
- 图层控制区新增"链条关联线"开关（默认开启）
- 右侧面板"串案关联"区块改为"链条推断"，展示当前地图范围内的推断数量和已确认数量

**注意细节**
- 案件数量多时，大量链条线会造成视觉混乱——默认只显示置信度 > 0.5 的链条线
- 半径圆只在选中某个案件时显示，不要常驻
- 链条线要在案件标记点图层之下，避免遮挡点击热区

**TODO**
- [ ] `LeafletMap.tsx`：新增 `chainLinks` prop
- [ ] `LeafletMap.tsx`：推断线（橙色虚线）+ 确认线（绿色实线带箭头）渲染
- [ ] `LeafletMap.tsx`：点击高亮 + 半径圆交互
- [ ] `CasesMap.tsx`：拉取链条数据并传入 `LeafletMap`
- [ ] `CasesMap.tsx`：图层控制新增链条开关
- [ ] 性能：链条线数量超过 50 条时做剔除（只保留置信度最高的 N 条）

---

### 2-D  圆桌会议注入链条上下文

**目标**：启动圆桌会议时，自动将该案件的链条关联案件作为背景上下文注入，让 AI 分析更有依据。

**实现**：
- `meeting_manager.py` 启动时调用 `chain_analysis_service.get_chain_context(case_id)`
- 将链条上下文拼入 analyst prompt 的背景信息部分：
  ```
  【链条关联背景】
  本案可能属于同一犯罪链条的关联案件：
  - [上游] 2024-09-21 XX管线盗采案（距离8.2km，时间差12天，置信度0.82）
  - [下游] 2024-11-03 某村囤油点案（距离15.1km，时间差43天，置信度0.71）
  ```
- 仅注入 `status=confirmed` 或 `confidence > 0.6` 的关联

**注意细节**
- 链条上下文字数不要太长，提炼关键信息即可，不要把关联案件全文塞进去
- 如果没有任何链条关联，不注入该段落，不影响正常会议流程

**TODO**
- [ ] `meeting_manager.py`：启动时注入链条上下文
- [ ] 链条上下文格式化函数
- [ ] 测试：无链条关联时会议正常进行

---

## Phase 3：AI 辅助案件录入

### 业务目标

现在案件录入需要填写大量结构化字段，前线人员往往知道案情但不熟悉系统字段。支持用户输入一段自然语言描述，AI 自动解析并填充表单，用户只需核对和补充。

---

### 3-A  后端：自然语言解析接口

**接口**：`POST /api/cases/parse-description`

**请求**：
```json
{ "description": "2024年9月21日下午三点，在XX村附近XX管线km23处发现两名男子正在盗采原油，现场查获油罐车一辆，车牌冀B12345，估计涉案原油约2吨..." }
```

**响应**：
```json
{
  "extracted": {
    "occurred_time": "2024-09-21T15:00:00",
    "location_description": "XX村附近XX管线km23处",
    "case_type": "盗油",
    "facility_type": "管线",
    "oil_type": "原油",
    "oil_quantity": 2.0,
    "modus_operandi": "盗采",
    "vehicles": [{ "plate_number": "冀B12345", "vehicle_type": "油罐车" }]
  },
  "confidence": {
    "occurred_time": 0.95,
    "oil_quantity": 0.7
  },
  "unparsed": "部分信息无法确认：涉案人员姓名未提及"
}
```

**实现**：
- 复用现有 `model_factory.py`，调用已配置的 LLM
- System prompt 固定为结构化提取指令，输出 JSON Schema
- 使用 JSON mode / structured output 确保返回格式稳定
- 解析失败时返回空 extracted，不抛出 500

**注意细节**
- AI 不能凭空捏造字段——prompt 中明确要求：不确定的字段返回 null，不要推断
- `confidence` 字段帮助前端决定是否高亮提示用户核对
- 此接口不保存任何数据，只返回解析结果，保存动作由用户确认后的正常 case 创建接口完成
- 接口响应时间可能 3~5 秒，前端要显示 loading

**TODO**
- [ ] 后端：`/api/cases/parse-description` 接口
- [ ] LLM prompt：结构化提取指令 + JSON Schema 输出约束
- [ ] 解析结果验证：类型检查、范围检查
- [ ] 测试：正常解析、部分字段缺失、完全无法解析三种情况

---

### 3-B  前端：案件表单自然语言模式

**在现有案件创建/编辑表单顶部新增**：

```
[切换到自然语言录入]

┌─────────────────────────────────────┐
│ 描述案情（AI 将自动填写下方表单）      │
│                                     │
│ 2024年9月21日...                    │
│                                     │
└─────────────────────────────────────┘
           [AI 解析填充]
```

解析完成后：
- 自动填充能解析的字段
- 已被 AI 填充的字段显示黄色背景 + "AI填充，请核对"提示
- 置信度低的字段加感叹号标注
- 用户可正常编辑任何字段

**注意细节**
- AI 填充是辅助，不是替代——用户必须自己检查并提交，不能"一键保存"跳过核对步骤
- 文本框内容不要在解析后自动清空，用户可能需要对照原文核对
- 自然语言模式和手动模式可随时切换，切换不丢失已填数据

**TODO**
- [ ] 案件表单：自然语言输入区块
- [ ] `caseApi`：新增 `parseDescription(text)` 方法
- [ ] 表单字段：AI 填充高亮样式
- [ ] 置信度低字段的警示标注
- [ ] 测试：解析结果正确映射到对应表单字段

---

## Phase 4：分析知识沉淀与检索

### 业务目标

每次圆桌会议、每次部署建议、每次链条确认，都是宝贵的经验。目前这些结论各自孤立，新会议无法参考历史经验。本阶段将这些结论积累为可检索的知识库，让系统越用越聪明。

---

### 4-A  后端：知识沉淀入库

**触发时机**：
1. 圆桌会议 `status` 变为 `completed` → 自动将最终报告入库
2. 链条关联被 `confirmed` → 将确认记录入库
3. 部署建议被"标记为有效" → 入库（需新增此交互，见 4-C）

**实现**：
- 系统已有 `embedding_service.py` 和 `vector_db_service.py`，直接复用
- 新增 `knowledge_service.py`，封装"入库"和"检索"两个核心方法：

```python
def store_analysis(content: str, metadata: dict, db: Session) -> str:
    """将分析文本向量化并存储"""
    embedding = embedding_service.embed(content)
    vector_db_service.upsert(embedding, metadata)

def retrieve_similar(case: Case, top_k: int = 3, db: Session) -> list[dict]:
    """根据案件特征检索相似历史分析"""
    query = f"{case.case_type} {case.facility_type} {case.location_description}"
    embedding = embedding_service.embed(query)
    return vector_db_service.search(embedding, top_k=top_k)
```

**metadata 结构**：
```json
{
  "type": "meeting_report | chain_confirmed | deployment",
  "case_id": 123,
  "area": "XX区域",
  "case_type": "盗油",
  "facility_type": "管线",
  "created_at": "2024-09-21",
  "summary": "前50字摘要"
}
```

**注意细节**
- 入库失败不影响主流程（会议完成时异步触发，Celery 任务）
- 相同案件的报告重复入库需做去重（用 case_id + type 做 upsert key）
- 向量库未就绪时降级处理：`retrieve_similar` 返回空列表，不报错（现有代码已有此注释提示）

**TODO**
- [ ] `knowledge_service.py`：`store_analysis` + `retrieve_similar`
- [ ] 圆桌会议完成 hook：异步触发入库
- [ ] 链条确认 hook：触发入库
- [ ] API：`GET /api/knowledge/similar?case_id={id}` 供前端调用
- [ ] 去重逻辑

---

### 4-B  前端：圆桌会议历史参考

**在会议启动前的配置页，新增"历史参考"区块**：

```
📚 历史相似分析（系统自动检索）

  ► 2024-08-12  XX管线附近案件圆桌会议
    "该区域在早班时段盗采频次较高，建议加强6-9时巡逻..."
    [查看完整报告]

  ► 2024-06-30  同类设施盗采案件研判
    "运输车辆多为深色SUV，作案后向北方向撤离..."
    [查看完整报告]
```

**在案件详情页新增"相关经验"面板**：
- 展示与该案件相似的历史分析结论（top 3）
- 每条显示：时间、摘要、来源类型（会议 / 部署建议 / 链条确认）
- 点击可展开查看完整内容

**注意细节**
- 检索结果不一定准确，加"仅供参考"标注
- 检索接口较慢（需向量计算），使用懒加载，不阻塞页面主体
- 无历史数据时不显示该区块，不显示"暂无数据"占位

**TODO**
- [ ] 圆桌会议配置页：历史参考区块（懒加载）
- [ ] 案件详情页：相关经验面板
- [ ] `aiApi`：新增 `getSimilarAnalyses(caseId)` 方法
- [ ] 懒加载 + 骨架屏

---

### 4-C  部署建议效果标记（轻量闭环）

**业务目标**：为知识沉淀提供效果反馈，让系统知道哪些建议是有效的。

**做法**：在部署建议页，每条建议旁新增简单的反馈按钮：
- "已采纳" → 记录采纳状态
- "该区域近期无新案" → 触发入库，作为"有效建议"知识

**注意细节**
- 这不是严格的效果验证（项目还在开发，数据不足），只是为将来积累标注数据
- 交互要轻，不增加用户负担：一个下拉或简单按钮组即可
- 当前阶段优先级低，可放在 Phase 4 最后实现

**TODO**
- [ ] 部署建议页：每条建议加反馈按钮
- [ ] 后端：记录采纳状态字段
- [ ] 采纳后触发知识入库

---

## 各阶段依赖关系

```
Phase 1（基础）
  ├── 1-A 坐标补全     ←── Phase 2 的数据前提
  ├── 1-B 类型映射     ←── Phase 2 的分类前提
  └── 1-C 图标分类     ←── Phase 2-C 的视觉前提

Phase 2（核心）
  ├── 2-A 后端服务     ←── 2-B / 2-C / 2-D 的数据来源
  ├── 2-B 详情面板     独立，依赖 2-A
  ├── 2-C 地图可视化   依赖 1-C + 2-A
  └── 2-D 会议注入     依赖 2-A

Phase 3（独立）         可与 Phase 2 并行开发

Phase 4（积累）         依赖 Phase 2 产生数据
```

## 推荐开发顺序

```
1-B → 1-A → 1-C → 2-A → 2-B → 2-C → 2-D
                               ↑
                          Phase 3 可并行
                                        ↓
                                    Phase 4
```

---

## 风险提示

| 风险 | 影响 | 应对 |
|------|------|------|
| 历史案件坐标缺失率过高 | Phase 2 覆盖率低 | Phase 1-A 优先做，上线前统计缺失率 |
| `facility_type` 字段数据不规范 | 链条分类失准 | 分类器做宽松匹配 + unknown 兜底 |
| 向量库服务未就绪 | Phase 4 功能缺失 | 降级为空返回，不阻塞主流程 |
| 链条推断误报率高 | 用户信任度下降 | 置信度阈值可调，推断结果标注"仅供参考" |
| LLM 解析速度慢（Phase 3） | 录入体验差 | loading 提示 + 可中途取消 |
