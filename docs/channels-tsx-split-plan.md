# Channels.tsx 拆分方案

分析文件：`/www/wwwroot/zoaholic_original/frontend/src/pages/Channels.tsx`

当前文件共 6698 行。本文只给拆分方案，不修改业务代码。

## 1. 代码结构梳理

### 1.1 总体结构

| 区间 | 内容 |
| --- | --- |
| 1-39 | import。依赖 React、Radix Dialog/Switch、lucide-react、Toast、已有弹窗组件、ProviderLogo、virtualModels 与 keyRules 工具。 |
| 41-140 | 顶层小组件：DeferredInput、KeyLabelOverlay。 |
| 142-258 | 表单、渠道、虚拟模型、拖拽等类型定义。 |
| 260-565 | 调度常量、preferences 工具、余额与额度数据转换工具、provider 工具。 |
| 567-681 | 余额背景色、标签样式、倒计时、圆角路径、QuotaBorderOverlay。 |
| 698-840 | UI slot 动态加载体系与 UiSlot 组件。 |
| 842-1432 | Key 行、机房模式卡片、圆环组件。 |
| 1435-6698 | Channels 主组件。包含数据加载、编辑抽屉、OAuth、Key 管理、虚拟模型、列表筛选、列表渲染、所有 Dialog。 |

### 1.2 类型定义

| 类型 | 起止行号 | 行数 | 说明 |
| --- | ---: | ---: | --- |
| ApiKeyObj | 143-147 | 5 | API Key 表单对象。 |
| ModelMapping | 149-152 | 4 | 模型别名映射。 |
| HeaderEntry | 154-157 | 4 | 自定义请求头表单行。 |
| SubChannelFormData | 159-173 | 15 | 子渠道表单对象。 |
| ProviderFormData | 175-198 | 24 | 主渠道编辑表单对象。 |
| UiSlotValue | 200-200 | 1 | 渠道 UI slot 的脚本值类型。 |
| ChannelOption | 202-217 | 16 | 后端渠道注册表选项。 |
| PluginOption | 219-227 | 9 | 拦截器插件选项。 |
| VirtualModelChainNode | 232-236 | 5 | 虚拟模型链条节点。 |
| VirtualModelConfig | 238-241 | 4 | 虚拟模型配置。 |
| ProviderModelOption | 246-250 | 5 | 渠道模型展示项。 |
| VirtualDragPayload | 255-258 | 4 | 虚拟模型拖拽 payload。 |
| QuotaGauge | 288-304 | 17 | 统一额度圆环数据。 |
| RowQuota | 306-311 | 6 | Key 行额度模型。 |
| BalanceResult | 313-346 | 34 | 余额查询结果。 |
| OAuthQuota | 351-355 | 5 | OAuth 双额度兼容模型。 |
| Segment | 4137-4137 | 1 | Channels 内部真实渠道列表分段类型。 |

### 1.3 常量定义

| 常量 | 行号 | 说明 |
| --- | ---: | --- |
| SCHEDULE_ALGORITHMS | 260 | Key 调度策略选项。 |
| BALANCE_FILL_COLORS | 567 | 普通余额背景条颜色。 |
| TAG_CLASSES | 573 | 余额标签颜色。 |
| QuotaArcs | 684 | const 形式的组件，当前基本为兼容残留。 |
| uiSlotCache | 702 | UI slot 动态 import 缓存。 |
| UiSlot | 754 | const 形式的组件。 |
| RACK_ARC_LENGTH | 948 | 机房模式圆环有效弧长。 |
| RACK_GAP_LENGTH | 949 | 机房模式圆环缺口长度。 |
| RACK_RING_PATH_LENGTH | 950 | 机房模式圆环总 pathLength。 |
| QUOTA_GAUGE_TONE_STROKES | 1095 | QuotaGauge tone 到 stroke 色的映射。 |

### 1.4 工具函数（非组件函数）

| 函数 | 起止行号 | 行数 | 说明 |
| --- | ---: | ---: | --- |
| readBooleanPreference | 268-274 | 7 | 读取并归一化布尔偏好。 |
| serializeChannelPreferences | 276-285 | 10 | 保存前清理 preferences，尤其是 key_rules。 |
| formatCompactNumber | 357-365 | 9 | 数字缩写显示。 |
| getBalancePercent | 367-377 | 11 | 从 BalanceResult 计算百分比。 |
| getBalanceColor | 379-384 | 6 | 按余额百分比分档。 |
| getBalanceLabel | 386-398 | 13 | 完整行余额标签。 |
| getBalanceCompactLabel | 400-412 | 13 | 机房卡片紧凑余额标签。 |
| normalizeQuotaPct | 414-422 | 9 | 额度百分比归一化。 |
| getQuotaFromSource | 424-434 | 11 | 从新旧字段读取双额度。 |
| getOAuthQuota | 436-441 | 6 | 读取 OAuth 账号额度。 |
| normalizeOAuthAccountStateMap | 443-458 | 16 | 归一化 OAuth 账号状态 map。 |
| getBalanceQuota | 460-466 | 7 | 从余额结果读取双额度。 |
| getQuotaPairFromGauges | 468-477 | 10 | 从 gauges 提取双额度。 |
| buildRowQuota | 479-524 | 46 | 生成 Key 行统一额度模型。 |
| buildRowQuotaSlotData | 526-537 | 12 | 为 UI slot 构造兼容数据。 |
| withRackCompactBalanceFallback | 539-547 | 9 | 机房模式压缩旧余额显示。 |
| sortProvidersByWeight | 549-558 | 10 | 渠道按权重降序排序。 |
| buildProviderApiPath | 560-565 | 6 | 生成单 provider API 路径。 |
| formatCountdown | 580-588 | 9 | 冷却倒计时格式化。 |
| buildRoundRectPath | 591-604 | 14 | SVG 圆角矩形路径。 |
| buildTopHalfPath | 609-619 | 11 | 双额度上半边框路径。 |
| buildBottomHalfPath | 623-633 | 11 | 双额度下半边框路径。 |
| serializeSlotValue | 704-713 | 10 | UI slot effect 依赖序列化。 |
| getUiSlotValue | 715-721 | 7 | 从 window.__uiSlots 读取 slot 原始值。 |
| getEnabledPluginName | 723-728 | 6 | 从 plugin:options 中提取插件名。 |
| providerHasEnabledPlugin | 730-736 | 7 | 判断 provider 是否启用指定插件。 |
| getUiSlotScript | 738-748 | 11 | 根据 engine、slot、插件门控取脚本。 |
| hasUiSlot | 750-752 | 3 | 判断 slot 是否存在。 |
| clampRackPercent | 952-960 | 9 | 机房圆环百分比裁剪。 |
| mixRackRgb | 962-969 | 8 | RGB 线性混色。 |
| getRackUsageGradientColor | 971-979 | 9 | 机房普通 Key 圆环颜色。 |
| formatRackKeyLabel | 981-991 | 11 | 机房卡片 Key 文案。 |
| getRackBalanceTextClass | 993-1001 | 9 | 机房余额文字颜色。 |
| normalizeQuotaTone | 1106-1112 | 7 | 归一化 QuotaGauge tone。 |
| getQuotaGaugeStrokeColor | 1114-1122 | 9 | 额度圆环 stroke 色。 |
| getQuotaRingTextClass | 1124-1135 | 12 | 额度圆环文字色。 |
| getCurrencySymbol | 1137-1141 | 5 | 货币符号。 |
| formatQuotaAmount | 1143-1148 | 6 | 额度金额格式化。 |
| getQuotaRingText | 1150-1156 | 7 | 圆环中心文字。 |

### 1.5 React 函数组件

| 组件 | 起止行号 | 行数 | 说明 |
| --- | ---: | ---: | --- |
| DeferredInput | 43-48 | 6 | 延迟提交输入框。 |
| KeyLabelOverlay | 53-140 | 88 | Key 备注遮罩输入容器。 |
| QuotaBorderOverlay | 636-681 | 46 | Key 行双额度边框。 |
| QuotaArcs | 684-696 | 13 | 兼容用额度百分比标签组件。 |
| UiSlot | 754-840 | 87 | 渠道自定义 UI slot 挂载组件。 |
| CoolingKeyRow | 843-941 | 99 | 冷却 Key 完整行。 |
| RackGrid | 1003-1011 | 9 | 机房模式网格容器。 |
| RackRingCircle | 1013-1057 | 45 | SVG 圆环基础组件。 |
| RackSingleRing | 1059-1075 | 17 | 单额度圆环，当前主要是历史兼容。 |
| RackOAuthRings | 1077-1093 | 17 | OAuth 双环，当前主要是历史兼容。 |
| QuotaRings | 1158-1229 | 72 | 统一额度圆环组件。 |
| RackCoolingBorder | 1231-1282 | 52 | 机房卡片冷却边框。 |
| RackCard | 1284-1432 | 149 | 机房模式 Key 卡片。 |
| Channels | 1435-6698 | 5264 | 页面主组件。 |
| ProviderCard | 3839-3945 | 107 | Channels 内部移动端渠道卡片组件。 |

### 1.6 Channels 主组件内部主要函数

| 函数 | 起止行号 | 行数 | 功能分类 |
| --- | ---: | ---: | --- |
| restoreChannelModalScrollLock | 1558-1572 | 15 | 编辑抽屉滚动恢复。 |
| applyChannelModalScrollLock | 1579-1592 | 14 | 编辑抽屉滚动锁定。 |
| applyApiConfigData | 1601-1623 | 23 | api_config 数据写入 state。 |
| refreshProviders | 1625-1636 | 12 | 全量刷新 provider。 |
| refreshSingleProvider | 1638-1664 | 27 | 单 provider 刷新。 |
| fetchInitialData | 1666-1720 | 55 | 页面初始化加载。 |
| refreshKeyStatus | 1728-1746 | 19 | Key 运行时状态刷新。 |
| refreshOAuthAccounts | 1791-1814 | 24 | OAuth 账号状态刷新。 |
| openModal | 1923-2118 | 196 | 打开新增、编辑、复制、子渠道编辑表单。 |
| updateFormData | 2120-2122 | 3 | 表单字段更新。 |
| updatePreference | 2124-2126 | 3 | preferences 字段更新。 |
| updateModelPrefix | 2128-2137 | 10 | 模型前缀更新并联动 pool_sharing。 |
| queryAllBalances | 2140-2221 | 82 | 批量余额查询。 |
| addEmptyKey | 2223-2237 | 15 | 添加空 Key 并滚动聚焦。 |
| updateKey | 2239-2244 | 6 | 更新单个 Key。 |
| handleOAuthKeyFocus | 2246-2252 | 7 | OAuth Key 聚焦快照。 |
| handleOAuthKeyBlur | 2254-2290 | 37 | OAuth 账号重命名。 |
| openImportModal | 2292-2298 | 7 | 打开 OAuth token 导入弹窗。 |
| doImport | 2300-2333 | 34 | 提交 OAuth token 导入。 |
| startOAuthLogin | 2335-2397 | 63 | 发起 OAuth 浏览器登录。 |
| doManualExchange | 2399-2443 | 45 | 手动 OAuth 回调 URL 交换。 |
| toggleKeyDisabled | 2445-2450 | 6 | 切换 Key 禁用。 |
| deleteKey | 2452-2489 | 38 | 删除普通 Key 或 OAuth 账号。 |
| handleKeyPaste | 2491-2505 | 15 | 多行粘贴 Key。 |
| copyAllKeys | 2507-2513 | 7 | 复制有效 Key。 |
| exportOAuthCredentials | 2515-2548 | 34 | 导出 OAuth 凭证。 |
| clearAllKeys | 2550-2555 | 6 | 清空 Key。 |
| handleGroupInputKeyDown | 2557-2565 | 9 | 分组输入。 |
| removeGroup | 2567-2571 | 5 | 删除分组。 |
| handleModelInputKeyDown | 2573-2582 | 10 | 模型输入。 |
| openFetchModelsDialog | 2584-2641 | 58 | 拉取上游模型并打开选择弹窗。 |
| toggleModelSelect | 2643-2648 | 6 | 模型选择切换。 |
| selectAllVisible | 2657-2659 | 3 | 选择可见模型。 |
| deselectAllVisible | 2661-2666 | 6 | 取消选择可见模型。 |
| confirmFetchModels | 2668-2671 | 4 | 确认导入模型。 |
| copyAllModels | 2673-2678 | 6 | 复制模型列表。 |
| getAliasMap | 2680-2686 | 7 | 当前表单模型别名 map。 |
| getModelDisplayName | 2688-2691 | 4 | 模型显示名。 |
| formatJsonOnBlur | 2693-2702 | 10 | JSON 输入失焦格式化。 |
| handleMappingChange | 2704-2710 | 7 | 模型映射更新。 |
| handlePluginSheetUpdate | 2712-2725 | 14 | 插件 Sheet 回写 preferences。 |
| handleDeleteProvider | 2727-2755 | 29 | 删除主渠道。 |
| handleToggleProvider | 2757-2785 | 29 | 启用或禁用主渠道。 |
| handleCopyProvider | 2787-2797 | 11 | 复制渠道。 |
| handleToggleSubChannel | 2800-2822 | 23 | 启用或禁用子渠道。 |
| handleDeleteSubChannel | 2824-2848 | 25 | 删除子渠道。 |
| openSubChannelEdit | 2850-2906 | 57 | 打开子渠道完整编辑。 |
| buildSubChannelProvider | 2909-2925 | 17 | 构造子渠道测试 provider。 |
| handleUpdateWeight | 2932-2962 | 31 | 更新渠道权重。 |
| getVirtualProviderWeight | 2964-2969 | 6 | 虚拟面板渠道权重读取。 |
| getProviderModelOptions | 2971-3006 | 36 | 提取 provider 模型候选。 |
| findProviderModelOption | 3008-3022 | 15 | 查找模型匹配项。 |
| getProviderByName | 3024-3029 | 6 | 从虚拟路由 provider 列表查找 provider。 |
| getMatchingProviderCount | 3031-3036 | 6 | 统计模型可匹配渠道数。 |
| formatProviderModelOption | 3038-3043 | 6 | 格式化渠道模型候选。 |
| describeVirtualChannelNode | 3045-3055 | 11 | 虚拟渠道节点说明。 |
| updateVirtualModelsDraft | 3057-3063 | 7 | 虚拟模型草稿更新。 |
| serializeVirtualModels | 3065-3088 | 24 | 虚拟模型保存前清理。 |
| saveVirtualModels | 3090-3105 | 16 | 保存虚拟模型配置。 |
| handleSaveVirtualModelsDraft | 3107-3118 | 12 | 保存旧画布草稿入口。 |
| handleAddVirtualModel | 3120-3137 | 18 | 新建虚拟模型草稿。 |
| updateVirtualModelConfig | 3139-3147 | 9 | 更新虚拟模型配置。 |
| updateVirtualNode | 3149-3162 | 14 | 更新虚拟链条节点。 |
| moveVirtualNode | 3164-3176 | 13 | 移动虚拟链条节点。 |
| insertVirtualNode | 3178-3189 | 12 | 插入虚拟链条节点。 |
| appendVirtualNodeByType | 3191-3197 | 7 | 按类型追加虚拟节点。 |
| toggleVirtualModelExpanded | 3199-3208 | 10 | 切换虚拟模型展开。 |
| toggleVirtualProviderExpanded | 3210-3219 | 10 | 切换虚拟面板渠道展开。 |
| getPreferredVirtualTarget | 3221-3227 | 7 | 快速添加目标虚拟模型。 |
| handlePanelModelQuickAdd | 3229-3239 | 11 | 左栏模型快速添加。 |
| handlePanelChannelQuickAdd | 3241-3251 | 11 | 左栏渠道快速添加。 |
| handleDeleteVirtualModel | 3253-3273 | 21 | 删除虚拟模型并保存。 |
| setVirtualDragPayload | 3275-3283 | 9 | 写入拖拽 payload。 |
| readVirtualDragPayload | 3285-3296 | 12 | 读取拖拽 payload。 |
| handlePanelModelDragStart | 3298-3304 | 7 | 模型拖拽开始。 |
| handlePanelChannelDragStart | 3306-3311 | 6 | 渠道拖拽开始。 |
| handleChainNodeDragStart | 3313-3318 | 6 | 链条节点拖拽开始。 |
| handleVirtualDrop | 3320-3337 | 18 | 旧虚拟画布 drop 处理。 |
| openVirtualModelModal | 3339-3354 | 16 | 打开虚拟模型抽屉。 |
| updateVirtualEditorChainDraft | 3356-3362 | 7 | 抽屉链条草稿更新。 |
| updateVirtualEditorNode | 3364-3374 | 11 | 抽屉节点更新。 |
| insertVirtualEditorNode | 3376-3386 | 11 | 抽屉节点插入。 |
| moveVirtualEditorNode | 3388-3400 | 13 | 抽屉节点拖拽移动。 |
| swapVirtualEditorNode | 3402-3413 | 12 | 抽屉节点上移或下移。 |
| appendVirtualEditorNodeByType | 3415-3422 | 8 | 抽屉按类型追加节点。 |
| handleVirtualEditorDrop | 3424-3440 | 17 | 抽屉 drop 处理。 |
| handleSaveVirtualEditor | 3442-3471 | 30 | 保存虚拟模型抽屉。 |
| handleToggleVirtualModelCard | 3473-3486 | 14 | 列表中切换虚拟模型启用。 |
| openTestDialog | 3488-3491 | 4 | 打开渠道测试弹窗。 |
| openKeyTestDialog | 3493-3497 | 5 | 打开多 Key 测试弹窗。 |
| buildProviderSnapshotForTest | 3499-3568 | 70 | 生成测试用 provider 快照。 |
| getProviderModelNameListForUi | 3570-3584 | 15 | 生成测试弹窗模型名。 |
| disableKeysInForm | 3586-3594 | 9 | 测试后禁用 Key。 |
| handleSave | 3596-3836 | 241 | 保存主渠道或子渠道。 |
| ProviderCard | 3839-3945 | 107 | 移动端渠道卡片组件。 |
| getProviderModelNames | 3948-3983 | 36 | 搜索用模型名提取。 |
| virtualProviderEntries | 3986-3991 | 6 | 虚拟模型列表 useMemo。 |
| virtualRoutingProviderItems | 3993-3998 | 6 | 虚拟路由 provider useMemo。 |
| virtualProviderPanelItems | 4000-4005 | 6 | 虚拟面板 provider useMemo。 |
| providerNames | 4007-4012 | 6 | 渠道节点下拉名称 useMemo。 |
| providerListItems | 4014-4019 | 6 | 真实渠道列表 useMemo。 |
| availableEngines | 4022-4030 | 9 | 筛选引擎 useMemo。 |
| availableGroups | 4032-4039 | 8 | 筛选分组 useMemo。 |
| getProviderAnalyticsName | 4042-4050 | 9 | 统计分析 provider 名拼接。 |
| filteredVirtualProviderEntries | 4052-4070 | 19 | 虚拟模型筛选 useMemo。 |
| filteredProviders | 4073-4100 | 28 | 真实渠道筛选 useMemo。 |
| getMatchedModels | 4103-4107 | 5 | 模型搜索命中项。 |
| isProviderInactive | 4118-4124 | 7 | 不活跃渠道判断。 |
| toggleInactiveGroup | 4128-4134 | 7 | 不活跃分组展开切换。 |
| renderVirtualProviderPanelCollapsedRail | 4161-4194 | 34 | 虚拟模型抽屉桌面折叠侧栏。 |
| renderVirtualProviderPanelList | 4196-4282 | 87 | 虚拟模型抽屉渠道列表。 |
| getFullVirtualChainSummary | 4284-4289 | 6 | 虚拟链条完整摘要。 |
| openVirtualRouteTestDialog | 4291-4301 | 11 | 打开虚拟路由测试。 |
| renderDesktopVirtualRoutesAccordionRows | 4303-4389 | 87 | 桌面虚拟路由手风琴行。 |
| renderMobileVirtualRoutesAccordion | 4391-4460 | 70 | 移动端虚拟路由手风琴。 |
| renderFullKeyRow | 4463-4640 | 178 | 完整 Key 行渲染。 |

### 1.7 Channels 主组件 state 分组

| 分组 | state |
| --- | --- |
| 渠道数据 | providers、providerActivity、channelTypes、allPlugins、loading |
| 编辑抽屉 | isModalOpen、originalIndex、formData、editingSubChannel、showPluginSheet |
| 表单输入 | groupInput、modelInput、headerEntries、overridesJson、statusCodeOverridesJson、modelDisplayKey |
| 测试和统计弹窗 | testDialogOpen、testingProvider、keyTestDialogOpen、keyTestInitialIndex、keyTestOverride、analyticsOpen、analyticsProvider |
| Key 和余额 | balanceResults、balanceLoading、focusedKeyIdx、forceListMode、runtimeKeyStatus、localCountdowns |
| OAuth | oauthAccounts、importModalIdx、importToken、importing、oauthManualState、manualUrl、exchanging、oauthKeyFocusSnapshotRef |
| 全局价格 | globalModelPrice |
| 虚拟模型 | virtualModels、virtualDraftName、virtualDraftEnabled、virtualModelsDirty、expandedVirtualModels、expandedVirtualProviders、virtualAddNodeTypes、isVirtualModalOpen、editingVirtualName、virtualEditorChain、isVirtualProviderPanelCollapsed、isVirtualMobileProviderPanelOpen、isVirtualRoutesAccordionOpen |
| 拉取模型弹窗 | isFetchModelsOpen、fetchedModels、selectedModels、modelSearchQuery |
| 列表筛选 | filterKeyword、filterEngine、filterGroup、filterStatus、expandedInactiveGroups |
| 滚动锁 | channelModalScrollYRef、channelModalBodyStyleRef |

## 2. 依赖关系

### 2.1 可直接抽出的组件

这些组件已经在 Channels 外部，或者只需要通过 props 接收数据和回调，适合先抽出：

| 组件 | 建议目标文件 | 依赖 |
| --- | --- | --- |
| DeferredInput | `components/common/DeferredInput.tsx` | React。 |
| KeyLabelOverlay | `components/key/KeyLabelOverlay.tsx` | React、useLayoutEffect、useCallback。 |
| QuotaBorderOverlay | `components/quota/QuotaBorderOverlay.tsx` | buildTopHalfPath、buildBottomHalfPath。 |
| UiSlot | `components/ui-slots/UiSlot.tsx` | ui slot helpers、uiSlotCache。 |
| CoolingKeyRow | `components/key/CoolingKeyRow.tsx` | ApiKeyObj、formatCountdown、buildRoundRectPath、图标。 |
| RackGrid | `components/key/RackGrid.tsx` | ReactNode。 |
| RackRingCircle | `components/quota/RackRingCircle.tsx` | RACK_* 常量。 |
| QuotaRings | `components/quota/QuotaRings.tsx` | QuotaGauge、圆环颜色与文字 helper。 |
| RackCoolingBorder | `components/key/RackCoolingBorder.tsx` | formatCountdown、buildRoundRectPath。 |
| RackCard | `components/key/RackCard.tsx` | RowQuota helpers、UiSlot、QuotaRings、RackCoolingBorder、formatRackKeyLabel、hasUiSlot。 |
| ProviderCard | `components/list/ProviderCard.tsx` | 需要把 openModal、openTestDialog、handleToggleProvider、handleDeleteProvider、handleUpdateWeight、sub channel handlers 等作为 props 传入。 |

说明：RackSingleRing、RackOAuthRings、QuotaArcs 目前更像兼容残留。可以先抽出到 quota 目录保持行为不变，不建议在拆分批次中顺手删除。

### 2.2 不宜第一批直接抽出的部分

| 部分 | 原因 |
| --- | --- |
| renderFullKeyRow | 依赖 formData、runtimeKeyStatus、localCountdowns、balanceResults、oauthAccounts、isOAuthEngine、focusedKeyIdx、多个 Key 操作函数与测试函数。建议等 Key hook 稳定后抽成 `KeyListSection`。 |
| 虚拟模型抽屉主体 | 依赖 virtualModels、providers、拖拽、编辑草稿、筛选、保存 API。建议与 useVirtualModels 一起抽。 |
| handleSave/openModal | 负责序列化、并发安全保存、主渠道和子渠道双路径、OAuth state copy。风险高，应在有测试覆盖后拆。 |
| OAuth 导入与手动回调 portal | 依赖 Radix Dialog 焦点策略、createPortal、表单 Key 行。需要单独验证。 |
| 主 return 中编辑抽屉各 section | JSX 过长且直接读写大量 state。应先把 state 与 handlers 打包后再拆。 |

### 2.3 被多处调用的工具函数

| 工具 | 主要调用点 | 拆分建议 |
| --- | --- | --- |
| buildProviderApiPath | 单 provider GET/PUT/DELETE、保存、子渠道操作、权重更新 | 放入 `utils/providerPaths.ts`，优先抽出。 |
| hasUiSlot / UiSlot | RackCard、完整 Key 行、Base URL/Token URL/Key hint/summary/override hint | 放入 `ui-slots` 模块，保持 window.__uiSlots 入口不变。 |
| getQuotaFromSource | OAuth 自动查询、手动余额、账号归一化、balance fallback | 放入 `utils/quota.ts`，并补新旧字段兼容测试。 |
| buildRowQuota / buildRowQuotaSlotData | RackCard、renderFullKeyRow | 放入 `utils/rowQuota.ts`，是 Key 行与卡片共享核心。 |
| getBalancePercent / getBalanceColor / getBalanceLabel | 行背景、余额标签、余额汇总、圆环文字 | 放入 `utils/balance.ts`。 |
| sortProvidersByWeight | 初始加载、单渠道刷新、局部别名 sortByWeight | 放入 `utils/providerSort.ts`。 |
| serializeChannelPreferences | 测试快照、保存、子渠道序列化 | 放入 `utils/preferences.ts`。 |
| formatCountdown / buildRoundRectPath | CoolingKeyRow、RackCoolingBorder | 放入 `utils/svgProgress.ts` 或 `utils/time.ts`。 |
| getProviderModelOptions / findProviderModelOption | 虚拟模型左栏、节点说明、匹配统计 | 放入 `utils/virtualProviderModels.ts` 或随 useVirtualModels 抽出。 |
| serializeVirtualModels | 多个虚拟模型保存入口 | 放入 `utils/virtualModelsSerialization.ts`。 |
| buildProviderSnapshotForTest | ApiKeyTestDialog | 放入 `utils/providerSnapshot.ts`，但应在 handleSave 序列化抽出后复用同一套逻辑。 |

### 2.4 跨组件共享 state

| state | 共享范围 | 拆分处理 |
| --- | --- | --- |
| formData | 编辑抽屉所有 section、Key 行、RackCard、OAuth 导入、测试快照、保存 | 用 `useChannelEditor` 持有，向 section 传入局部 slice 和 handlers。 |
| providers | 主列表、ProviderCard、子渠道操作、虚拟模型 provider 列表、保存和刷新 | 用 `useChannelsData` 管理，provider 操作放入 `useProviderActions`。 |
| channelTypes | engine 下拉、默认 base_url/token_url、OAuth 判断、import placeholder | 随 `useChannelsData` 输出。 |
| balanceResults / oauthAccounts | RackCard、完整 Key 行、余额按钮、OAuth 自动刷新、slot data | 用 `useKeyBalances` 和 `useOAuthAccounts` 分开管理，但通过 Key section 组合。 |
| runtimeKeyStatus / localCountdowns | 列表 Key 统计、CoolingKeyRow、RackCard、完整 Key 行 | 用 `useRuntimeKeyStatus` 管理，输出刷新函数和倒计时 map。 |
| focusedKeyIdx / forceListMode | RackGrid、RackCard、renderFullKeyRow、编辑抽屉点击收起 | 保留在 Key section hook 或 editor hook 中。 |
| headerEntries / overridesJson / statusCodeOverridesJson | openModal 初始化、保存、测试快照、高级设置 section | 与 `useChannelEditor` 放在一起。 |
| virtualModels 相关 state | 虚拟路由手风琴、虚拟模型抽屉、拖拽、测试、保存 | 用 `useVirtualModels` 持有。 |
| filterKeyword/filterEngine/filterGroup/filterStatus | FilterBar、真实列表、虚拟列表、统计 | 用 `useChannelFilters` 管理。 |
| testDialogOpen/testingProvider/keyTest* | 主列表、子渠道、Key section、虚拟路由测试 | 可保留在 Channels 外壳，或抽成 `useChannelDialogs`。 |
| isOAuthOverlayOpen 派生值 | Dialog modal、onFocusOutside、onInteractOutside | 与 OAuth portal state 保持在同一个 hook，避免焦点回归问题。 |

## 3. 拆分目录结构

建议在 `frontend/src/pages/channels/` 下建立页面专属目录，再让原 `frontend/src/pages/Channels.tsx` 只保留导出入口。

```text
frontend/src/pages/Channels.tsx                         # 5-20 行，re-export 页面外壳
frontend/src/pages/channels/ChannelsPage.tsx            # 250-350 行，组合 hooks、列表、抽屉、Dialog
frontend/src/pages/channels/types.ts                    # 120-150 行，页面类型
frontend/src/pages/channels/constants.ts                # 40-60 行，调度、颜色、圆环常量
frontend/src/pages/channels/utils/preferences.ts        # 40-60 行
frontend/src/pages/channels/utils/balance.ts            # 120-170 行
frontend/src/pages/channels/utils/quota.ts              # 120-180 行
frontend/src/pages/channels/utils/provider.ts           # 80-130 行，路径、排序、模型提取基础函数
frontend/src/pages/channels/utils/svgProgress.ts        # 60-90 行
frontend/src/pages/channels/utils/uiSlots.ts            # 80-120 行
frontend/src/pages/channels/utils/providerSnapshot.ts   # 180-260 行，测试快照与保存序列化复用
frontend/src/pages/channels/utils/virtualModels.ts      # 160-240 行，虚拟模型序列化、模型匹配说明
frontend/src/pages/channels/hooks/useChannelsData.ts    # 180-260 行，初始加载、provider 刷新
frontend/src/pages/channels/hooks/useRuntimeKeyStatus.ts# 100-150 行，运行时状态与倒计时
frontend/src/pages/channels/hooks/useChannelEditor.ts   # 450-700 行，openModal、formData、保存
frontend/src/pages/channels/hooks/useKeyManagement.ts   # 260-380 行，Key 增删改、粘贴、测试禁用、余额入口协调
frontend/src/pages/channels/hooks/useOAuthAccounts.ts   # 250-360 行，OAuth 账号、导入、登录、手动 exchange
frontend/src/pages/channels/hooks/useVirtualModels.ts   # 500-750 行，虚拟模型 CRUD、拖拽、抽屉草稿
frontend/src/pages/channels/hooks/useChannelFilters.ts  # 120-180 行，筛选、分段、不活跃分组
frontend/src/pages/channels/hooks/useChannelDialogs.ts  # 80-130 行，测试弹窗、分析弹窗状态
frontend/src/pages/channels/components/common/DeferredInput.tsx          # 20-35 行
frontend/src/pages/channels/components/key/KeyLabelOverlay.tsx           # 90-120 行
frontend/src/pages/channels/components/key/CoolingKeyRow.tsx             # 100-130 行
frontend/src/pages/channels/components/key/RackGrid.tsx                  # 15-25 行
frontend/src/pages/channels/components/key/RackCard.tsx                  # 160-220 行
frontend/src/pages/channels/components/key/KeyListSection.tsx            # 320-480 行
frontend/src/pages/channels/components/quota/QuotaBorderOverlay.tsx      # 50-70 行
frontend/src/pages/channels/components/quota/RackRingCircle.tsx          # 50-70 行
frontend/src/pages/channels/components/quota/QuotaRings.tsx              # 100-150 行
frontend/src/pages/channels/components/ui-slots/UiSlot.tsx               # 90-130 行
frontend/src/pages/channels/components/list/FilterBar.tsx                # 100-140 行
frontend/src/pages/channels/components/list/ProviderCard.tsx             # 120-160 行
frontend/src/pages/channels/components/list/MobileProviderList.tsx       # 120-180 行
frontend/src/pages/channels/components/list/DesktopProviderTable.tsx     # 260-420 行
frontend/src/pages/channels/components/virtual/VirtualRoutesAccordion.tsx# 180-260 行
frontend/src/pages/channels/components/virtual/VirtualProviderPanel.tsx  # 220-320 行
frontend/src/pages/channels/components/virtual/VirtualModelDialog.tsx    # 500-750 行
frontend/src/pages/channels/components/editor/ChannelEditorSheet.tsx     # 250-400 行，组合各 section
frontend/src/pages/channels/components/editor/BaseConfigSection.tsx      # 220-320 行
frontend/src/pages/channels/components/editor/KeySection.tsx             # 180-260 行，组合 KeyListSection
frontend/src/pages/channels/components/editor/ModelSection.tsx           # 130-180 行
frontend/src/pages/channels/components/editor/MappingSection.tsx         # 80-130 行
frontend/src/pages/channels/components/editor/SubChannelsSection.tsx     # 450-650 行
frontend/src/pages/channels/components/editor/RoutingLimitsSection.tsx   # 260-380 行
frontend/src/pages/channels/components/editor/AdvancedSettingsSection.tsx# 450-650 行
frontend/src/pages/channels/components/dialogs/FetchModelsDialog.tsx     # 100-150 行
frontend/src/pages/channels/components/dialogs/OAuthCredentialDialogs.tsx# 120-180 行
```

拆分后目标不是把每个文件都压到很短，而是让每个文件只有一个清晰职责。`ChannelEditorSheet` 下的 section 可以继续二次拆分，尤其是 `SubChannelsSection` 与 `AdvancedSettingsSection`。

## 4. 分批执行计划（按风险从低到高）

### 第一批：类型、常量、纯工具函数

风险最低。先补纯函数测试，再搬迁代码。

范围：

1. 抽 `types.ts`、`constants.ts`。
2. 抽 `utils/preferences.ts`、`utils/balance.ts`、`utils/quota.ts`、`utils/provider.ts`、`utils/svgProgress.ts`、`utils/uiSlots.ts`。
3. 暂不改 JSX 结构，只改 import。
4. 保留 `Channels.tsx` 的行为和函数名。

建议测试：

- `readBooleanPreference` 对字符串和布尔值的归一化。
- `serializeChannelPreferences` 对 key_rules retry/remap 的清理。
- `getQuotaFromSource` 对 quota_5h/quota_7d 与 quota_inner/quota_outer 的兼容。
- `buildRowQuota` 对 OAuth、普通 amount、percent、quota、gauges 的输出。
- `buildProviderApiPath` 对特殊 provider 名的 encode。
- `serializeVirtualModels` 对空节点和 channel.model 的清理。

验收：TypeScript 构建通过，页面能打开，渠道列表能加载。

### 第二批：独立展示组件

风险较低到中等。组件行为清楚，但有 CSS 和焦点交互。

范围：

1. 抽 `DeferredInput`、`KeyLabelOverlay`。
2. 抽 quota 组件：`QuotaBorderOverlay`、`RackRingCircle`、`QuotaRings`，同时保留 `QuotaArcs`、`RackSingleRing`、`RackOAuthRings` 兼容导出。
3. 抽 Key 展示组件：`CoolingKeyRow`、`RackGrid`、`RackCoolingBorder`、`RackCard`。
4. 抽 `UiSlot` 及其 helper，注意 `uiSlotCache` 仍为模块级单例。

验收：

- 普通 Key 完整行、冷却行、机房卡片显示一致。
- quota_display、key_background、key_border 插槽仍能加载。
- Key 备注遮罩聚焦和失焦行为不变。

### 第三批：业务 hook 与序列化逻辑

风险中等到偏高。主要风险来自闭包、effect 依赖和异步刷新顺序。

范围：

1. 抽 `useChannelsData`：providers、providerActivity、channelTypes、allPlugins、loading、refreshProviders、refreshSingleProvider、fetchInitialData。
2. 抽 `useRuntimeKeyStatus`：runtimeKeyStatus、localCountdowns、refreshKeyStatus、倒计时 interval、轮询 interval。
3. 抽 `useOAuthAccounts`：oauthAccounts、refreshOAuthAccounts、doImport、startOAuthLogin、doManualExchange、exportOAuthCredentials、rename/delete account 相关逻辑。
4. 抽 `useChannelEditor`：formData、openModal、updateFormData、updatePreference、handleSave、headerEntries、JSON 配置、scroll lock。
5. 抽 `useVirtualModels`：虚拟模型 CRUD、拖拽、抽屉草稿、保存。
6. 抽 `useChannelFilters`：availableEngines、availableGroups、filteredProviders、filteredVirtualProviderEntries、segments、expandedInactiveGroups。

验收：

- 新增、编辑、重命名、删除、复制渠道仍走单 provider API，不退回全量覆盖。
- 子渠道编辑保存只更新所属主渠道。
- OAuth 登录、导入、手动回调弹窗焦点不被底层 Dialog 抢回。
- 虚拟模型新增、编辑、删除、启用、拖拽保存仍正常。

### 第四批：主 JSX、编辑抽屉和列表拆分

风险最高。主要因为 JSX 大块拆分会引入 props 边界和事件传播变化。

范围：

1. 抽 `FilterBar`、`MobileProviderList`、`DesktopProviderTable`、`ProviderCard`。
2. 抽 `VirtualRoutesAccordion`、`VirtualModelDialog`、`VirtualProviderPanel`。
3. 抽 `ChannelEditorSheet`，再拆 `BaseConfigSection`、`KeySection`、`ModelSection`、`MappingSection`、`SubChannelsSection`、`RoutingLimitsSection`、`AdvancedSettingsSection`。
4. 抽 `FetchModelsDialog`、`OAuthCredentialDialogs`。
5. 让 `ChannelsPage.tsx` 只负责组合 hooks、传递 props、挂载全局弹窗。

验收：

- 桌面表格和移动卡片在筛选、折叠不活跃分组、虚拟路由手风琴下行为一致。
- 编辑抽屉关闭后滚动位置恢复。
- Key section 的点击空白收起、机房卡片展开完整行、输入框 blur 都不变。
- 所有 Dialog 的 z-index、modal、focusOutside 行为不变。

## 5. 风险评估

| 风险 | 等级 | 原因 | 缓解措施 |
| --- | --- | --- | --- |
| handleSave 拆分后保存语义变化 | 高 | 主渠道、子渠道、新增、重命名、OAuth copy-provider 共用一条长函数。 | 先抽序列化纯函数并加测试，最后再抽 hook；保留单 provider API 路径。 |
| OAuth portal 焦点与 Dialog modal 行为变化 | 高 | importModalIdx 和 oauthManualState 会影响 Radix Dialog 的 modal、onFocusOutside、onInteractOutside。 | OAuth 相关 state 与派生 isOAuthOverlayOpen 必须同处一个 hook，拆分后逐项手测。 |
| UI slot 动态 import 缓存失效 | 高 | uiSlotCache 是模块级缓存，slot 还受 enabled_plugins 门控。 | 抽为单模块，缓存 key 和 fallback 行为不变；测试 requires_plugin。 |
| 虚拟模型拖拽失效 | 中高 | 原生 DragEvent payload 依赖 application/json 与 text/plain 回退。 | read/write payload 保持在同一工具模块；桌面拖拽和移动端上下移都验证。 |
| Key 行 focus/blur 行为变化 | 中高 | 完整行、机房展开行、OAuth rename、点击空白收起都依赖焦点传播。 | 先抽 RackCard，再抽 KeyListSection；不要在同批次移动 OAuth rename。 |
| useEffect 依赖变化导致重复请求 | 中高 | 初始加载、余额自动查询、OAuth 自动 quota 查询、轮询倒计时都有副作用。 | hook 抽出时显式列出依赖，避免把对象引用直接放进 effect；保留现有 eslint-disable 的语义。 |
| 类型循环引用 | 中 | types、utils、components 相互引用多。 | types.ts 不 import 页面组件；utils 只依赖 types/constants；components 依赖 utils，不反向依赖 hooks。 |
| CSS 或响应式布局变化 | 中 | 当前 JSX 中 className 很长，移动端和桌面端差异多。 | 第一轮只移动代码，不重构样式；每次抽组件前后截图或人工核对。 |
| 行为测试不足 | 中 | 目前页面承担 API、表单、拖拽、Dialog 多种职责。 | 每批先加 characterization tests，至少覆盖纯函数和关键 hook；UI 部分用手工 smoke list。 |

## 6. 建议的最终职责边界

1. `ChannelsPage.tsx` 只组合数据、hooks 和组件，不直接写 provider 保存细节。
2. 保存与测试快照共用同一套 provider 序列化工具，避免测试 payload 和正式保存 payload 分叉。
3. Key 行和机房卡片只消费统一的 `RowQuota`、runtime status、OAuth account，不直接理解渠道私有字段。
4. UI slot 系统保持独立模块，所有渠道差异继续由 slot 脚本负责。
5. 虚拟模型相关状态和拖拽逻辑独立成 hook，列表和抽屉只负责渲染。
6. 编辑抽屉各 section 只接收局部 props，避免每个 section 都拿完整 Channels 上下文。

## 7. 推荐验证清单

每批完成后至少验证：

1. 渠道列表初始加载、筛选、清除筛选。
2. 新增渠道、编辑渠道、复制渠道、删除渠道、启用禁用渠道、修改权重。
3. 子渠道新增、完整编辑、启用禁用、删除、测试。
4. 普通 Key 添加、粘贴多行、禁用、删除、清空、复制全部、多 Key 测试后禁用。
5. OAuth Key 导入、浏览器登录、手动回调、账号重命名、账号删除、导出凭证。
6. 余额查询、普通余额标签、OAuth 双额度、quota_display/key_background/key_border 插槽。
7. 机房模式自动切换、手动切换完整行模式、卡片展开完整行、冷却倒计时。
8. 虚拟模型新增、编辑、删除、启用禁用、拖拽排序、移动端上下移、虚拟路由测试。
9. 编辑抽屉打开和关闭后的滚动位置恢复。
10. 移动端卡片列表和桌面表格都能正常操作。
