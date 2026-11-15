# astrbot_plugin_llm_keyword_interceptor · LLM 调用关键词拦截

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.0-5B6CFF)](https://github.com/AstrBotDevs/AstrBot)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](metadata.yaml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

消息命中关键词时，只掐断 AstrBot 默认的 LLM 调用，**不终止事件**。有人发「机器人闭嘴」，AI 不接话，其他插件照常工作。

## 功能

- 全局监听私聊、群聊消息（`EventMessageType.ALL`）
- 命中 `block_words` 任意一词 → `event.should_call_llm(True)`，本条消息不进大模型
- 不使用 `event.stop_event()`，不发送任何消息，其他插件不受影响
- 大小写可配置，命中可选打印日志

## 支持平台

插件只改事件上的 `call_llm` 标志，与平台协议无关，因此声明支持 AstrBot 全部 19 个平台适配器：

`aiocqhttp` · `qq_official` · `qq_official_webhook` · `telegram` · `wecom` · `wecom_ai_bot` · `lark` · `dingtalk` · `discord` · `slack` · `kook` · `vocechat` · `weixin_official_account` · `weixin_oc` · `satori` · `misskey` · `line` · `matrix` · `mattermost`

## 安装

### 方式一：Git

```bash
cd AstrBot/data/plugins
git clone https://github.com/TonyV2Intl/astrbot_plugin_llm_keyword_interceptor.git
```

### 方式二：手动

1. 将 `astrbot_plugin_llm_keyword_interceptor` 整个目录放入 `AstrBot/data/plugins/`
2. 重启 AstrBot，或在 WebUI → 插件管理中重载
3. 在插件配置页填写 `block_words`，保存后生效

也可以把本目录打包成 zip，通过 WebUI「安装插件 → 从文件安装」上传。

> 需要 AstrBot 4.x。`@register` 装饰器自 v3.5.19 起可选，本插件未使用。

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `block_words` | list | `["机器人闭嘴","/群内其他bot的指令"]` | 拦截关键词，包含即命中 |
| `case_sensitive` | bool | `false` | 是否区分大小写 |
| `log_hit` | bool | `true` | 命中时打印日志 |

> 默认第二项 `/群内其他bot的指令` 是占位示例，演示「拦截群里其他机器人的指令」这类场景，请替换成你实际要拦的词。

## 实现要点

### 1. `should_call_llm` 的参数含义与字面意思相反

AstrBot 的 `call_llm` 字段语义是「**是否禁止**默认 LLM 请求」，字段默认值为 `False`：

```python
# astrbot/core/platform/astr_message_event.py
self.call_llm = False
"""是否在此消息事件中禁止默认的 LLM 请求"""

def should_call_llm(self, call_llm: bool) -> None:
    self.call_llm = call_llm
```

判定发生在 `astrbot/core/pipeline/process_stage/stage.py`：

```python
if (
    not event._has_send_oper
    and event.is_at_or_wake_command
    and not event.call_llm      # ← 只有 call_llm 为 False 才调用 LLM
):
    ... 请求大模型 ...
```

所以：

| 写法 | 实际效果 |
|---|---|
| `event.should_call_llm(True)` | **禁止** LLM（本插件采用） |
| `event.should_call_llm(False)` | 允许 LLM，等于没做事 |

### 2. 唤醒前缀会把 `message_str` 改掉

`astrbot/core/pipeline/waking_check/stage.py` 命中唤醒前缀时会重写消息文本：

```python
event.message_str = event.message_str[len(wake_prefix) :].strip()
```

默认 `wake_prefix` 是 `["/"]`，于是用户发 `/路线` 时 `event.message_str` 变成 `路线`，配置里的 `/路线` 永远匹配不上。

插件因此在 `event.message_str` 之外，额外匹配 `event.message_obj.message_str`（原始文本，未被改写），两者任一命中即拦截。

## 目录结构

```
astrbot_plugin_llm_keyword_interceptor/
├── main.py              # 插件入口
├── _conf_schema.json    # 配置 Schema
├── metadata.yaml        # 插件元数据
├── logo.png             # 插件图标
├── requirements.txt     # 依赖声明（无第三方依赖）
├── pyproject.toml       # ruff 配置
├── LICENSE
└── README.md
```

## 验证

1. 私聊发送 `机器人闭嘴` → 机器人不回复，日志出现：
   `命中拦截词 [机器人闭嘴]，已禁止本条消息的默认 LLM 请求（事件继续传播）。`
2. 群里 @机器人 发送 `/群内其他bot的指令` → 对应插件正常返回结果，且大模型没有额外回复
3. 发送不含关键词的普通消息 → AI 正常回复

## 常见问题

**Q：为什么明明拦截了，别的插件还能响应？**
A：因为插件只改了 `call_llm` 标志，事件继续在 pipeline 中传播，其他 handler 照常执行。这正是与 `stop_event()` 的区别。

**Q：群聊里没 @ 机器人，消息也被检查了吗？**
A：会。`EventMessageType.ALL` 覆盖所有入站消息。未唤醒的消息本来就不会调用 LLM，插件设置标志只是幂等的保险操作，不会导致 AI 乱回复。

**Q：改了配置需要重启吗？**
A：插件每次处理消息都实时读取 `self.config`，在 WebUI 保存配置后即生效；若你的 AstrBot 版本保存配置会重载插件，也无需手动重启。

**Q：想彻底不让某个命令被任何插件处理怎么办？**
A：那不是本插件的职责，应该用 `event.stop_event()`。本插件刻意不这么做。

## License

[MIT](LICENSE) © 2026 TonyV2Intl
