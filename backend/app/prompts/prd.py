from pathlib import Path


SYSTEM_PROMPT = (
    "你是一个产品经理，具备丰富的产品知识。"
    "请根据用户提问的语言种类，使用相同语言回复用户。"
    "即使参考的 PRD 写作 skill、模板或资料是其他语言，也必须把章节标题、字段名、用户故事、说明文字和最终 PRD 内容全部改写为用户使用的语言。"
)

PRD_SKILL_PATH = Path(__file__).with_name("prd_skill.md")


def load_prd_skill() -> str:
    if not PRD_SKILL_PATH.exists():
        return "当前未配置 PRD 写作 skill。"
    return PRD_SKILL_PATH.read_text(encoding="utf-8").strip()


def build_prd_messages(
    requirement: str,
    contexts: list[dict],
    history: list[dict],
    *,
    rag_enabled: bool,
    writing_guidelines: str | None = None,
    source_context: str | None = None,
) -> list[dict]:
    context_text = _format_contexts(contexts)
    history_text = _format_history(history)
    guidelines = (writing_guidelines or load_prd_skill()).strip()
    rag_status = "已启用历史资料检索" if rag_enabled else "未启用历史资料检索"
    source_text = source_context.strip() if source_context else "无。"

    user_prompt = f"""
用户当前需求：
{requirement}

用户指定的外部需求背景：
{source_text}

PRD 写作 skill：
{guidelines}

注意：
- PRD 写作 skill 只作为方法论、流程和结构参考，不代表最终输出语言。
- 不要照搬 skill 中的英文标题、字段名或示例句式。
- 最终回复必须与用户当前需求使用同一种语言。
- 如果用户指定了外部需求背景，请优先把它作为当前 PRD 的业务输入，而不是历史引用。

短期对话记忆：
{history_text}

历史资料检索状态：
{rag_status}

参考资料：
{context_text}

请根据用户当前需求、用户指定的外部需求背景、短期对话记忆、PRD 写作 skill 和可选参考资料完成本轮 PRD 写作回复。
如果参考资料为空，请不要输出虚假的引用；如果参考资料只能覆盖部分内容，请明确说明缺口。
当前产品不支持自动提交 GitHub issue，因此只需要在对话中输出 PRD 内容。
""".strip()

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_contexts(contexts: list[dict]) -> str:
    if not contexts:
        return "无。"
    lines: list[str] = []
    for index, item in enumerate(contexts, start=1):
        location = [f"文件：{item['filename']}"]
        if item.get("page_no") is not None:
            location.append(f"页码：{item['page_no']}")
        if item.get("section_title"):
            location.append(f"标题：{item['section_title']}")
        if item.get("retrieval_note"):
            location.append(f"检索备注：{item['retrieval_note']}")
        lines.append(f"[{index}] {' | '.join(location)}\n{item['content'].strip()}")
    return "\n\n".join(lines)


def _format_history(history: list[dict]) -> str:
    if not history:
        return "无。"
    lines = []
    for item in history:
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{role}：{str(item.get('content', '')).strip()}")
    return "\n".join(lines)
