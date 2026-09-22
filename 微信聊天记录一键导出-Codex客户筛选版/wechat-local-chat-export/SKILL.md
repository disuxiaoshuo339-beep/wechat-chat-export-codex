---
name: wechat-local-chat-export
description: Use when a Windows user asks to export, 整理, 备份, 取数, or analyze an authorized local Windows WeChat 4.x account's chat history, with a mandatory human screening gate that limits the export to conversations the user marks as customers.
---

# 微信本地聊天记录导出（客户筛选版）

把用户明确授权的 Windows 微信 4.x 本地账号里、**用户本人逐条勾选确认过的客户会话**，整理为一对一聊天 HTML、CSV、Excel 索引和摘要 ZIP。全程只在本机处理。

与全量导出版的唯一区别：中间多了一道「会话清单 → 人工勾选 → 只导出勾中的」筛选闸门。私人会话（亲友、同事、非客户）的聊天正文从头到尾不会被读取，也不会进入交付物。

## 不可越过的授权门

附件和「开始导出」只授权只读预检，不授权任何具体账号。即使只发现一个账号，也要列出完整账号 ID，并取得用户对该准确 ID 的明确回复。不得按目录大小、修改时间或「看起来像主账号」自动选择。

只处理用户本人或用户明确声明有权处理的账号。不得读取无关私人目录，不得上传聊天内容，不得保存或输出密钥，不得安装依赖、删除文件、覆盖源文件或修改微信。

## 不可越过的筛选门

第 4 步生成的 `会话清单.csv` 是本流程的闸门：

- 清单只由联系人**元数据**构成（备注名、昵称、微信号、消息条数、首末时间）。生成它时脚本只跑 `COUNT/MIN/MAX` 聚合，不 SELECT 任何消息正文字段。
- 清单里的「自动判定」列只是关键词猜测（涂料/化工词、手机号备注、公司-人名形态、企业微信联系人→疑似客户；亲属称谓→私人），**不是结论**，必须由用户复核。
- **你不要读取这份 CSV**。它含有用户的私人联系人姓名。让用户自己打开确认，脚本只会把数量统计返回给你。
- 第 5 步只会导出「是否客户」列填了 `Y` 的会话。未勾选的会话，脚本在发出任何正文查询之前就跳过了。

## 执行流程

1. 确认附件包完整，当前系统为 Windows，微信 4.x 已登录并保持运行，并阅读 `references/compatibility-and-safety.md` 与 `references/output-contract.md`。

2. 在 Skill 根目录运行 `python scripts/preflight.py`。这一步只读发现环境和账号。

3. 将预检结果中的账号 ID 原样展示给用户，要求明确授权准确账号。未授权前停止。

4. 授权后建立本机快照并解密：

   `python scripts/prepare_snapshot.py --account-id "准确账号ID"`

   如需指定用户同意的输出位置，加 `--output-root "绝对路径"`。不得把输出写回微信数据目录。记下返回的 `run_root`。

5. 生成会话清单（零正文）：

   `python scripts/list_conversations.py --run-root "run_root"`

   脚本返回私聊会话总数、疑似客户数、私人数、待定数，并在 `run_root\会话清单.csv` 落盘。

6. **停下来交给用户**。原话告诉用户：请用 Excel 打开 `run_root\会话清单.csv`，在最后一列「是否客户」里确认——`Y` 表示导出，留空表示不导出，`?` 是脚本拿不准的，请人工判断后改成 `Y` 或清空。改完保存为 CSV（UTF-8）。你不要打开这个文件。等用户回复「已确认」再继续。

7. 只导出勾选的会话：

   `python scripts/run_export.py --run-root "run_root"`

   （清单不在默认位置时加 `--selection "绝对路径"`。）

8. 生成索引表：

   `python scripts/build_index.py --run-root "run_root"`

   优先出 `客户聊天索引.xlsx`；本机没有 `openpyxl` 时会降级成 `客户聊天索引.csv` 并在返回里注明。降级可接受，也可在征得用户同意后 `pip install openpyxl` 重跑本步。

9. 对账、打包、清理明文中间产物：

   `python scripts/finalize_delivery.py --run-root "run_root" --purge-workspace`

   `--purge-workspace` 会在 ZIP 校验通过后删除 `run_root\source_copy` 与 `run_root\private`——这两个目录里是解密后的完整明文数据库，**包含未导出的私人会话**，留在磁盘上等于筛选白做了。除非用户明确要求保留以便重跑，否则必须带上这个开关。

10. 只在终态为 `complete` 且对账、文件类型和 ZIP CRC 都通过后宣布完成，并给出交付 ZIP 的绝对路径、客户会话数和消息数。同时告诉用户被筛除的会话数（只报数字）。

## 失败处理

- 缺少 `pycryptodomex`、`zstandard` 或 `openpyxl` 时，说明用途并询问用户是否允许做依赖安装；未授权不得安装。`openpyxl` 缺失不阻塞流程（降级 CSV）。
- 微信不是 4.x、微信未运行、核心数据库缺失、密钥未覆盖全部数据库、SQLite 校验失败、WAL 异常或数量不守恒时停止。
- 会话清单一行都没勾 `Y` 时脚本会报错停止，这是预期行为——回到第 6 步让用户确认。
- 不要用过期快照或部分成功结果冒充全量。修复条件后创建新的运行目录重跑。
- 错误报告只给阶段、错误类型和可操作建议；不要粘贴聊天正文、联系人姓名、密钥或数据库二进制内容。
