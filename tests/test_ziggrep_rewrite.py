"""Recursive grep/rg become ziggrep in the preview, only under the RTK opt-in."""
import os
import posixpath
import types

import pytest

from isycode.ziggrep_rewrite import rewrite

REWRITES = {
    ('grep', '-rn', 'foo', '.'): ('ziggrep', '-G', '-n', 'foo', '.'),
    ('grep', '-r', 'foo'): ('ziggrep', '-G', '-n', 'foo', '.'),
    ('grep', '-rniE', 'a|b', 'src', 'lib'): ('ziggrep', '-n', '-i', '-E', 'a|b', 'src', 'lib'),
    ('grep', '-rl', 'TODO', '.'): ('ziggrep', '-G', '-l', 'TODO', '.'),
    ('grep', '-rn', '--include=*.py', 'foo', '.'): ('ziggrep', '-G', '-n', '--include=*.py', 'foo', '.'),
    ('grep', '-rnA', '2', 'foo', '.'): ('ziggrep', '-G', '-n', '-A', '2', 'foo', '.'),
    ('grep', '-rn', '--regexp', '-x', '.'): ('ziggrep', '-G', '-n', '-e', '-x', '.'),
    ('grep', '-rI', 'foo', '.'): ('ziggrep', '-G', '-n', 'foo', '.'),
    ('rg', 'foo'): ('ziggrep', '--no-hidden', '-n', 'foo', '.'),
    ('rg', '-g', '!*.lock', '-g', '*.ts', 'foo'):
        ('ziggrep', '--no-hidden', '-n', '--exclude=*.lock', '--include=*.ts', 'foo', '.'),
    ('rg', '--hidden', '-i', 'foo', '.'): ('ziggrep', '-n', '-i', 'foo', '.'),
    ('rg', '-tpy', '-l', 'foo'): ('ziggrep', '--no-hidden', '-t', 'py', '-l', 'foo', '.'),
}

UNTOUCHED = [
    ('grep', '-n', 'foo', 'file.txt'),        # not recursive
    ('grep', '-rnP', 'a(?=b)', '.'),          # PCRE
    ('grep', '-rn', 'foo', '-'),              # stdin
    ('grep', '-rn', 'foo', '--', '-dir'),     # dash-led path
    ('./grep', '-rn', 'foo', '.'),            # someone's own program
    ('/opt/x/grep', '-rn', 'foo', '.'),
    ('rg', '-s', 'foo'),                      # rg -s != ziggrep -s
    ('rg', '-L', 'foo'),
    ('rg', '-u', 'foo'),
    ('git', 'grep', 'foo'),
    ('ziggrep', '-n', 'foo', '.'),
]


@pytest.mark.parametrize('argv,want', REWRITES.items())
def test_rewrites(argv, want):
    assert rewrite(argv) == want


@pytest.mark.parametrize('argv', UNTOUCHED)
def test_untouched(argv):
    assert rewrite(argv) is None


def test_env_off(monkeypatch):
    monkeypatch.setenv('ZIGGREP_RTK', '0')
    assert rewrite(('grep', '-rn', 'foo', '.')) is None


def test_preview_keeps_grep_without_rtk_opt_in(tmp_path, monkeypatch):
    from isycode import command_runner
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    argv = ('grep', '-rn', 'foo', '.')
    assert command_runner._ziggrep(argv, '/usr/bin/grep', lambda n: f'/usr/local/bin/{n}') == (argv, '/usr/bin/grep')


def test_preview_shows_ziggrep_with_opt_in(tmp_path, monkeypatch):
    from isycode import command_runner, rtk_integration
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setattr(rtk_integration.Settings, 'load', lambda self: {'enabled': True})
    argv = ('grep', '-rn', 'foo', '.')
    new, program = command_runner._ziggrep(argv, '/usr/bin/grep', lambda n: f'/usr/local/bin/{n}')
    assert new == ('ziggrep', '-G', '-n', 'foo', '.')
    assert program == '/usr/local/bin/ziggrep'


def test_preview_keeps_grep_when_ziggrep_cannot_run_there(tmp_path, monkeypatch):
    from isycode import command_runner, rtk_integration
    monkeypatch.setattr(rtk_integration.Settings, 'load', lambda self: {'enabled': True})

    def missing(name):
        raise ValueError(f'program {name!r} is not installed')
    argv = ('rg', 'foo')
    assert command_runner._ziggrep(argv, '/usr/bin/rg', missing) == (argv, '/usr/bin/rg')


def test_plan_routes_ziggrep_output_to_rtk_grep_filter(tmp_path, monkeypatch):
    from isycode import rtk_integration as rtk
    identity = {'enabled': True, 'path': '/usr/local/bin/rtk', 'sha256': 'a' * 64, 'version': 'rtk 0.51.0'}
    # Do not mutate the process-wide os module: pathlib depends on os.name.
    # The plan path is POSIX-only, so its path module must be posixpath; on
    # Windows ntpath.normpath would rewrite the POSIX identity to backslashes
    # and reject a valid identity.
    monkeypatch.setattr(rtk, 'os', types.SimpleNamespace(name='posix', path=posixpath))
    monkeypatch.setattr(rtk.Settings, 'load', lambda self: identity)
    monkeypatch.setattr(rtk, '_binary', lambda identity: b'')
    monkeypatch.setattr(rtk, '_cli', lambda *a: pytest.fail('ziggrep needs no rtk rewrite call'))
    value = rtk.plan(('ziggrep', '-G', '-n', 'foo', '.'), '/home/u/.local/bin/ziggrep')
    assert value['rewrite_argv'] == ('rtk', 'grep', '-G', '-n', 'foo', '.')
    assert value['decision'] == 'ask'
    assert rtk._filter_args(value) == ('pipe', '--filter', 'grep')
    # a pattern that looks like a shell operator is never smuggled into a plan
    assert rtk.plan(('ziggrep', '-n', '|', '.'), '/home/u/.local/bin/ziggrep') is None
