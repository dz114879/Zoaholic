import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 修改原因：OAuth 类型引擎的 Key 不再是普通 API Key，而是本地账号标识符。
// 修改方式：通过源码回归测试锁定 OAuth 引擎识别、账号拉取、导入弹窗、浏览器登录入口和专属 Key 行渲染。
// 目的：避免后续维护时把 OAuth 账号管理退回为普通余额条和 sk-* 输入体验。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const channelsSource = readFileSync(path.resolve(__dirname, '../src/pages/Channels.tsx'), 'utf8');

function sliceBetween(startMarker, endMarker, fromIndex = 0) {
  const start = channelsSource.indexOf(startMarker, fromIndex);
  assert.notEqual(start, -1, `找不到起始片段：${startMarker}`);
  const end = channelsSource.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1, `找不到结束片段：${endMarker}`);
  return channelsSource.slice(start, end);
}

assert.match(channelsSource, /ClipboardPaste, LogIn/, 'Channels.tsx 应该导入 OAuth 导入和登录按钮图标');
assert.match(channelsSource, /const OAUTH_ENGINES = new Set\(\['codex', 'claude-code', 'antigravity'\]\);/, '应该集中声明 OAuth 类型引擎集合');
assert.match(channelsSource, /const isOAuthEngine = OAUTH_ENGINES\.has\(formData\?\.engine \|\| ''\);/, '编辑面板应该从当前 engine 派生 isOAuthEngine');
assert.match(channelsSource, /const \[oauthAccounts, setOauthAccounts\] = useState<Record<string, any>>\(\{\}\);/, '应该保存 OAuth 账号列表');
assert.match(channelsSource, /const \[importModalIdx, setImportModalIdx\] = useState<number \| null>\(null\);/, '应该保存导入弹窗目标 Key 下标');
assert.match(channelsSource, /const \[importToken, setImportToken\] = useState\(''\);/, '应该保存待导入 refresh_token');
assert.match(channelsSource, /const \[importing, setImporting\] = useState\(false\);/, '应该保存导入请求进行状态');

const oauthAccountsEffect = sliceBetween('// ── 打开 OAuth 编辑面板时同步账号状态 ──', 'const openModal');
assert.match(channelsSource, /const refreshOAuthAccounts = useCallback\(async \(\) => \{/, '应该把 OAuth 账号拉取封装为可复用函数');
assert.match(channelsSource, /apiFetch\('\/v1\/oauth\/accounts', \{ headers: \{ Authorization: `Bearer \$\{token\}` \} \}\)/, '账号列表请求应该携带管理员 token');
assert.match(channelsSource, /setOauthAccounts\(data \|\| \{\}\)/, '账号列表响应应该落入 oauthAccounts');
assert.match(oauthAccountsEffect, /if \(isModalOpen && isOAuthEngine\)/, '只应在 OAuth 编辑面板打开时拉取账号列表');
assert.match(oauthAccountsEffect, /refreshOAuthAccounts\(\);/, '打开 OAuth 编辑面板时应该复用账号刷新函数');

const importBlock = sliceBetween('const openImportModal', 'const startOAuthLogin');
assert.match(importBlock, /setImportModalIdx\(idx\);\s*setImportToken\(''\);/s, '打开导入弹窗时应该清空旧 token');
assert.match(importBlock, /apiFetch\('\/v1\/oauth\/import'/, '导入应该调用 OAuth import 端点');
assert.match(importBlock, /const keyId = `account_\$\{Date\.now\(\)\}`;/, '导入前应该生成临时账号 ID');
assert.match(importBlock, /type: formData\.engine/, '导入请求应该携带当前 OAuth engine');
assert.match(importBlock, /refresh_token: importToken\.trim\(\)/, '导入请求应该提交修剪后的 refresh_token');
assert.match(importBlock, /updateKey\(importModalIdx, data\.key_id \|\| keyId\);/, '导入成功后应该用后端返回的 key_id 更新 Key 列表');
assert.match(importBlock, /alert\(`导入失败: \$\{err\.detail \|\| err\.message \|\| res\.statusText\}`\);/, '导入失败应该展示后端错误信息');

const loginBlock = sliceBetween('const startOAuthLogin', 'const handleKeyPaste');
// 修改原因：OAuth 登录流程已分为 manual 粘贴回调 URL 和 auto 成功页 postMessage 两种模式。
// 修改方式：把旧的弹窗地址轮询断言改为锁定 mode 分支、manual 状态保存和 auto 消息校验。
// 目的：保证 Codex 固定 localhost 回调和可自定义回调 provider 都能沿当前流程完成登录。
assert.match(loginBlock, /apiFetch\(`\/v1\/oauth\/authorize\?type=\$\{encodeURIComponent\(formData\.engine\)\}`/, '登录应该请求 authorize 端点获取授权 URL');
assert.match(loginBlock, /Authorization: `Bearer \$\{token\}`/, 'authorize 请求应该携带管理员 token');
assert.match(loginBlock, /const \{ auth_url, state, mode \} = await res\.json\(\);/, '登录应该读取 auth_url、state 和登录模式');
assert.match(loginBlock, /window\.open\(auth_url, '_blank', 'width=600,height=700'\);/, '登录应该打开授权窗口');
assert.match(loginBlock, /if \(mode === 'manual'\) \{[\s\S]*setOauthManualState\(\{ idx, state \}\);[\s\S]*setManualUrl\(''\);[\s\S]*return;/, 'manual 模式应该打开手动粘贴弹窗并保存本次 state');
assert.match(loginBlock, /const handler = \(event: MessageEvent\) => \{[\s\S]*event\.data\?\.type !== 'oauth_callback_success'/, 'auto 模式应该监听 callback 成功页消息');
assert.match(loginBlock, /event\.data\?\.state && event\.data\.state !== state/, 'auto 模式应该校验 postMessage 中的 state');
assert.match(loginBlock, /window\.removeEventListener\('message', handler\);[\s\S]*const keyId = event\.data\.key_id;[\s\S]*updateKey\(idx, keyId\);/, 'auto 模式收到 key_id 后应该更新当前 Key 行');
assert.match(loginBlock, /refreshOAuthAccounts\(\);[\s\S]*authWindow\.close\(\);/, 'auto 模式成功后应该刷新账号列表并关闭授权窗口');
assert.match(loginBlock, /window\.addEventListener\('message', handler\);/, 'auto 模式应该注册 postMessage 监听器');
assert.match(loginBlock, /window\.setTimeout\(\(\) => \{[\s\S]*window\.removeEventListener\('message', handler\);[\s\S]*\}, 300000\);/, 'auto 模式应该在后端授权状态过期时移除监听器');
assert.doesNotMatch(loginBlock, /const poll = window\.setInterval/, '登录不应该继续轮询弹窗 location');
assert.doesNotMatch(loginBlock, /prompt\(/, '登录不应该继续使用 prompt 作为手动粘贴入口');
assert.doesNotMatch(loginBlock, /openImportModal\(idx\);/, '登录按钮不应该再回退到导入弹窗');
assert.doesNotMatch(loginBlock, /浏览器登录功能开发中，请先使用导入方式/, '登录按钮不应该再显示占位提示');

const manualExchangeBlock = sliceBetween('const doManualExchange', 'const toggleKeyDisabled');
assert.match(manualExchangeBlock, /const url = new URL\(manualUrl\.trim\(\)\);[\s\S]*url\.searchParams\.get\('code'\)[\s\S]*url\.searchParams\.get\('state'\)/, 'manual 交换应该解析用户粘贴 URL 中的 code 和 state');
assert.match(manualExchangeBlock, /callbackState && callbackState !== oauthManualState\.state[\s\S]*alert\('state 不匹配，可能不是本次登录的回调'\);/, 'manual 交换应该校验回调 URL 中的 state');
assert.match(manualExchangeBlock, /apiFetch\('\/v1\/oauth\/exchange', \{[\s\S]*method: 'POST'[\s\S]*JSON\.stringify\(\{ code, state: oauthManualState\.state \}\)/, 'manual 交换应该调用 exchange 端点提交 code 和保存的 state');
assert.match(manualExchangeBlock, /updateKey\(oauthManualState\.idx, data\.key_id \|\| ''\);/, 'manual 交换成功后应该自动填入 key_id');
assert.match(manualExchangeBlock, /await refreshOAuthAccounts\(\);[\s\S]*setOauthManualState\(null\);[\s\S]*setManualUrl\(''\);/, 'manual 交换成功后应该刷新账号列表并关闭粘贴弹窗');

assert.match(channelsSource, /const QuotaArcs = \(\{ quota5h, quota7d \}: \{ quota5h\?: number; quota7d\?: number \}\) => \{/, '应该提供双弧配额 SVG 组件');
assert.match(channelsSource, /quota5h == null && quota7d == null/, '双弧组件没有配额时应该不渲染');
assert.match(channelsSource, /5h: \$\{quota5h \?\? '\?'\}% · 7d: \$\{quota7d \?\? '\?'\}%/, '双弧组件 title 应该同时展示 5h 和 7d');

const keyRows = sliceBetween('{formData.api_keys.map((keyObj, idx) => {', '{formData.api_keys.length === 0');
assert.match(keyRows, /const oauthAccount = oauthAccounts\[keyObj\.key\];/, 'Key 行应该按 key_id 查找 OAuth 账号');
assert.match(keyRows, /const oauthQuota = getOAuthQuota\(oauthAccount\);/, 'Key 行应该归一化 OAuth 配额字段');
assert.match(keyRows, /!isOAuthEngine && !isFocused && balColor && balPct != null/, '普通余额进度条不应该覆盖 OAuth 专属行');
assert.match(keyRows, /placeholder=\{isOAuthEngine \? "邮箱或标识符" : "sk-\.\.\."\}/, 'OAuth Key 输入框 placeholder 应该改为邮箱或标识符');
assert.match(keyRows, /isOAuthEngine && !keyObj\.key[\s\S]*openImportModal\(idx\)[\s\S]*<ClipboardPaste className="w-3 h-3" \/> 导入/, 'OAuth 空条目应该显示导入按钮');
assert.match(keyRows, /isOAuthEngine && !keyObj\.key[\s\S]*startOAuthLogin\(idx\)[\s\S]*<LogIn className="w-3 h-3" \/> 登录/, 'OAuth 空条目应该显示登录按钮');
assert.match(keyRows, /isOAuthEngine && !isFocused && oauthQuota[\s\S]*<QuotaArcs quota5h=\{oauthQuota\.quota_5h\} quota7d=\{oauthQuota\.quota_7d\} \/>/, 'OAuth 已有账号应该显示双弧配额');
assert.match(keyRows, /isOAuthEngine && !isFocused && oauthAccount && !oauthQuota[\s\S]*已连接[\s\S]*刷新失败[\s\S]*冷却中/, 'OAuth 无配额账号应该显示连接状态标签');
assert.match(keyRows, /!isOAuthEngine && !isFocused && balLabel && balColor/, '普通余额标签不应该显示在 OAuth 行上');

// 修改原因：OAuth 弹窗已经迁移到 document.body portal，旧的编辑抽屉前置位置断言会误判。
// 修改方式：分别截取导入弹窗和手动粘贴弹窗的 createPortal 代码段做断言。
// 目的：继续检查 OAuth 表单内容，同时允许 portal 层级修复 Radix 焦点问题。
const importModalSource = sliceBetween('{importModalIdx !== null && createPortal(', 'document.body');
const manualModalSource = sliceBetween('{oauthManualState !== null && createPortal(', 'document.body', channelsSource.indexOf('{oauthManualState !== null && createPortal('));
assert.match(importModalSource, /tabIndex=\{-1\}/, '导入弹窗的 portal 遮罩应该允许焦点回退');
assert.match(importModalSource, /导入 Refresh Token/, '页面应该渲染导入 Refresh Token 弹窗');
assert.match(importModalSource, /从 CLIProxyAPI 配置或本地 OAuth 文件中复制 refresh_token 粘贴到下方/, '导入弹窗应该说明 token 来源');
assert.match(importModalSource, /placeholder="rt_xxxxxxxx\.\.\."/, '导入弹窗应该提供 refresh_token 示例 placeholder');
assert.match(importModalSource, /disabled=\{!importToken\.trim\(\) \|\| importing\}/, '导入按钮应该在空 token 或请求中禁用');
assert.match(manualModalSource, /tabIndex=\{-1\}/, '手动粘贴弹窗的 portal 遮罩应该允许焦点回退');
assert.match(manualModalSource, /完成 OAuth 登录/, '页面应该渲染手动完成 OAuth 登录弹窗');
assert.match(manualModalSource, /placeholder="http:\/\/localhost:1455\/auth\/callback\?code=\.\.\."/, '手动粘贴弹窗应该提示完整 localhost 回调 URL');
assert.match(manualModalSource, /disabled=\{!manualUrl\.trim\(\) \|\| exchanging\}/, '手动完成按钮应该在空 URL 或请求中禁用');

console.log('oauth key management regression passed');
// 修改原因：当前部署环境的 Node 18 在部分 ESM 脚本自然结束后会触发 Aborted。
// 修改方式：断言全部通过后显式以 0 退出，断言失败时仍会在这里之前抛出错误。
// 目的：让测试退出码只反映本文件断言是否通过。
process.exit(0);
