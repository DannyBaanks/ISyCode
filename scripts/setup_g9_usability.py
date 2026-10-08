#!/usr/bin/env python3
"""Create a fresh, independent fixture for one human participant."""
import argparse
from pathlib import Path


def create_fixture(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    files = {
        'calc.py': 'def add(a, b):\n    return a - b\n',
        'test_calc.py': 'import unittest\nfrom calc import add\n\nclass TestAdd(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, 3), 1)\n        self.assertEqual(add(0, 0), 0)\n',
        'notes.txt': 'PROJECT_CODE=ALPHA_42\nThe release note is in docs/release.txt\n',
        'docs/release.txt': 'Release: CANARY_RELEASE_7\nStatus: review\n',
        'review.txt': 'status=original\n',
    }
    for name, content in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('out')
    print(create_fixture(parser.parse_args().out))
