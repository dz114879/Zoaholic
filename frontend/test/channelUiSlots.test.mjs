import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 修改原因：Channels.tsx 要从单一 quota_display 改为通用多插槽，不能再保留 extra_usage 渲染硬编码。
// 修改方式：用源码静态断言检查通用 UiSlot、四个插槽挂载点，以及 extra_usage 只保留在数据透传路径中。
// 目的：防止后续维护时把渠道专属余额条、标签或汇总逻辑重新写回通用前端。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '..');
const channelsSource = readFileSync(path.resolve(frontendRoot, 'src/pages/Channels.tsx'), 'utf8');

function sliceBetween(source, startMarker, endMarker, fromIndex = 0) {
  const start = source.indexOf(startMarker, fromIndex);
  assert.notEqual(start, -1, `找不到起始片段：${startMarker}`);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1, `找不到结束片段：${endMarker}`);
  return source.slice(start, end);
}

const slotComponent = sliceBetween(channelsSource, 'const uiSlotCache', '// ── 冷却中 Key 行组件');
assert.match(slotComponent, /const UiSlot = \(\{ engine, slot, data, context, className, element = 'span', fallbackText \}/, '前端应提供通用 UiSlot 组件，而不是只提供 QuotaUiSlot');
assert.match(slotComponent, /const cacheKey = `\$\{engine\}:\$\{slot\}`;/, 'UiSlot 缓存 key 应包含 engine 和 slot');
assert.match(slotComponent, /__uiSlots\?\.\[engine\]\?\.\[slot\]/, 'UiSlot 应按 engine 和 slot 从 window.__uiSlots 读取脚本');
assert.doesNotMatch(slotComponent, /quota_display;/, 'UiSlot 内部不能固定读取 quota_display');
assert.match(slotComponent, /fn\(\{ el, data: dataRef\.current, \.\.\.\(contextRef\.current \?\? \{\}\) \}\)/, 'UiSlot 应把 data 和额外 context 一起传给渠道脚本');

const balanceButton = sliceBetween(channelsSource, '<Wallet className={`w-3 h-3 ${balanceLoading ? \'animate-pulse\' : \'\'}`} />', '</button>', channelsSource.indexOf('onClick={() => queryAllBalances()}'));
assert.match(balanceButton, /slot="balance_summary"/, 'OAuth 余额按钮应使用 balance_summary 插槽');
assert.match(balanceButton, /context=\{\{ accounts: oauthAccounts \}\}/, 'balance_summary 插槽应收到所有 OAuth 账号');
assert.match(balanceButton, /fallbackText="余额"/, 'balance_summary 插槽应保留余额默认文本');
assert.doesNotMatch(balanceButton, /extra_usage_enabled|extra_usage_limit|extra_usage_used/, '余额按钮不能再包含 extra_usage 汇总硬编码');

// 修改原因：hint 插槽只负责渠道提示文本，通用前端不能硬编码 Antigravity 覆写格式或 Claude Code 充值链接。
// 修改方式：用源码静态断言检查 base_url_hint、key_hint、override_hint 三个挂载点都按 hasUiSlot 条件渲染。
// 目的：保证未注册 hint 的渠道不显示、不占空间，注册渠道能通过 UiSlot 自行写入提示内容。
const baseUrlBlock = sliceBetween(channelsSource, 'API 地址 (Base URL)', '修改原因：OAuth 引擎');
assert.match(baseUrlBlock, /hasUiSlot\(formData\.engine, 'base_url_hint'\)/, 'Base URL 区域应检测 base_url_hint 插槽');
assert.match(baseUrlBlock, /slot="base_url_hint"[\s\S]*data=\{null\}[\s\S]*element="div"[\s\S]*className="text-xs text-muted-foreground mt-1"/, 'base_url_hint 应挂载为 muted 小字 div');

const keyHintBlock = sliceBetween(channelsSource, '{/* 2. API Keys', '<div className="space-y-2 max-h-64');
assert.match(keyHintBlock, /hasUiSlot\(formData\.engine, 'key_hint'\)/, 'Key 列表标题附近应检测 key_hint 插槽');
assert.match(keyHintBlock, /slot="key_hint"[\s\S]*data=\{null\}[\s\S]*element="div"[\s\S]*className="text-xs text-muted-foreground"/, 'key_hint 应挂载为 muted 小字 div');

const overrideHintBlock = sliceBetween(channelsSource, '请求体覆写 (JSON)', '<div className="flex items-center justify-between p-3 bg-muted/50');
assert.match(overrideHintBlock, /hasUiSlot\(formData\.engine, 'override_hint'\)/, '请求体覆写区域应检测 override_hint 插槽');
assert.match(overrideHintBlock, /slot="override_hint"[\s\S]*data=\{null\}[\s\S]*element="div"[\s\S]*className="text-xs text-amber-600 dark:text-amber-400 mt-1"/, 'override_hint 应挂载为 amber 警告小字 div');

const keyRows = sliceBetween(channelsSource, '{formData.api_keys.map((keyObj, idx) => {', '{formData.api_keys.length === 0');
assert.match(keyRows, /const hasKeyBorderSlot = hasUiSlot\(formData\.engine, 'key_border'\);/, 'Key 行应检测 key_border 插槽');
assert.match(keyRows, /const hasKeyBackgroundSlot = hasUiSlot\(formData\.engine, 'key_background'\);/, 'Key 行应检测 key_background 插槽');
assert.match(keyRows, /const hasQuotaLabelSlot = hasUiSlot\(formData\.engine, 'quota_label'\);/, 'Key 行应检测 quota_label 插槽');
assert.match(keyRows, /slot="key_border"[\s\S]*element="div"[\s\S]*className="absolute inset-0 pointer-events-none z-\[1\]"[\s\S]*<QuotaBorderOverlay quota5h=\{oauthQuota\.quota_5h\} quota7d=\{oauthQuota\.quota_7d\} \/>/, 'key_border 插槽存在时应替代默认双弧边框，否则保留默认边框');
assert.match(keyRows, /slot="key_background"[\s\S]*element="div"[\s\S]*className="absolute inset-0 pointer-events-none rounded-\[7px\] z-0 transition-all duration-500"/, 'key_background 插槽应挂载为覆盖整行的 absolute div');
assert.match(keyRows, /slot="quota_label"[\s\S]*context=\{\{ account: oauthAccount \}\}/, 'quota_label 插槽应收到当前账号');
assert.match(keyRows, /slot="quota_display"/, 'quota_display 应继续作为通用 UiSlot 的一个插槽');
assert.match(keyRows, /slot="quota_display"[\s\S]*data=\{oauthQuota\}[\s\S]*context=\{\{ account: oauthAccount \}\}/, 'quota_display 插槽应收到当前账号，供 Claude Code tier 标签读取 subscription_type');
assert.doesNotMatch(keyRows, /extra_usage_enabled|extra_usage_limit|extra_usage_used/, 'Key 行渲染逻辑不能再读取 extra_usage 字段');
assert.doesNotMatch(keyRows, /!oauthAccount\.extra_usage_enabled/, 'OAuth 已连接状态不能再被 extra_usage_enabled 条件压制');

const dataFlow = sliceBetween(channelsSource, 'const perAccount = data?.results || {};', 'const openModal = async');
assert.match(dataFlow, /extra_usage_enabled[\s\S]*extra_usage_limit[\s\S]*extra_usage_used/, 'extra_usage 字段仍应在余额回调中写入账号状态，供渠道插槽使用');

console.log('channel UI slots regression passed');
// 修改原因：当前部署环境的 Node 18 在部分 ESM 脚本自然结束后会触发 Aborted。
// 修改方式：断言全部通过后显式以 0 退出，断言失败时仍会在这里之前抛出错误。
// 目的：让测试退出码只反映本文件断言是否通过。
process.exit(0);
