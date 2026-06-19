export type EnabledPluginValue =
  | string
  | {
      name?: string;
      plugin?: string;
      plugin_name?: string;
      options?: string;
      params?: Record<string, unknown>;
    }
  | Record<string, unknown>;

export interface ParsedEnabledPlugin {
  name: string;
  opts?: string;
  hasOpts: boolean;
}

function stringifyParamValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return value.map(item => String(item)).join('\n');
  return String(value);
}

function singleKeyObject(value: Record<string, unknown>): { name: string; params: unknown } | null {
  const keys = Object.keys(value);
  if (keys.length !== 1) return null;
  const name = keys[0];
  if (!name || ['name', 'plugin', 'plugin_name', 'options', 'params'].includes(name)) return null;
  return { name, params: value[name] };
}

export function paramsObjectToOptions(pluginName: string, params: unknown): string {
  if (!params || typeof params !== 'object') return stringifyParamValue(params);
  const obj = params as Record<string, unknown>;

  if (pluginName === 'key_guard') {
    const parts: string[] = [];
    const allowedUa = obj.allowed_ua ?? obj.ua;
    if (allowedUa !== undefined && allowedUa !== null) {
      parts.push(`allowed_ua=${stringifyParamValue(allowedUa)}`);
    }
    const stripTools = obj.strip_tools ?? obj.tools;
    if (stripTools !== undefined && stripTools !== null) {
      parts.push(`strip_tools=${stringifyParamValue(stripTools)}`);
    }
    return parts.join(',');
  }

  return Object.entries(obj)
    .map(([key, value]) => {
      const text = stringifyParamValue(value);
      return text ? `${key}=${text}` : '';
    })
    .filter(Boolean)
    .join(',');
}

export function parseEnabledPluginValue(value: EnabledPluginValue): ParsedEnabledPlugin {
  if (typeof value === 'string') {
    const colonIndex = value.indexOf(':');
    if (colonIndex < 0) return { name: value, opts: undefined, hasOpts: false };
    const opts = value.slice(colonIndex + 1);
    return { name: value.slice(0, colonIndex), opts, hasOpts: true };
  }

  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    const directName = obj.name ?? obj.plugin ?? obj.plugin_name;
    if (typeof directName === 'string' && directName.trim()) {
      const name = directName.trim();
      if (typeof obj.options === 'string') {
        return { name, opts: obj.options, hasOpts: Boolean(obj.options) };
      }
      if ('params' in obj) {
        const opts = paramsObjectToOptions(name, obj.params);
        return { name, opts: opts || undefined, hasOpts: Boolean(opts) };
      }
      return { name, opts: undefined, hasOpts: false };
    }

    const single = singleKeyObject(obj);
    if (single) {
      const opts = paramsObjectToOptions(single.name, single.params);
      return { name: single.name, opts: opts || undefined, hasOpts: Boolean(opts) };
    }
  }

  return { name: '', opts: undefined, hasOpts: false };
}

function parseKeyValueOptions(options: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const rawPart of options.split(',')) {
    const part = rawPart.trim();
    if (!part) continue;
    const idx = part.indexOf('=');
    if (idx <= 0) continue;
    const key = part.slice(0, idx).trim();
    const value = part.slice(idx + 1);
    if (key) result[key] = value;
  }
  return result;
}

function parseKeyGuardOptions(options: string): Record<string, string> {
  // 修改原因：key_guard 的 allowed_ua 来自 textarea，值里理论上可以出现逗号，不能用通用逗号切分。
  // 修改方式：只识别固定字段边界 allowed_ua=、ua=、strip_tools=、tools=，避免把 allowed_ua 内容按逗号拆碎。
  // 目的：前端内部转换也尽量不依赖用户内容不会出现逗号。
  const result: Record<string, string> = {};
  const readTextField = (key: string, aliases: string[]) => {
    for (const alias of aliases) {
      const prefix = `${alias}=`;
      const start = options.indexOf(prefix);
      if (start < 0) continue;
      const valueStart = start + prefix.length;
      const boundaryCandidates = ['allowed_ua=', 'ua=', 'strip_tools=', 'tools=']
        .map(candidate => options.indexOf(`,${candidate}`, valueStart))
        .filter(index => index >= 0);
      const end = boundaryCandidates.length > 0 ? Math.min(...boundaryCandidates) : options.length;
      result[key] = options.slice(valueStart, end);
      return;
    }
  };
  readTextField('allowed_ua', ['allowed_ua', 'ua']);
  readTextField('strip_tools', ['strip_tools', 'tools']);
  return result;
}

function parseBooleanText(value: string): boolean {
  return ['1', 'true', 'yes', 'on', 'strip_tools'].includes(String(value || '').trim().toLowerCase());
}

function splitLines(value: string): string[] {
  return String(value || '')
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(Boolean);
}

export function buildEnabledPluginValue(name: string, opts: string): EnabledPluginValue {
  const pluginName = String(name || '').trim();
  const trimmedOpts = String(opts || '').trim();
  if (!pluginName) return '';
  if (!trimmedOpts) return pluginName;

  if (pluginName === 'key_guard') {
    const parsed = parseKeyGuardOptions(trimmedOpts);
    const params: Record<string, unknown> = {};
    const allowedUa = parsed.allowed_ua ?? parsed.ua;
    if (allowedUa) params.allowed_ua = splitLines(allowedUa);
    const stripTools = parsed.strip_tools ?? parsed.tools;
    if (stripTools !== undefined) params.strip_tools = parseBooleanText(stripTools);
    return Object.keys(params).length > 0 ? { name: pluginName, params } : pluginName;
  }

  return `${pluginName}:${trimmedOpts}`;
}
