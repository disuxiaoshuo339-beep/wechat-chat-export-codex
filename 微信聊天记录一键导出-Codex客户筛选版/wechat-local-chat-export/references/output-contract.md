# 输出契约

成功交付 ZIP 只允许包含：

- `客户聊天索引.xlsx`（无 `openpyxl` 时为 `客户聊天索引.csv`，二者只出现一个）
- `聊天记录_HTML/*.html`
- `聊天记录_CSV/*.csv`
- `导出摘要.json`
- `README.txt`

不得包含数据库、WAL/SHM、密钥文件、进程转储、源快照、私有工作目录、日志、测试缓存，也不得包含 `客户索引数据.json`、`会话清单.csv`、`run-state.json`、`source-manifest.csv`、`final-result.json` 这些中间文件。其中 `会话清单.csv` 尤其敏感——它列出了用户的全部私聊联系人，包括未勾选的私人联系人。

验收条件：

- 索引表行数 = 用户勾选为客户的会话数。
- HTML 数 = CSV 数 = 勾选会话数。
- 每位客户消息数与其 CSV 数据行数一致。
- 导出消息总数 = 我发送 + 客户发送 + 未知方向。
- 勾选会话数 + 筛除会话数 = 库中一对一私聊会话总数（`导出摘要.json` 里的 `private_conversations` + `screened_out_conversations`）。
- ZIP 文件清单通过禁入检查并可完整 CRC 解压测试。
