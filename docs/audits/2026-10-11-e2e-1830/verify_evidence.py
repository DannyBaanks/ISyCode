"""Check the captured audit witnesses; does not run or alter product code."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent

def state(name):
    return json.loads((OUT/(name+'.json')).read_text())

def widget(data, identifier):
    return next(w for w in data['widgets'] if w['id'] == identifier)

checks = {}
suite = ET.parse(OUT/'suite.xml').getroot().find('testsuite')
checks['suite_exit_zero'] = json.loads((OUT/'suite-result.json').read_text())['exit_code'] == 0
checks['suite_no_failures_or_errors'] = suite.attrib['failures'] == '0' and suite.attrib['errors'] == '0'
checks['real_sandbox_exit_zero'] = json.loads((OUT/'real-sandbox-result.json').read_text())['exit_code'] == 0

blocked = state('24-security-blocked-chat')
inverse = state('26-chat-allowed-with-security-banner')
checks['F1_security_policy_classic_banner'] = blocked['mode'] == 'security' and 'Classic' in widget(blocked, 'banner')['text']
checks['F1_classic_policy_security_banner'] = inverse['mode'] == 'classic' and 'Security' in widget(inverse, 'banner')['text'] and inverse['provider_calls'] == 1

files = state('16-files-80x24-settings-hidden')
main = widget(files, 'main')['region']
gear = widget(files, 'settings-button')['region']
checks['F2_settings_outside_main_after_f6'] = gear[0] >= main[0] + main[2]
events = [json.loads(line) for line in (OUT/'classic-events.jsonl').read_text().splitlines()]
clicks = [e for e in events if e['command'] == {'op': 'click', 'selector': '#settings-button'} and e['state']['size'] == [80, 24]]
checks['F2_click_did_not_open_menu'] = any(widget(e['state'], 'action-card')['region'] == [0, 0, 0, 0] for e in clicks)

focus = state('15-new-chat-lost-focus')
focused = next(w for w in focus['widgets'] if w['focus'])
checks['F3_hidden_button_owns_focus'] = focused['id'] == 'work-refresh' and focused['region'] == [0, 0, 0, 0]
checks['F3_typed_abc_not_in_composer'] = widget(focus, 'prompt-input')['text'] == ''

onboarding = state('05-mode-narrow')
card = widget(onboarding, 'workspace-mode-card')['region']
checks['F4_onboarding_card_exceeds_height'] = card[1]+card[3] > onboarding['size'][1]
preview = state('17-file-preview-clipped')
parent = widget(preview, 'files-view')['region']
scroll = widget(preview, 'file-preview-scroll')['region']
checks['F5_inline_preview_exceeds_parent'] = scroll[1]+scroll[3] > parent[1]+parent[3]
checks['F5_read_succeeded_but_text_clipped'] = 'def helper():' in widget(preview, 'file-preview')['text']
approval = state('12-command-approval')
checks['F6_english_consent_in_spanish_ui'] = widget(approval, 'command-approval-title')['text'].startswith('Run a command') and widget(approval, 'command-approval-run')['label'].startswith('Ejecutar')

done = state('13-chat-complete')
checks['local_read_edit_run_diff_completed'] = done['provider_calls'] == 5 and done['file_value'] == 'value = 2\n'
cancel = state('20-cancel-keeps-draft')
checks['cancel_preserves_new_draft'] = widget(cancel, 'prompt-input')['text'] == 'BORRADOR que debe sobrevivir a Escape.'
error = state('21-provider-error-recovery')
checks['401_restores_original_prompt'] = widget(error, 'prompt-input')['text'] == 'Este mensaje debe recuperarse si el proveedor devuelve HTTP 401.'
checks['security_does_not_call_provider'] = blocked['provider_calls'] == error['provider_calls']
calls = (OUT/'classic-provider-calls.json').read_text()
checks['sensitive_canary_not_sent_to_provider'] = 'never_display_this_canary' not in calls

for path in OUT.glob('fixture-verification-*.json'):
    verification = json.loads(path.read_text())
    data = json.loads(verification['stdout'])
    checks[path.stem+'_journal_chain'] = verification['exit_code'] == 0 and data['journal']['status'] == 'PASS'

result = {'checks': checks, 'all_confirmed': all(checks.values()), 'suite': suite.attrib,
          'limits': ['inference simulated', 'no live accounts or remote integrations', 'no screen reader certification']}
(OUT/'evidence-verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
print(json.dumps(result, indent=2, ensure_ascii=False))
raise SystemExit(0 if all(checks.values()) else 1)
