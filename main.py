"""关键词拦截插件（Block Words）。

设计目标只有一条：消息命中关键词时，**只关闭 AstrBot 默认的 LLM 请求链路**，
事件的传播不受影响，其他插件（命令插件、工具插件、定时任务等）仍能正常处理
同一条消息。

因此本插件：
  * 不调用 event.stop_event()；
  * 不 yield / 发送任何消息（发送消息同样会让框架跳过 LLM）；
  * 只调用 event.should_call_llm(...) 设置「禁止默认 LLM 请求」标志。
"""

from __future__ import annotations

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class LLMKeywordInterceptorPlugin(Star):
    """命中 block_words 中的任意关键词时，禁止本条消息触发默认 LLM 回复。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        # 注意：Star.__init__ 只保存 context，不会把 config 挂到实例上，
        # 所以这里必须自己保存。插件没有 _conf_schema.json 或配置为空时，
        # loader 只会传 context，此时 config 为 None。
        self.config = config or {}

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    def _get_rules(self) -> tuple[list[tuple[str, str]], bool]:
        """读取配置并规范化拦截词。

        Returns:
            (rules, case_sensitive)
            rules 为 (原始词, 用于比较的词) 列表；原始词用于日志展示。
        """
        raw = self.config.get("block_words") or []
        if isinstance(raw, str):
            # 兼容用户在配置文件里手写成一整行字符串的情况
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            logger.warning(
                "block_words 配置格式不正确，应为字符串列表，当前为 %r", type(raw)
            )
            return [], False

        case_sensitive = bool(self.config.get("case_sensitive", False))

        rules: list[tuple[str, str]] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            word = item.strip()
            if not word:
                continue
            rules.append((word, word if case_sensitive else word.lower()))
        return rules, case_sensitive

    @staticmethod
    def _match(
        text: str, rules: list[tuple[str, str]], case_sensitive: bool
    ) -> str | None:
        """返回命中的原始关键词，未命中返回 None。"""
        if not text:
            return None
        haystack = text if case_sensitive else text.lower()
        for original, needle in rules:
            if needle in haystack:
                return original
        return None

    # ------------------------------------------------------------------ #
    # 核心：全局消息监听
    # ------------------------------------------------------------------ #

    # ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE，覆盖私聊与群聊。
    # priority 数值越大越先执行（AstrBot 内部按 -priority 升序排列），
    # 提前执行可以保证在别的 handler 终止事件前就写好标记。
    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def intercept_message(self, event: AstrMessageEvent):
        rules, case_sensitive = self._get_rules()
        if not rules:
            return

        # 唤醒阶段会把唤醒前缀（默认 "/"）从 event.message_str 中剥掉，
        # 例如 "/路线" 会变成 "路线"，导致配置里写 "/路线" 匹配不到。
        # 因此额外用 message_obj 中未被修改的原始文本再匹配一次。
        candidates = [event.message_str]
        raw_text = getattr(event.message_obj, "message_str", "")
        if raw_text and raw_text != event.message_str:
            candidates.append(raw_text)

        for text in candidates:
            hit = self._match(text, rules, case_sensitive)
            if hit is None:
                continue

            # 关键：AstrBot 中 call_llm 字段的含义是「是否禁止默认 LLM 请求」，
            # 默认 False（允许）。因此传 True 才是阻断，传 False 等于放行。
            # 参考 astrbot/core/pipeline/process_stage/stage.py：
            #     if not event._has_send_oper and event.is_at_or_wake_command \
            #             and not event.call_llm:
            #         ... 调用 LLM ...
            event.should_call_llm(True)

            if self.config.get("log_hit", True):
                logger.info(
                    "命中拦截词 [%s]，已禁止本条消息的默认 LLM 请求（事件继续传播）。",
                    hit,
                )
            # 命中一个即可，直接返回；绝不能调用 event.stop_event()
            return

    async def terminate(self) -> None:
        """插件被禁用或重载时调用。"""
        logger.debug("关键词拦截插件已停止。")
