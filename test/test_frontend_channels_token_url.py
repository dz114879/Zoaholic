from pathlib import Path


# 修改原因：Channels.tsx 中 token_url 曾经只在测试快照中出现，正式保存 payload 没有写入，导致 PUT 全量替换后字段丢失。
# 修改方式：用源码级回归测试固定保存快照和正式保存对象都必须保留 token_url 字段，即使字段为空字符串也不能被 JSON.stringify 删除。
# 目的：防止后续把 token_url 再次写成 `formData.token_url || undefined`，或遗漏到正式 targetProvider 保存对象之外。
ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "frontend" / "src" / "pages" / "Channels.tsx").is_file()
)
CHANNELS_TSX = ROOT / "frontend" / "src" / "pages" / "Channels.tsx"


def _read_channels_source() -> str:
    return CHANNELS_TSX.read_text(encoding="utf-8")


def _slice_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_provider_snapshot_payload_keeps_empty_token_url_field():
    source = _read_channels_source()
    snapshot_block = _slice_between(
        source,
        "const buildProviderSnapshotForTest = (): any => {",
        "const getProviderModelNameListForUi = (): string[] => {",
    )

    # 修改原因：测试弹窗使用的 provider 快照应与正式保存 payload 保持同样字段语义。
    # 修改方式：断言 token_url 直接来自 formData，而不是通过 || undefined 让空字符串在 JSON 序列化时丢失。
    # 目的：确保用户清空 token_url 时，测试链路和保存链路都能表达“空字符串”这个显式配置值。
    assert "token_url: formData.token_url," in snapshot_block
    assert "token_url: formData.token_url || undefined" not in snapshot_block


def test_provider_save_payload_includes_token_url_for_full_put_replace():
    source = _read_channels_source()
    save_block = _slice_between(
        source,
        "const targetProvider: any = {",
        "let newProviders: any[] | null = null;",
    )

    # 修改原因：/v1/providers/{id} 的 PUT 会用请求体整体替换 provider，不发 token_url 就等同删除旧字段。
    # 修改方式：正式保存对象必须始终包含 token_url: formData.token_url。
    # 目的：保证保存后 api.yaml、GET /v1/providers/{id} 和再次打开编辑面板都能看到同一份 token_url。
    assert "token_url: formData.token_url," in save_block
    assert "token_url: formData.token_url || undefined" not in save_block


def test_provider_edit_form_reads_token_url_from_latest_provider_response():
    source = _read_channels_source()
    open_modal_block = _slice_between(
        source,
        "const openModal = async (provider: any = null, index: number | null = null) => {",
        "const updateFormData = (field: keyof ProviderFormData, value: any) => {",
    )

    # 修改原因：保存链路修复后，回显链路也必须继续从 GET 到的最新 provider 对象读取 token_url。
    # 修改方式：断言表单初始化使用 activeProvider.token_url，并且 activeProvider 是单渠道 GET 的结果或回退值。
    # 目的：覆盖“保存、持久化、GET、formData 初始化”完整链路中的前端回显入口。
    assert "const activeProvider = freshProvider;" in open_modal_block
    assert "token_url: activeProvider.token_url || ''," in open_modal_block
