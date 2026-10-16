set -eu
git clone -q /repo /tmp/baseline-question
chown -R parity:parity /tmp/baseline-question
su parity -s /bin/sh -c 'cd /tmp/baseline-question; timeout 90 python -m pytest -vv tests/test_agent_questions.py -o faulthandler_timeout=30'
