"""Recursive grep/rg argv -> ziggrep argv, before the command preview.

Part of the RTK opt-in (`/rtk`): a recursive search is shown to the person as
`ziggrep ...` and, once approved, runs exactly like that; its output then goes
through RTK's grep filter (rtk_integration.plan). ziggrep is grep/rg
compatible, respects .gitignore and is much faster on large trees.

Data only: this never executes anything and never widens a request. Any flag
outside the allow-lists, a non-recursive grep, stdin search or a dash-led path
leaves the argv untouched. Same rules as ISyCo tools/ziggrep_rtk (shell hooks
of the other TUIs). Off for one run: ZIGGREP_RTK=0.
"""
from __future__ import annotations

import os
from pathlib import Path

RECURSIVE = frozenset({'-r', '-R', '--recursive', '--dereference-recursive'})
_GREP_NOARG = frozenset('rRniwlLcFEGvHhsoxqaI')
_GREP_ARG = frozenset('eABCm')
_GREP_LONG_NOARG = frozenset({
    '--recursive', '--dereference-recursive', '--line-number', '--ignore-case',
    '--word-regexp', '--files-with-matches', '--files-without-match', '--count',
    '--fixed-strings', '--extended-regexp', '--basic-regexp', '--invert-match',
    '--no-messages', '--only-matching', '--line-regexp', '--quiet', '--silent',
    '--with-filename', '--no-filename', '--text',
})
_GREP_LONG_ARG = frozenset({'--include', '--exclude', '--exclude-dir', '--context',
                            '--after-context', '--before-context', '--max-count', '--regexp'})
# rg -s/-L/-N/-u mean something else in ziggrep: refused, not mapped.
_RG_NOARG = frozenset('niwlcFvxoSHUq')
_RG_ARG = frozenset('eABCmtTg')
_RG_LONG_NOARG = frozenset({
    '--line-number', '--ignore-case', '--word-regexp', '--files-with-matches',
    '--files-without-match', '--count', '--fixed-strings', '--invert-match',
    '--only-matching', '--line-regexp', '--smart-case', '--with-filename',
    '--no-filename', '--multiline', '--hidden', '--no-ignore', '--quiet',
    '--count-matches', '--no-heading',
})
_RG_LONG_ARG = frozenset({'--glob', '--iglob', '--type', '--type-not', '--context',
                          '--after-context', '--before-context', '--max-count',
                          '--max-depth', '--regexp'})
_DROP = frozenset({'-I', '--binary-files=without-match', '--no-heading',
                   '--color=never', '--colour=never', '--color=auto', '--colour=auto'})
_QUIET = frozenset({'-l', '-L', '-c', '-q', '-o', '--files-with-matches', '--files-without-match',
                    '--count', '--count-matches', '--quiet', '--silent', '--only-matching'})


def _parse(args, noarg, witharg, long_noarg, long_arg):
    flags, pos, ended, i = [], [], False, 0
    while i < len(args):
        token = args[i]
        if ended or not token.startswith('-') or token == '-':
            pos.append(token)
        elif token == '--':
            ended = True
        elif token in _DROP:
            pass
        elif token.startswith('--'):
            name, eq, value = token.partition('=')
            if name in long_noarg and not eq:
                flags.append((name, None))
            elif name in long_arg:
                if not eq:
                    i += 1
                    if i >= len(args):
                        return None
                    value = args[i]
                flags.append((name, value))
            else:
                return None
        else:
            body = token[1:]
            for k, char in enumerate(body):
                if char in witharg:
                    value = body[k + 1:]
                    if not value:
                        i += 1
                        if i >= len(args):
                            return None
                        value = args[i]
                    flags.append(('-' + char, value))
                    break
                if char not in noarg:
                    return None
                flags.append(('-' + char, None))
        i += 1
    return flags, pos


def _build(flags, pos, front):
    names = {name for name, _ in flags}
    if '-e' in names or '--regexp' in names:
        pattern, paths = None, pos
    elif pos:
        pattern, paths = pos[0], pos[1:]
    else:
        return None
    if any(path == '-' or path.startswith('-') for path in paths):
        return None
    out = ['ziggrep', *front]
    if not names & (_QUIET | {'-n', '--line-number'}):
        out.append('-n')
    for name, value in flags:
        if name in RECURSIVE or name == '-I':
            continue  # ziggrep always recurses and already skips binary files
        if name == '--regexp':
            name = '-e'
        if value is None:
            out.append(name)
        elif name.startswith('--'):
            out.append(f'{name}={value}')
        else:
            out += [name, value]
    if pattern is not None:
        out += ['-e', pattern] if pattern.startswith('-') else [pattern]
    # Without a path ziggrep reads stdin (like grep), not the directory.
    return tuple(out + (paths or ['.']))


def rewrite(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """The ziggrep argv for a recursive grep/rg, or None to keep `argv` as is."""
    if os.environ.get('ZIGGREP_RTK') == '0' or not argv:
        return None
    name, args = Path(argv[0]).name, list(argv[1:])
    if argv[0] != name:
        return None  # explicit paths (./grep, /opt/x/grep) are someone's own program
    if name == 'grep':
        parsed = _parse(args, _GREP_NOARG, _GREP_ARG, _GREP_LONG_NOARG, _GREP_LONG_ARG)
        if parsed is None or not {n for n, _ in parsed[0]} & RECURSIVE:
            return None
        names = {n for n, _ in parsed[0]}
        dialect = {'-E', '-F', '-G', '--extended-regexp', '--fixed-strings', '--basic-regexp'}
        return _build(*parsed, [] if names & dialect else ['-G'])  # grep default is BRE
    if name == 'rg':
        parsed = _parse(args, _RG_NOARG, _RG_ARG, _RG_LONG_NOARG, _RG_LONG_ARG)
        if parsed is None:
            return None
        flags, hidden = [], False
        for flag, value in parsed[0]:
            if flag in {'-g', '--glob', '--iglob'}:
                flags.append(('--exclude', value[1:]) if value.startswith('!') else ('--include', value))
            elif flag == '--hidden':
                hidden = True
            elif flag == '--type':
                flags.append(('-t', value))
            elif flag == '--regexp':
                flags.append(('-e', value))
            else:
                flags.append((flag, value))
        return _build(flags, parsed[1], [] if hidden else ['--no-hidden'])
    return None
