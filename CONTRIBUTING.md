# 贡献指南

感谢关注这个项目！贡献前请阅读以下要点。

## 行为边界（红线）

1. **不接受任何破解、绕过或规避加密/鉴权/访问控制的代码。** 本项目定位是
   与自有设备的开放互操作，不做也不收录这类内容（包括云端协议、设备密钥
   恢复、DRM 规避等）。
2. **不提交厂商官方资产**：官方 App/驱动/安装包的任何部分、反编译产物、
   官方文档原文。讨论协议时请基于自观测并整理为规格描述。
3. **不提交个人或敏感信息**：真实内网地址、设备序列号、MAC、个人路径。
   详见 [docs/OPEN-SOURCE-CHECKLIST.md](docs/OPEN-SOURCE-CHECKLIST.md)。

## 开发环境

```powershell
git clone <repo-url>
cd paperang-p1-connect
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
git config core.hooksPath .githooks   # 启用提交前敏感信息扫描
```

## 提交要求

- 改动带测试；`pytest -q` 全绿（无需真实设备）。
- 涉及设备通信语义（时序、错误处理、任务状态）的改动，请说明依据
  （实机观测 / 协议规格章节），不要凭猜测放宽校验。
- 提交信息用简洁祈使句（中英文均可），例如
  `fix: 在分片边界停止发送后关闭会话`。

## 新机型适配

欢迎为其他 Paperang 机型/固件做适配！建议流程：

1. 按 [docs/protocol-a5.md](docs/protocol-a5.md) 的格式观测并整理该机型的
   命令表差异（可开 issue 讨论）。
2. 在 `device_a5.py` 的兼容性判断处增加机型条件，避免影响已验证机型。
3. 提供测试向量（帧字节 + 语义标注，不含会话身份字段）。

## Issue

- Bug：使用 `.github/ISSUE_TEMPLATE/bug_report.md`，附服务日志与任务状态。
- 新机型：使用 device-compat 模板，附设备型号、固件版本与观测现象。
