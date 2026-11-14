# -*- coding: utf-8 -*-
"""公开产物脱敏扫描。

工具本身不含任何项目专属的敏感词，可直接随仓库发布。需要额外检查的词
（例如部署者自己的用户名、内部系统名）由使用者通过环境变量提供：

===============================  ==========================================
环境变量                         含义
===============================  ==========================================
``DESENSITIZE_TERMS``            逗号分隔的补充词表
``DESENSITIZE_TERMS_FILE``       每行一个词的补充词表文件
``VERIFY_RESULTS_DIR``           报告输出目录（见 _common）
===============================  ==========================================

用法::

    python scripts/verify/desensitize_scan.py worktree
        # 工作区 diff 的新增行 + 全部未跟踪文件（提交前）
    python scripts/verify/desensitize_scan.py commits <base> <head>
        # 一批提交的 message + 相对 base 的新增行（发布前复核）
    python scripts/verify/desensitize_scan.py tree
        # 当前已跟踪文件的完整快照（CI 定期体检）
    python scripts/verify/desensitize_scan.py selftest
        # 阳性对照：确认规则确实能命中，而不是正则写错导致假 PASS

命中「严格项」即 FAIL，需人工判读；「提示项」仅列出供复核。
"""
import os
import pathlib
import re
import subprocess
import sys

from _common import ROOT, RESULTS_DIR

# (级别, 名称, 正则, 适用模式)；strict=FAIL，notice=仅提示，modes=None 表示全部
# 「内部清单引用」只在 diff 类模式下检查：全树快照里 .gitignore 的忽略项与
# 测试函数名中的 verify 都是合法内容，不该被当成内部材料引用。
PATTERNS = [
    ('strict', '本机绝对路径',
     re.compile(r'(?i)[a-z]:[\\/]+users[\\/]+[^\\\/\s"\'<>,;)]+'), None),
    ('strict', 'Git Bash 家目录路径', re.compile(r'(?i)/[a-z]/users/'), None),
    ('strict', '非回环内网地址',
     re.compile(r'(?i)\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
                r'|192\.168\.\d{1,3}\.\d{1,3}'
                r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})'), None),
    ('strict', '内部清单/验证脚本引用',
     re.compile(r'(?i)\.workbuddy|_verify[/\\]|待改进清单|清单\s*P\d|详见清单|见清单|'
                r'P3-1|P2-\d+|P1-\d+|P0-\d+'),
     ('worktree', 'commits', 'selftest')),
    ('strict', '内部评审措辞',
     re.compile(r'后门|移除了.{0,12}漏洞|修复了.{0,12}漏洞|安全漏洞'), None),
    ('strict', '手机号', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'), None),
    ('strict', '身份证号', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)'), None),
    ('notice', '凭据赋值',
     re.compile(r'(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*["\'][^"\']{3,}["\']'), None),
    ('notice', '邮箱地址', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), None),
]

# 本地回环地址与公开仓库信息属于正常内容，不算脱敏项
ALLOW = re.compile(
    r'(?i)github\.com/Durian2005|332970281\+Durian2005@users\.noreply\.github\.com'
    r'|admin123|admin/admin123|127\.0\.0\.1:\d+|localhost:\d+'
)

MAX_SHOWN_PER_PATTERN = 5


def extra_terms():
    """从环境变量/词表文件读取项目专属补充词，合成一条 strict 规则。"""
    words = []
    inline = os.environ.get('DESENSITIZE_TERMS', '')
    words += [w.strip() for w in inline.split(',') if w.strip()]
    path = os.environ.get('DESENSITIZE_TERMS_FILE', '')
    if path:
        try:
            text = pathlib.Path(path).read_text(encoding='utf-8')
            words += [w.strip() for w in text.splitlines()
                      if w.strip() and not w.strip().startswith('#')]
        except OSError as exc:
            print('补充词表读取失败：%s' % exc, file=sys.stderr)
            sys.exit(2)
    if not words:
        return None
    body = '|'.join(re.escape(w) for w in words)
    return ('strict', '补充词表', re.compile(body, re.IGNORECASE))


def git(*args):
    return subprocess.run(
        ['git', *args], cwd=str(ROOT), capture_output=True,
        encoding='utf-8', errors='replace',
    ).stdout


def added_lines(diff_text):
    """返回 [(文件, 行号, 内容)]，只取新增行。"""
    out = []
    current = '(unknown)'
    lineno = 0
    for line in diff_text.splitlines():
        if line.startswith('+++ '):
            path = line[4:].strip()
            if path.startswith('b/'):
                path = path[2:]
            current = path
        elif line.startswith('@@'):
            m = re.search(r'\+(\d+)', line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith('+') and not line.startswith('+++'):
            out.append((current, lineno, line[1:]))
            lineno += 1
        elif line.startswith('-') and not line.startswith('---'):
            pass
        else:
            lineno += 1
    return out


def read_entries_from_files(paths):
    out = []
    for rel in paths:
        fp = ROOT / rel
        try:
            if fp.stat().st_size > 4 * 1024 * 1024:
                continue
            text = fp.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            out.append((rel, i, line))
    return out


def scan(entries, patterns):
    hits = []
    for name, level, pattern in patterns:
        start = len(hits)
        shown = 0
        total = 0
        for path, lineno, text in entries:
            # 本文件是规则载体：正则定义与阳性样本本身就是敏感词字典，
            # 逐行扫自己必然自命中。显式排除，只检查其余公开产物。
            if path.endswith('desensitize_scan.py'):
                continue
            for m in pattern.finditer(text):
                frag = m.group(0)
                if ALLOW.search(frag):
                    continue
                total += 1
                if shown < MAX_SHOWN_PER_PATTERN:
                    shown += 1
                    lo = max(0, m.start() - 55)
                    hi = min(len(text), m.end() + 55)
                    context = text[lo:hi].replace('\r', ' ').replace('\n', ' ')
                    if len(context) > 180:
                        context = context[:180] + '...'
                    hits.append('  [%s/%s] %s:%d  <%s>  ...%s...'
                                % (level, name, path, lineno, frag[:70], context))
        if total:
            hits.insert(start, '  %-8s %-22s 命中 %d 处（最多展示 %d）'
                        % (level.upper(), name, total, shown))
    return hits


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    entries = []
    extra = []

    if mode == 'worktree':
        entries += added_lines(git('diff', '--no-color', '--unified=0'))
        staged = git('diff', '--cached', '--no-color', '--unified=0')
        entries += [('[已暂存] ' + p, n, t) for p, n, t in added_lines(staged)]
        untracked = [p for p in git('ls-files', '--others', '--exclude-standard').splitlines() if p]
        extra.append('未跟踪文件：%d 个 -> %s' % (len(untracked), ', '.join(untracked)))
        entries += read_entries_from_files(untracked)
    elif mode == 'commits' and len(sys.argv) >= 4:
        base, head = sys.argv[2], sys.argv[3]
        entries += added_lines(git('diff', '--no-color', '--unified=0', base, head))
        messages = git('log', '--format=%B%x00', '%s..%s' % (base, head))
        for i, block in enumerate(messages.split('\0')):
            for j, line in enumerate(block.splitlines(), 1):
                if line.strip():
                    entries.append(('<commit-message #%d>' % (i + 1), j, line))
        names = git('diff', '--name-only', base, head).splitlines()
        extra.append('提交涉及文件：%d 个' % len(names))
        bad = [p for p in names if p.startswith('.workbuddy/') or '_verify' in p]
        extra.append('内部文件混入检查：%s' % ('FAIL -> ' + ', '.join(bad) if bad else 'PASS'))
        if bad:
            entries.append(('<guard>', 0, 'FAIL 内部文件混入: ' + ', '.join(bad)))
        extra.append('提交列表：')
        for line in git('log', '--oneline', '%s..%s' % (base, head)).splitlines():
            extra.append('  ' + line)
    elif mode == 'tree':
        paths = [p for p in git('ls-files').splitlines() if p]
        entries += read_entries_from_files(paths)
        extra.append('已跟踪文件：%d 个' % len(paths))
    elif mode == 'selftest':
        # 阳性对照：确认扫描器确实抓得住敏感信息，而不是正则写错导致假 PASS
        samples = [
            r'C:\Users\example\project\README.md',
            '/c/Users/example/secret.py',
            '详见清单 P3-1 第二步',
            '本次移除了后门与若干安全漏洞',
            '联系人 13812345678',
            '内网地址 10.20.0.1',
            '证件号 110101199001011234',
            '公开链接 https://github.com/Durian2005/CardioCrypt 应放行',
        ]
        for i, s in enumerate(samples, 1):
            entries.append(('<selftest>', i, s))
    else:
        sys.exit('用法: desensitize_scan.py worktree | commits <base> <head> | tree | selftest')

    patterns = [(n, l, p) for l, n, p, modes in PATTERNS
                if modes is None or mode in modes]
    term_rule = extra_terms()
    if term_rule:
        patterns.append((term_rule[1], term_rule[0], term_rule[2]))
        extra.append('补充词表：已启用')

    hits = scan(entries, patterns)
    strict = [h for h in hits if h.startswith('  [strict/')]
    notice = [h for h in hits if h.startswith('  [notice/')]
    verdict = 'FAIL' if strict else 'PASS'
    if mode == 'selftest':
        verdict = 'PASS' if len(strict) >= 7 else 'FAIL'
        extra.append('阳性对照：严格项命中 %d 处，期望 >= 7（前 7 条样本）' % len(strict))

    lines = ['=== 脱敏扫描 [%s] ===' % mode, '扫描行数：%d' % len(entries), '结论：%s' % verdict]
    lines += extra
    lines.append('严格项命中：%d 处 | 提示项命中：%d 处' % (len(strict), len(notice)))
    lines.append('--- 明细 ---')
    lines += hits if hits else ['  （无命中）']
    report = '\n'.join(lines) + '\n'

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / ('desensitize_scan_%s.txt' % mode)
    with open(str(out), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(report)
    print(report)
    print('报告：%s' % out)
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
