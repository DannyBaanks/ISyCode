from pathlib import Path
import hashlib,importlib.util,json,subprocess
repo=Path('/home/danny/Development/ISyCo Git/ISyCode')
evidence=Path(__file__).parent
name='docs/evidence/classic-security-ux/M8/32aa6ccbb4604fe9c33b7bdbb8e152716a4cbeaa/gate.yaml'
spec=importlib.util.spec_from_file_location('readonly_gate_validator',repo/'scripts/validate_gates.py')
validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
for label,commit in [('A-correct-substituted-test-fingerprint','1871ab422d02d0145475460b1c6a911f5f0da8d1'),('B-restore-original-reviewed-artifact','db697b6302e8374ad0be8a3082fedb6cf4079ab2')]:
    content=(evidence/(label+'-candidate.txt')).read_bytes()
    blob=subprocess.run(['git','show',commit+':'+name],cwd=repo,capture_output=True,check=True).stdout
    document=validator.document_from_text(content.decode())
    errors=validator.validate_document(document,required_ids=validator.REQUIRED_BY_GATE['G8'],dependency_states={'G7':'APROBADO'})
    for case in document['casos']:
        errors.extend(validator._artifact_errors(repo,(repo/name).parent,case,strict=True,evaluated_sha=document['sha_evaluado']))
    print(json.dumps({'candidate':label,'historical_commit':commit,'identical_to_commit_manifest':content==blob,'candidate_sha256':hashlib.sha256(content).hexdigest(),'historical_validation_errors':errors}))
    assert content==blob and not errors
print('Read-only candidate verification completed; no repository edit or new acceptance.')
