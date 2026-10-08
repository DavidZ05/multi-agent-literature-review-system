# 中文快速开始

该项目是本地优先的文献综述工作流。SQLite 数据库、论文审批记录和运行产物默认保存在本机；只有启用外部检索源或模型 API 时，相关查询和提示才会发送到对应服务。

## 安装

系统支持 macOS 或 Linux，以及 Python 3.11–3.12：

```bash
git clone https://github.com/DavidZ05/multi-agent-literature-review-system.git
cd multi-agent-literature-review-system
python3 -m pip install -e .
literature-review doctor
```

`doctor` 会初始化本地存储并检查语料与配置，不会调用模型或文献检索服务。

## 启动工作台

```bash
literature-review-workbench
```

浏览器会打开 `http://127.0.0.1:8765/`。工作台仅监听本机回环地址，不应直接暴露到公网。

## 创建可恢复任务

```bash
literature-review start \
  --topic "Memory-Augmented LLM Agents" \
  --corpus data/papers.json \
  --discover \
  --providers arxiv semantic_scholar \
  --max-results 10
```

命令返回的 `run_id` 用于查询、恢复和取消任务：

```bash
literature-review status RUN_ID
literature-review events RUN_ID
literature-review resume RUN_ID
literature-review cancel RUN_ID
```

自动检索完成后，流程会停在人工语料审批节点。候选论文只有在人工批准并补齐分类、贡献和理由后，才能进入 Writer 的可引用语料。

## API 模式

默认的 deterministic 模式不需要 API key。使用兼容 OpenAI 协议的模型时：

```bash
cp .env.example .env
set -a
source .env
set +a
literature-review doctor
```

不要提交 `.env`，也不要在截图、Issue 或导出的日志中公开密钥。本项目的模型插件不能绕过语料审批、引用门禁和最终验证。

## 继续阅读

- [完整工作流](../workflow.md)
- [可靠性与审计](../reliability.md)
- [安全边界](../security.md)
- [GitHub 仓库](https://github.com/DavidZ05/multi-agent-literature-review-system)
