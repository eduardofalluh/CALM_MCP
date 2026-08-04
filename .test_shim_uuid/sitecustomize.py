import json, requests
class _FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text; self.status_code = status_code
    def raise_for_status(self): pass
    def json(self): return json.loads(self.text)
_TEST_CASES = '[{"uuid": "550e8400-e29b-41d4-a716-446655440000", "projectId": "P001", "scopeId": "SC001", "solutionProcessId": "SP001", "title": "Test Customer Login", "isPrepared": true, "priorityCode": "20"}, {"uuid": "6ba7b810-9dad-11d1-80b4-00c04fd430c8", "projectId": "P001", "scopeId": "SC001", "solutionProcessId": "SP001", "title": "Test Password Reset", "isPrepared": false, "priorityCode": "30"}]'
def _fake_get(url, *a, **kw):
    if 'ManualTestCases' in url:
        return _FakeResp(json.dumps({'value': json.loads(_TEST_CASES)}))
    return _FakeResp('{}')
def _fake_request(method, url, *a, **kw):
    # Echo back with a real UUID
    body = json.loads(kw.get('data') or '{}')
    body['uuid'] = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    return _FakeResp(json.dumps(body))
requests.get = _fake_get
requests.request = _fake_request
