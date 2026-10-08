#!/usr/bin/env python3
"""Validate moderator observations; this cannot substitute for real people."""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

FIELDS = ['participant_id', 'task_id', 'human_observed', 'credential_ready',
          'onboarding_seconds', 'completed_without_help', 'ordinary_modals_after_trust', 'evidence']


def evaluate(rows, base):
    participants = sorted({r['participant_id'] for r in rows})
    if len(participants) != 5 or len(rows) != 15:
        return {'status': 'BLOCKED', 'reason': 'Needs five real participants and three observations each.'}
    times, completion, modals = [], {str(t): 0 for t in range(1, 4)}, 0
    for person in participants:
        records = [r for r in rows if r['participant_id'] == person]
        if len(records) != 3 or {r['task_id'] for r in records} != {'1', '2', '3'}:
            raise ValueError('Each participant needs exactly tasks 1, 2 and 3')
        if any(not all(r.get(k) for k in FIELDS) for r in records):
            return {'status': 'BLOCKED', 'reason': 'Observations are incomplete; no participants simulated.'}
        if any(r['human_observed'] != 'yes' or r['credential_ready'] != 'yes' for r in records):
            return {'status': 'BLOCKED', 'reason': 'Requires observed real humans with credentials already available.'}
        values = [float(r['onboarding_seconds']) for r in records]
        if any(not math.isfinite(t) or t < 0 for t in values) or len(set(values)) != 1:
            raise ValueError('Onboarding must be finite, nonnegative and consistent per participant')
        times.append(values[0])
        for r in records:
            if r['completed_without_help'] not in {'yes', 'no'}:
                raise ValueError('Completion must be yes/no')
            count = int(r['ordinary_modals_after_trust'])
            if count < 0:
                raise ValueError('Modal count must be nonnegative')
            modals += count
            completion[r['task_id']] += r['completed_without_help'] == 'yes'
            path = Path(r['evidence'])
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Evidence must be a local relative file')
            target = base
            for part in path.parts:
                target /= part
                if target.is_symlink():
                    raise ValueError('Evidence cannot follow symlinks')
            if not (base / path).is_file():
                return {'status': 'BLOCKED', 'reason': 'Raw observation evidence missing.'}
    checks = {'each_task_four_of_five': all(n >= 4 for n in completion.values()),
              'median_onboarding_two_minutes': statistics.median(times) <= 120,
              'zero_ordinary_modals_after_trust': modals == 0}
    return {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
            'completed_per_task': completion, 'median_onboarding_seconds': statistics.median(times),
            'ordinary_modals': modals,
            'scope': 'Moderator-attested real-human observations; validator cannot establish identity or replace observation.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    args = parser.parse_args()
    path = Path(args.csv).resolve()
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Unexpected CSV schema')
        report = evaluate(list(reader), path.parent)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
