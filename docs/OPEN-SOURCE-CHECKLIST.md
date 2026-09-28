# 开源合规自查清单（提交前 / 发布前）

本清单是维护者与贡献者共用的守门文档。**每个提交前过一遍第 1 节；
每次发版/公开推送前过全文。** CI 会自动跑其中的机器可查项
（`scripts/check_sensitive.py` + 测试）。

## 1. 每次提交前（1 分钟）

- [ ] `python scripts/check_sensitive.py --staged` 通过（本地 pre-commit
      钩子已配置 `git config core.hooksPath .githooks` 时自动执行）。
- [ ] 新增内容里没有：真实内网 IP（用 192.168.1.x / 192.0.2.x 示例段）、
      设备序列号、蓝牙 MAC（占位 `AA:BB:CC:DD:EE:FF`）、个人用户名/邮箱、
      个人绝对路径（Windows 用户目录、本机仓库盘符路径等）。
- [ ] 没有引用 `.refs/`、`vendor/` 等本地目录的内容。
- [ ] 涉及设备通信的改动有对应测试，且 `pytest -q` 全绿。

## 2. 新增第三方依赖时

- [ ] 查明 SPDX 许可证标识；只接受 MIT/BSD/Apache-2.0/PSF/ISC/MPL-2.0
      等宽松许可。**AGPL/GPL 组件默认拒绝**（本项目 MIT，需保持可组合性）。
- [ ] LGPL（如 pystray、zeroconf）：只允许以 pip 独立包引用，禁止把源码
      复制进本仓库；在 `THIRD-PARTY-NOTICES.md` 登记义务说明。
- [ ] 同步更新 `requirements.txt`、`pyproject.toml` 与
      `THIRD-PARTY-NOTICES.md`。

## 3. 新增设备侧脚本时（A/B 分类）

- **可发布（A 类）**：走产品 API/产品代码、无硬编码设备标识、输出到
  临时目录或仓库内被 ignore 的路径。
- **不发布（B 类）**：引用 `.refs`、硬编码实验设备地址、复现抓包/回放/
  反编译流程的脚本。放进 `.gitignore` 的 scripts 清单（本地保留）。

## 4. 协议逆向新发现时

- [ ] 先更新公开规格 `docs/protocol-a5.md`（帧格式/命令语义/约束），
      再写实现；方法论细节（工具链、过程）只写在本地日记，不入库。
- [ ] **红线**：任何破解设备加密、绕过云端鉴权、规避访问控制的代码或
      算法**永不入库**（CONTRIBUTING.md 有同样声明）。
- [ ] 抓包测试向量只包含帧字节与语义标注，不包含会话身份字段。

## 5. 发布 / 公开推送前

- [ ] `git ls-files` 全量过目一遍，确认没有多余文件。
- [ ] `python scripts/check_sensitive.py`（全仓库）零命中。
- [ ] `pytest -q` 与 `flutter test`（flutter/ 下）全绿；CI 绿。
- [ ] **Release 附件只允许本项目源码构建出的产物**（Android APK、Windows
      安装器），仍禁止附带任何厂商资产或第三方二进制库；附件必须附
      SHA256SUMS；签名密钥材料（`*.jks`、`*.keystore`、`key.properties`）
      **永不入库**，只存在于本地与 CI secrets。
- [ ] 版本号与 `pyproject.toml`、`flutter/pubspec.yaml` 一致，CHANGELOG 或
      Release notes 就绪。

## 6. 后续仓库（如 Flutter 移动端）沿用本清单

- Flutter/Dart 仓库同样 MIT，复制本清单与 `check_sensitive.py`
  （按语言适配模式）+ pre-commit/CI 双保险。
- 协议实现只引用公开规格 `docs/protocol-a5.md`；任何来自本地 `.refs/`
  素材（反编译产物、官方抓包）的内容不得进入新仓库。
- 平台通道等原生代码遵循同样的敏感信息规范。
