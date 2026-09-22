# 使用 Codex 在本机导出微信客户聊天记录

**先把代码克隆到自己的 Windows 电脑，再在本机操作。聊天记录、会话清单、数据库、密钥和导出结果只留在本机，不要上传到 GitHub。**

本仓库公开的是工具源码、说明和合成测试。使用者不需要加入协作者，也不需要把自己的数据发给仓库作者。

## 1. 拉取到本机

在 Windows PowerShell 中进入自己准备放工具代码的目录，执行：

```powershell
git clone https://github.com/disuxiaoshuo339-beep/wechat-chat-export-codex.git
cd wechat-chat-export-codex
```

以后只更新工具代码时，在这个目录执行 `git pull --ff-only`。普通使用不需要 fork，也不需要 `git add`、`git commit` 或 `git push`。

没安装 Git 时，也可 [下载工具 ZIP](downloads/微信聊天记录一键导出-Codex客户筛选版.zip?raw=true)，解压到本机。这个 ZIP 是工具；程序运行后产生的“微信客户聊天记录_交付.zip”是私人数据，两者不要混淆。

## 2. 在 Codex 本地项目里运行

在 Codex Desktop 中打开刚克隆的仓库目录作为本地项目，让任务在当前 Windows 电脑执行。复制发送：

```text
请先阅读根目录 AGENTS.md，以及
微信聊天记录一键导出-Codex客户筛选版/START_HERE.md。
按其中流程帮我导出本机微信客户聊天记录，现在只做只读预检。

账号由我明确确认，会话清单由我本人打开并勾选。
使用仓库外的默认本地输出位置。
禁止把聊天正文、联系人清单、数据库、密钥、日志或导出结果发到对话或 GitHub。
不要执行 git add、git commit、git push，也不要用 GitHub Actions/Codespaces 运行导出。
```

之后按 [完整操作说明](微信聊天记录导出方法_Codex版.md) 完成账号确认、人工勾选、导出和核验。微信应保持登录运行。

## 3. 数据保存在哪里

默认输出位置是本机 `%LOCALAPPDATA%\WeChatChatExport\runs`，与克隆目录分开。程序不会以当前仓库下的 `outputs` 作为备用位置。

标准导出入口会拒绝把运行数据写进 Git 仓库或工具目录。仓库与工具包中的 `.gitignore` 仅放行已列出的源码和说明，其他新文件默认忽略；不要用 `git add -f` 绕过，也不要把聊天内容粘进已有源码或说明文件。

**不要把任何实际聊天数据放进 GitHub 的提交、Issue、PR、Gist、Release、Actions 日志或附件。** 需要反馈问题时，只提供脱敏的错误类型、版本和合成复现，不附真实联系人、完整日志或截图。

Codex 使用过程中可能联网；聊天数据由本机脚本处理，不要求把正文交给模型。筛选前会产生含未选会话的本机解密中间库，完成后按说明清理；会话清单需本人另行保管或删除。

## 适用范围

- Windows、Python 3.11+、正在运行的微信 4.x；具体小版本仍需在使用者电脑上检查。
- 仅导出本人确认的一对一会话，默认排除群聊、公众号及系统账号。
- 整理本机已有消息记录，不承诺完整多媒体备份、手机历史完整同步或已删除消息恢复。
- 本项目不是微信或 OpenAI 官方产品；静态检查与合成测试不等于对所有微信版本的兼容保证。

发布检查见 [PRIVACY_CHECK.md](PRIVACY_CHECK.md)。代码使用 [MIT 许可证](LICENSE)。第三方 Python 依赖由使用者按各自许可证安装，未打包进本项目。
