"""安全校验工具：路径防穿越 + 危险指令拦截。

safety.py 负责命令字符串级别的预检（第一道防线）。
sysguard.py 负责内核级文件/网络访问拦截（第二道防线）。
两层的职责划分：
  safety.py — 拦截进程行为攻击（提权、反弹shell、下载执行、环境投毒等）
  sysguard  — 拦截文件访问攻击（敏感文件读取、越界写入、持久化文件篡改等）

精简后的 safety.py 不再包含文件访问相关的模式——这些由 sysguard 在内核层兜底。
"""

from __future__ import annotations

import os
import re
import unicodedata

# ============================================================
# 路径安全检查
# ============================================================


def safe_resolve_path(path: str, workspace_root: str) -> str:
    """将相对路径解析为绝对路径，确保不超出 workspace_root。"""
    abs_path = os.path.realpath(os.path.join(workspace_root, path))
    real_root = os.path.realpath(workspace_root)

    if abs_path != real_root and not abs_path.startswith(real_root + os.sep):
        raise ValueError(
            f"Path safety check failed: '{path}' attempts to escape the workspace"
        )
    return abs_path


# ============================================================
# 危险指令拦截
# ============================================================

# ── Unicode 安全检测 ────────────────────────────────────

_SUSPICIOUS_UNICODE_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u202f\u200d"
    r"\u0430-\u044f\u0450-\u045f\u03b1-\u03c9\u0300-\u036f"
    r"\u0400-\u04ff\u0370-\u03ff]"
)


def _check_unicode_safety(command: str) -> None:
    match = _SUSPICIOUS_UNICODE_RE.search(command)
    if match:
        code = ord(match.group())
        if 0x200B <= code <= 0x200F:
            tag = {
                0x200B: "zero-width space",
                0x200D: "zero-width joiner",
                0x200F: "LRM marker",
            }.get(code, "zero-width")
            raise ValueError(f"Dangerous command blocked ({tag}): unicode obfuscation")
        elif 0x202A <= code <= 0x202E:
            raise ValueError("Dangerous command blocked (RTLO): unicode bidi override")
        elif code == 0x202F:
            raise ValueError(
                "Dangerous command blocked (narrow no-break space): unicode obfuscation"
            )
        elif 0x0300 <= code <= 0x036F:
            raise ValueError(
                "Dangerous command blocked (combining chars): unicode obfuscation"
            )
        elif 0x0430 <= code <= 0x044F or 0x03B1 <= code <= 0x03C9:
            raise ValueError(
                "Dangerous command blocked (homoglyph greek/cyrillic character): "
                "potential homoglyph attack"
            )
        elif 0x0400 <= code <= 0x04FF or 0x0370 <= code <= 0x03FF:
            raise ValueError(
                "Dangerous command blocked (homoglyph greek/cyrillic character): "
                "potential homoglyph attack"
            )

    normalized = unicodedata.normalize("NFKC", command)
    if normalized != command:
        raise ValueError(
            "Dangerous command blocked (homoglyph greek/cyrillic character): "
            "NFKC normalization changed command"
        )


_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # ═══════════════════════════════════════════════════════
    # 0. Unicode 混淆（regex 兜底）
    # ═══════════════════════════════════════════════════════
    (r"[\u200b-\u200f]", "zero-width space obfuscation"),
    (r"[\u202a-\u202e]", "RTLO bidi override"),
    (r"\u202f", "narrow no-break space obfuscation"),
    (r"\u200d", "zero-width joiner obfuscation"),
    (r"\u200f", "LRM marker obfuscation"),
    (r"[\u0300-\u036f]", "combining chars obfuscation"),
    (r"[\u0430-\u044f\u03b1-\u03c9]", "homoglyph greek/cyrillic character"),
    # ═══════════════════════════════════════════════════════
    # 1. Bash 陷阱 / PROMPT_COMMAND / PS1-4 / shopt
    #    必须在 $() 等通用模式之前
    # ═══════════════════════════════════════════════════════
    (
        r"\btrap\b\s+['\"].*['\"]\s+(?:DEBUG|ERR|EXIT|RETURN)\b",
        "trap DEBUG trap ERR trap EXIT trap RETURN",
    ),
    (r"\bBASH_ENV\b.*\btrap\b", "BASH_ENV trap injection"),
    (r"\bPROMPT_COMMAND\s*=", "PROMPT_COMMAND obfuscated injection"),
    (r"\bPS[1234]\s*=\s*['\"]?\s*\$\(.*(?:cat|/etc/)", "PS4 injection"),
    (r"\bPS[1234]\s*=\s*['\"]?\s*\$\(", "PS1 injection"),
    (r"\bPS[1234]\s*=", "PS1/PS2/PS3/PS4 injection"),
    (r"\bshopt\b\s+-s\s+extdebug\b", "shopt extdebug trap"),
    # ═══════════════════════════════════════════════════════
    # 2. 数据外泄 (含 $() ) / 间接执行 — 必须在 $() 之前
    # ═══════════════════════════════════════════════════════
    (r"\bdig\b.*\$\(.*(?:/etc/|\.ssh|whoami)", "dns exfil via dig"),
    (r"\bnslookup\b.*\$\(.*(?:whoami|/etc/|id\b)", "dns exfil via nslookup"),
    (r"\bhost\b.*\$\(.*(?:/etc/|head\b)", "dns exfil via host"),
    (r"\bping\b.*-p\s*\$\(.*(?:echo|cat|xxd)", "icmp exfil via ping"),
    (
        r"\bnohup\b\s+.*\b(?:ba)?sh\b\s+-c\b.*(?:\bnc\b|cat\s+/etc/)",
        "nohup wrapper execution",
    ),
    (r"\bionice\b\s+.*\b(?:ba)?sh\b\s+-c\b.*\bnc\b", "ionice wrapper execution"),
    (r"\bfind\b.*\s+-exec(?:dir)?\s", "find -exec execution"),
    (r"\bscreen\b.*\s+-X\s+exec\b", "screen exec escape"),
    (r"\beval\b\s+\$\(\s*printf\b", "printf nested eval"),
    (r"\$\(.*\$\(.*\$\(", "nested command sub"),
    # ═══════════════════════════════════════════════════════
    # 3. ANSI 转义
    # ═══════════════════════════════════════════════════════
    (r"\\x1b\[2A.*\\x1b\[K", "ANSI escape sequence"),
    (r"\\x1b\]0;", "ANSI title injection"),
    (r"\\x1b\]52;", "ANSI clipboard injection"),
    (r"\\x1b\[30;40m", "ANSI color hide"),
    (r"\\x1b\[s.*\\x1b\[.*H.*\\x1b\[u", "ANSI cursor spoof"),
    (r"\\r\\x1b\[K", "ANSI carriage return hide"),
    (r"\\x1b\[", "ANSI escape sequence"),
    (r"\\e\]8;", "OSC hyperlink injection"),
    (r"\\e\[8;\d+;\d+t", "ANSI resize DoS"),
    # ═══════════════════════════════════════════════════════
    # 4. 进程替换 / 命令替换
    # ═══════════════════════════════════════════════════════
    (r"<\(\s*", "process substitution <()"),
    (r">\(\s*", "process substitution >()"),
    (r"`[^`]+`", "backtick command substitution"),
    (r"\$\(\s*", "$() command substitution"),
    # ═══════════════════════════════════════════════════════
    # 5. Shell 内建 / 元字符
    # ═══════════════════════════════════════════════════════
    (r"\|\s*(?:nc|ncat|netcat)\b", "pipe to nc"),
    (r"\beval\b\s+", "eval execution"),
    (r"\bexec\b\s+/(?:bin|usr/bin)/", "exec builtin"),
    (r"(?:^|[;&|])\s*source\s+", "source builtin"),
    (r"(?:^|\s|;)\s*\.\s+/", "dot source execution"),
    (r"\balias\b\s+\w+\s*=", "alias abuse"),
    (r"\{\s*\w+,/[^\}]+\}", "brace expansion file access"),
    (r"<<\s*\w+.*>\s*/etc/", "heredoc overwrite system file"),
    # ═══════════════════════════════════════════════════════
    # 6. 混淆绕过
    # ═══════════════════════════════════════════════════════
    (r"\\x[0-9a-fA-F]{2}", "hex-escaped character (obfuscation)"),
    (r"\\u[0-9a-fA-F]{4}", "unicode-escaped character (obfuscation)"),
    (r"\\[0-7]{3}", "octal escaped character (obfuscation)"),
    (r"\bprintf\b\s+['\"].*\\x[0-9a-fA-F]{2}", "printf obfuscation"),
    (r"\$\{IFS\}", "${IFS} whitespace masquerade"),
    (r"\$\w+\s+\$\w+\s+\$\w+", "variable concatenation obfuscation"),
    (r"\$@", "$@ argument vector injection"),
    # ═══════════════════════════════════════════════════════
    # 7. 环境变量投毒
    # ═══════════════════════════════════════════════════════
    (r"\bLD_KEEPDIR\b.*\bLD_PRELOAD\b", "LD_KEEPDIR bypass injection"),
    (r"\bLD_KEEPDIR\s*=", "LD_KEEPDIR bypass injection"),
    (r"\bLD_PRELOAD\s*=", "LD_PRELOAD injection"),
    (r"\bLD_LIBRARY_PATH\s*=", "LD_LIBRARY_PATH injection"),
    (r"\bLD_AUDIT\s*=", "LD_AUDIT injection"),
    (r"\bLD_DEBUG\s*=", "LD_DEBUG injection"),
    (r"\bLD_PROFILE\s*=", "LD_PROFILE injection"),
    (r"\bLD_ORIGIN_PATH\s*=", "LD_ORIGIN_PATH injection"),
    (r"\bPYTHONPATH\s*=", "PYTHONPATH injection"),
    (r"\bPYTHONSTARTUP\s*=", "PYTHONSTARTUP injection"),
    (r"\bPERL5LIB\s*=", "PERL5LIB injection"),
    (r"\bPERL5OPT\s*=", "PERL5OPT injection"),
    (r"\bRUBYLIB\s*=", "RUBYLIB injection"),
    (r"\bRUBYOPT\s*=", "RUBYOPT injection"),
    (r"\bNODE_PATH\s*=", "NODE_PATH injection"),
    (r"\bNODE_OPTIONS\s*=", "NODE_OPTIONS injection"),
    (r"\bBASH_ENV\s*=", "BASH_ENV trap injection"),
    (r"\bSHELLOPTS\s*=", "SHELLOPTS injection"),
    (r"\bBASH_FUNC_\w+%+", "BASH_FUNC injection"),
    (r"\bGEM_PATH\s*=", "GEM_PATH injection"),
    (r"\bGIT_EXEC_PATH\s*=", "GIT_EXEC_PATH injection"),
    (r"\bGIT_SSH_COMMAND\s*=", "GIT_SSH injection"),
    (r"\bENV\s*=", "ENV injection"),
    (r"\bIFS\s*=\s*", "IFS injection (word-splitting attack)"),
    (r"\bPATH\s*=\s*[^$]", "PATH variable override"),
    # ═══════════════════════════════════════════════════════
    # 8. GTFOBins 工具滥用 — 内联解释器 / 工具逃逸
    # ═══════════════════════════════════════════════════════
    (
        r"\bpython\d*\s+-c\s.*\bimport\s+socket\b",
        "socket python reverse shell",
    ),
    (r"\bpython\d*\s+-c\s", "python -c inline execution"),
    (r"\bpython\d*\s+-m\s+timeit\b", "python timeit execution"),
    (r"\bperl\s+-[eE]\s", "perl -e inline execution"),
    (r"\bruby\s+-e\s", "ruby -e inline execution"),
    (r"\blua\s+-e\s", "lua inline execution"),
    (r"\bnode\s+-[ep]\s", "node -e inline execution"),
    (r"\bphp\s+-[rR]\s", "php -r inline execution"),
    (r"\bexpect\s+-c\s", "expect inline execution"),
    (r"\bawk\b.*\bsystem\s*\(", "awk system() call"),
    (r"\btar\b.*--checkpoint-action\s*=\s*exec", "tar checkpoint execution"),
    (r"echo\s+.*\*.*\|\s*xargs\b", "xargs wildcard execution"),
    (r"\bxargs\b.*\b(?:sh|bash)\b\s+-c\b", "xargs exfil with shell"),
    (r"\bxargs\b", "xargs execution"),
    (r"\bvim?\b\s+-c\s+['\"]?\s*:", "vim escape execution"),
    (r"\bless\b.*\s+-c\s+['\"]\s*!", "less escape execution"),
    (r"\bman\b.*\s+-P\s+['\"]\s*!", "man escape execution"),
    (r"\bgit\b.*\bcore\.pager\s*=\s*['\"]", "git escape execution"),
    (r"\bssh\b.*ProxyCommand\s*=\s*['\"]", "ssh ProxyCommand injection"),
    (r"\bssh\b.*PermitLocalCommand\s*=\s*yes", "ssh LocalCommand injection"),
    (r"\bssh\b.*LocalCommand\s*=\s*['\"]", "ssh LocalCommand injection"),
    (r"\bmake\b.*\s+-f\s+/tmp/", "make -f execution"),
    (r"\bscreen\b.*\s+-X\s+(?:exec|stuff)\b", "screen exec escape"),
    (r"\btmux\b.*\bnew-session\b.*\b(?:rm|sh|bash|nc)\b", "tmux escape"),
    (r"\bstrace\b.*\s+-c\s", "strace execution"),
    (r"\bbusctl\b", "busctl execution"),
    # ═══════════════════════════════════════════════════════
    # 9. 反向 Shell
    # ═══════════════════════════════════════════════════════
    (r"\b(?:nc|ncat|netcat)\b.*\s+-[ce]\s", "nc reverse shell"),
    (r"\bsocat\b.*\b(?:EXEC|exec|SYSTEM|system)\b", "socat reverse shell"),
    (r"\btelnet\b.*\|\s*/(?:bin/|usr/bin/)?(?:ba)?sh\b", "telnet reverse shell"),
    (r"\bmkfifo\b.*\btelnet\b", "telnet reverse shell"),
    (r"\btelnet\b.*\bmkfifo\b", "telnet reverse shell"),
    (r"\bopenssl\b\s+s_client\b.*\|", "openssl reverse shell"),
    (r">&?\s*/dev/tcp/", "TCP reverse shell via /dev/tcp"),
    (r">&?\s*/dev/udp/", "UDP exfiltration via /dev/udp"),
    # ═══════════════════════════════════════════════════════
    # 10. 间接执行链
    # ═══════════════════════════════════════════════════════
    (r"\bnice\b\s+.*\b(?:ba)?sh\b\s+-c\b", "nice wrapper execution"),
    (r"\bnohup\b\s+.*\b(?:ba)?sh\b\s+-c\b", "nohup wrapper execution"),
    (r"\bstdbuf\b\s+.*\b(?:ba)?sh\b\s+-c\b", "stdbuf wrapper execution"),
    (r"\btimeout\b\s+.*\b(?:ba)?sh\b\s+-c\b", "timeout wrapper execution"),
    (r"\btaskset\b\s+.*\b(?:ba)?sh\b\s+-c\b", "taskset wrapper execution"),
    (r"\bchrt\b\s+.*\b(?:ba)?sh\b\s+-c\b", "chrt wrapper execution"),
    (r"\bionice\b\s+.*\b(?:ba)?sh\b\s+-c\b", "ionice wrapper execution"),
    (r"\bsetarch\b\s+.*\b(?:ba)?sh\b\s+-c\b", "setarch wrapper execution"),
    (r"\bprlimit\b\s+.*\b(?:ba)?sh\b\s+-c\b", "prlimit wrapper execution"),
    (r"\benv\b\s+.*\b(?:ba)?sh\b\s+-c\b", "env wrapper execution"),
    (r"\bwatch\b\s+.*\b(?:rm|sh|bash|nc|curl)\b", "watch wrapper execution"),
    # ═══════════════════════════════════════════════════════
    # 11. 数据外泄（不含 $() 的部分）
    # ═══════════════════════════════════════════════════════
    (r"\bcurl\b.*-d\s*@[-/]", "http exfil via curl"),
    (r"\bwget\b.*--post-file\s*=\s*(?:/etc/|/tmp/)", "http exfil via wget"),
    (r"\bssh\b\s+\S+\s+.*<\s*/etc/", "ssh exfil via ssh redirect"),
    (r"\bnc\b\s+\S+\s+\d+\s*<\s*/etc/", "nc exfil via nc redirect"),
    (r"\bopenssl\b\s+enc\b.*\|\s*\bcurl\b", "encrypted exfil via openssl-curl"),
    # ═══════════════════════════════════════════════════════
    # 12. 权限提升
    # ═══════════════════════════════════════════════════════
    (r"\bpkexec\b", "pkexec privilege escalation"),
    (r"\bsudoedit\b", "sudoedit privilege escalation"),
    (r"\bsudo\b", "sudo privilege escalation"),
    (r"\bsu\b", "su user switch"),
    # ═══════════════════════════════════════════════════════
    # 13. 沙箱逃逸
    # ═══════════════════════════════════════════════════════
    (r"\bdocker\b\s+run\b.*-v\s+/:", "docker escape via host mount"),
    (r"\bdocker\b\s+run\b.*--privileged", "docker privileged escape"),
    (r"\bdocker\b\s+run\b.*--cap-add\s*=\s*SYS_ADMIN", "docker cap-add escape"),
    (r"\bnsenter\b", "nsenter namespace escape"),
    (r"\bunshare\b", "unshare namespace escape"),
    (r"\bchroot\b", "chroot escape"),
    (r"\bmount\b.*-t\s+cgroup\b", "cgroup mount escape"),
    (r"\bmount\b.*-o\s+remount.*\s+/", "mount remount root"),
    (r"\bmount\b.*--bind\s+/", "mount bind root"),
    # ═══════════════════════════════════════════════════════
    # 14. 多态编码链
    # ═══════════════════════════════════════════════════════
    (r"\brev\b\s*\|\s*\bbase64\b", "rev base64 chain"),
    (r"\brev\b\s*\|", "rev base64 chain"),
    (r"\brev\b.*\bbase64\b", "rev base64 chain"),
    (r"\bbase64\b.*\s+-d\s+.*\|\s*\bbase64\b", "nested base64 decoding"),
    (r"\bxxd\b.*\s+-r\s+-p\s+.*\|\s*\bbase64\b", "hex to base64 chain"),
    (r"\bbase64\b.*\s+-d\s+.*\|\s*\bgunzip\b", "gzip nested decoding"),
    (r"\bopenssl\b\s+enc\b.*\s+-d\s+.*\|", "openssl decrypt pipe"),
    (r"\bxxd\b\s+-r\s+-p\s+.*\|", "xxd hex decode pipe"),
    (r"\bbase64\b\s+-d\s+.*\|", "base64 decode pipe"),
    (r"\biconv\b\s+.*\|", "iconv encoding chain"),
    # ═══════════════════════════════════════════════════════
    # 15. 通配符注入
    # ═══════════════════════════════════════════════════════
    (r"--checkpoint-action\s*=\s*exec", "tar wildcard injection"),
    (r"touch\s+--\s+['\"]\s*-e\s+sh\b", "rsync wildcard injection"),
    (r"scp\s+.*\*\s+.*@", "scp wildcard injection"),
    (r"touch\s+/tmp/\{1\.\.\d+\}\.txt", "brace expansion DoS"),
    # ═══════════════════════════════════════════════════════
    # 16. 拒绝服务（进程层面）
    # ═══════════════════════════════════════════════════════
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\};", "fork bomb"),
    (r"\.\(\)\s*\{\s*\.\s*\|\s*\.\s*&\s*\};", "fork bomb"),
    (r"fork\s*\(\s*\)\s*\{\s*fork\s*\|\s*fork\s*&\s*\};", "fork bomb"),
    (r"\(\)\s*\{[^}]*:[^}]*\}[^)]*\|[^)]*:&[^)]*\)\s*;", "fork bomb"),
    (r"\byes\b\s*>", "yes bomb resource exhaustion"),
    (r"\bulimit\b\s+-[nu]\s+[01]\b", "ulimit restriction DoS"),
    # ═══════════════════════════════════════════════════════
    # 17. 内核 / 模块操纵
    # ═══════════════════════════════════════════════════════
    (r"\bmodprobe\b", "modprobe kernel manipulation"),
    (r"\binsmod\b", "insmod kernel manipulation"),
    (r"\brmmod\b", "rmmod kernel manipulation"),
    (r"\bsysctl\b\s+-w\b", "sysctl write kernel manipulation"),
    (r"\bkexec\b", "kexec kernel manipulation"),
    (r"\bdmesg\b\s+-n\b", "dmesg kernel manipulation"),
    # ═══════════════════════════════════════════════════════
    # 18. 防火墙 / 安全策略篡改
    # ═══════════════════════════════════════════════════════
    (
        r"\biptables\b\s+-P\s+(?:INPUT|OUTPUT|FORWARD)\s+ACCEPT",
        "iptables policy manipulation",
    ),
    (r"\biptables\b\s+-[FP]", "iptables flush/policy manipulation"),
    (r"\bip6tables\b\s+-[FP]", "iptables flush/policy manipulation"),
    (r"\bufw\b\s+disable\b", "ufw disable"),
    (r"\bsetenforce\b", "selinux manipulation"),
    (r"\bsetcap\b", "setcap manipulation"),
    # ═══════════════════════════════════════════════════════
    # 19. 网络下载 + 管道执行
    # ═══════════════════════════════════════════════════════
    (r"\blynx\b\s+-source\b.*\|\s*(?:ba)?sh\b", "lynx download pipe"),
    (r"\bcurl\b.*\b((ba)?sh|python|perl|ruby)\b", "curl pipe to interpreter"),
    (r"\bwget\b.*\b((ba)?sh|python|perl|ruby)\b", "wget pipe to interpreter"),
    # ═══════════════════════════════════════════════════════
    # 20. rm -rf 变体（强力信号，即使 sysguard 也能拦，提前拦截避免 fork）
    # ═══════════════════════════════════════════════════════
    (r"rm\s+-r\s+-f\s+/", "rm -rf / with separate flags"),
    (
        r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+--no-preserve-root",
        "rm -rf shell command",
    ),
    (
        r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+/(\*|\s|$)",
        "rm -rf / or rm -rf /*",
    ),
    (
        r"rm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\s+/(\*|\s|$)",
        "rm -fr / or rm -fr /*",
    ),
    (r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+~/", "rm -rf ~/"),
    (
        r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+\$HOME",
        "rm -rf with env var expansion",
    ),
    (r"\bmkfs\b", "mkfs filesystem format"),
    (r"\bmkswap\b", "mkfs filesystem format"),
    # ═══════════════════════════════════════════════════════
    # 21. 系统停机
    # ═══════════════════════════════════════════════════════
    (r"\bshutdown\b", "shutdown system"),
    (r"\breboot\b", "reboot system"),
    (r"\bpoweroff\b", "poweroff system"),
    (r"\bhalt\b", "halt system"),
    (r"\binit\b\s+\d", "init runlevel change"),
    (r"\btelinit\b", "telinit runlevel change"),
    # ═══════════════════════════════════════════════════════
    # 22. 进程屠杀
    # ═══════════════════════════════════════════════════════
    (r"\bkillall5\b", "killall5 process kill"),
    (r"\bkill\b\s+-\d+\s+-1\b", "kill all processes"),
    (r"\bkill\b\s+-\d+\s+1\b", "kill init process"),
    (r"\bpkill\b", "pkill by name"),
    (r"\bkillall\b", "killall by name"),
]


def check_command_safety(command: str) -> None:
    """检查命令是否包含危险操作。"""
    _check_unicode_safety(command)

    for pattern, description in _DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            raise ValueError(
                f"Dangerous command blocked ({description}): "
                f"matched pattern '{pattern}'"
            )
