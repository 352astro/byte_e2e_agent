# TMP_DIR 不跟随 session checkout 回溯

## 现象

Session 执行 regret / restore / replay 时，transcript 列表正确截断，但 `TMP_DIR` 下的 task 文件不会被清理或回滚。被截断的 timeline 上产生过的 task 文件仍然残留在磁盘上。

## 影响

- 旧 task 文件占用磁盘空间
- 部分 task 文件可能被后续同 session 的新 task 意外读取或覆盖
- 回溯后 session 状态与文件系统状态不一致

## 预期行为

checkout 时应同步清理 TMP_DIR 中属于被截断 transcript 的 task 文件，使文件系统状态与 session timeline 对齐。
