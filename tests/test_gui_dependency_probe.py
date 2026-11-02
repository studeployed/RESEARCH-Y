"""Offline contract tests for the isolated dependency probe; no GUI installed."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gui_dependency_probe', ROOT / 'scripts/gui_dependency_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def item(package, package_version, requested=True):
    return {
        'is_direct': False, 'is_yanked': False, 'requested': requested,
        'requested_extras': ['native'] if package == 'nicegui' else [],
        'metadata': {'name': package, 'version': package_version, 'requires_dist': [],
                     'license_expression': 'MIT', 'classifier': ['License :: OSI Approved :: MIT License']},
        'download_info': {'url': f'https://files.pythonhosted.org/packages/ab/{package}-{package_version}.whl',
                          'archive_info': {'hashes': {'sha256': 'a' * 64}}},
    }


def report():
    return {'version': '1', 'pip_version': '25.1.1',
            'environment': {'sys_platform': 'linux', 'python_version': '3.13', 'implementation_name': 'cpython'},
            'install': [item('nicegui', '3.18.0'), item('pywebview', '6.2.1'), item('other', '2.0', False)]}


def release_for(row):
    return {'info': {'name': row['name'], 'version': row['version']}, 'vulnerabilities': [],
            'urls': [{'url': row['url'], 'digests': {'sha256': row['sha256']}, 'yanked': False}]}


def feed_for(source):
    rows = {r['name']: r for r in probe.packages(source)}
    return lambda package, version: release_for(rows[package])


def test_pinned_candidates_transitive_coordinates_and_no_acceptance():
    source = report()
    evidence = probe.inspect_resolution(source, feed_for(source))
    assert evidence['state'] == 'ready_for_isolated_install'
    assert evidence['package_count'] == 3
    assert evidence['approved_candidates'] == {'nicegui': '3.18.0', 'pywebview': '6.2.1'}
    assert [r['name'] for r in evidence['packages']] == ['nicegui', 'other', 'pywebview']
    assert all(not evidence[k] for k in ('gui_acceptance', 'production_adoption_approved',
               'runtime_install_verified', 'complete_security_audit', 'complete_license_review'))
    assert source == report()


@pytest.mark.parametrize('change,error', [
    (lambda r: r.update(version='2'), 'unsupported_pip_report'),
    (lambda r: r.update(install=[]), 'invalid_package_count'),
    (lambda r: r.update(install=r['install'] * 100), 'invalid_package_count'),
    (lambda r: r['install'].append(deepcopy(r['install'][0])), 'duplicate_package'),
    (lambda r: r['install'][0]['metadata'].update(version='3.17.0'), 'approved_candidates_changed_or_missing'),
    (lambda r: r['install'].pop(1), 'approved_candidates_changed_or_missing'),
    (lambda r: r['install'][2].update(requested=True), 'unapproved_top_level_requirement'),
    (lambda r: r['install'][0].update(requested_extras=['native', 'dev']), 'unapproved_requested_extra'),
    (lambda r: r['install'][1].update(requested_extras=['qt']), 'unapproved_requested_extra'),
    (lambda r: r['install'][0].update(is_direct=True), 'direct_or_yanked_distribution'),
    (lambda r: r['install'][0].update(is_yanked=True), 'direct_or_yanked_distribution'),
    (lambda r: r['install'][0].update(requested='true'), 'invalid_request_marker'),
    (lambda r: r['install'][0]['metadata'].update(requires_dist='other'), 'invalid_metadata_list'),
    (lambda r: r['install'][0]['metadata'].update(license={}), 'invalid_metadata_text'),
    (lambda r: r['environment'].update(sys_platform='darwin'), 'unsupported_probe_environment'),
    (lambda r: r['environment'].update(python_version='3.14'), 'unsupported_probe_environment'),
    (lambda r: r['environment'].update(implementation_name='pypy'), 'unsupported_probe_environment'),
    (lambda r: r['install'][0]['download_info']['archive_info'].update(hashes={}), 'malformed_pip_report'),
    (lambda r: r['install'][0]['download_info']['archive_info']['hashes'].update(sha256='bad'), 'missing_artifact_sha256'),
    (lambda r: r['install'][0]['download_info'].update(vcs_info={}), 'nonarchive_distribution'),
])
def test_bad_resolution_cannot_become_lock(change, error):
    source = report(); change(source)
    with pytest.raises(probe.ProbeError, match=error):
        probe.packages(source)


@pytest.mark.parametrize('url', ['http://files.pythonhosted.org/packages/a.whl',
    'https://example.org/packages/a.whl', 'https://files.pythonhosted.org.evil.test/packages/a.whl',
    'https://user:secret@files.pythonhosted.org/packages/a.whl',
    'https://files.pythonhosted.org:443/packages/a.whl',
    'file:///private/example.whl', 'https://files.pythonhosted.org/packages/a.whl?token=x',
    'https://files.pythonhosted.org/packages/a.whl#fragment',
    'https://files.pythonhosted.org/packages/a\n--extra-index-url=x',
    'https://files.pythonhosted.org/other/a.whl'])
def test_artifact_origin_never_controls_network_destination(url):
    source = report(); source['install'][0]['download_info']['url'] = url
    with pytest.raises(probe.ProbeError, match='invalid_artifact_origin'):
        probe.packages(source)


@pytest.mark.parametrize('bad', ['nicegui\n--index-url=x', ' x', 'x/y', '', '--flag', 'x;command'])
def test_names_cannot_inject_requirements_or_requests(bad):
    with pytest.raises(probe.ProbeError): probe.name(bad)


@pytest.mark.parametrize('bad', ['1\n--extra-index-url=x', '*', '>=3', '1;print()', '', None])
def test_versions_cannot_inject_requirements_or_requests(bad):
    with pytest.raises(probe.ProbeError): probe.version(bad)


def test_names_normalize_before_duplicate_check():
    source = report()
    source['install'][2]['metadata']['name'] = 'Other_Package'
    row = deepcopy(source['install'][2]); row['metadata']['name'] = 'other.package'
    source['install'].append(row)
    with pytest.raises(probe.ProbeError, match='duplicate_package'): probe.packages(source)


@pytest.mark.parametrize('raw', [b'{}bad', b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff'])
def test_invalid_json_is_not_partially_accepted(raw):
    with pytest.raises(probe.ProbeError): probe.decode(raw)


def test_json_size_guard(monkeypatch):
    monkeypatch.setattr(probe, 'MAX_BYTES', 3)
    with pytest.raises(probe.ProbeError): probe.decode(b'{"x":1}')


@pytest.mark.parametrize('change', [
    lambda r: r.pop('vulnerabilities'), lambda r: r.update(vulnerabilities=None),
    lambda r: r.update(vulnerabilities=[{'id': 1}]),
    lambda r: r['info'].update(version='wrong'), lambda r: r['info'].update(name='elsewhere'),
    lambda r: r['urls'][0]['digests'].update(sha256='b' * 64),
    lambda r: r.update(urls=[]), lambda r: r['urls'].append(deepcopy(r['urls'][0])),
    lambda r: r['urls'][0].update(yanked=True), lambda r: r['urls'][0].pop('yanked'),
])
def test_missing_or_bad_feed_evidence_is_unknown_not_clean(change):
    row = probe.packages(report())[0]; data = release_for(row); change(data)
    result = probe.release_observation(row, lambda *a: data)
    assert result['state'] == 'unverified'
    assert not result['artifact_verified_against_release'] and 'findings' not in result


def test_network_failure_is_static_and_blocks_install():
    def failed(*args): raise OSError('PRIVATE credential not to log')
    evidence = probe.inspect_resolution(report(), failed)
    assert evidence['state'] == 'blocked_pending_dependency_review'
    assert all(o['error'] == 'release_lookup_failed' for o in evidence['release_observations'])
    assert 'PRIVATE' not in json.dumps(evidence)


def test_real_finding_kept_and_blocks_install():
    source = report(); good_feed = feed_for(source)
    def feed(package, version):
        data = good_feed(package, version)
        if package == 'other':
            data['vulnerabilities'] = [{'id': 'TEST-1', 'aliases': ['TEST-ALIAS'], 'fixed_in': ['2.1']}]
        return data
    evidence = probe.inspect_resolution(source, feed)
    assert evidence['state'] == 'blocked_pending_dependency_review'
    bad = next(o for o in evidence['release_observations'] if o['name'] == 'other')
    assert bad['findings'][0]['id'] == 'TEST-1'
    assert not evidence['complete_security_audit']


def test_source_archives_and_build_limits_are_explicit():
    source = report()
    source['install'][2]['download_info']['url'] = 'https://files.pythonhosted.org/packages/ab/other-2.0.tar.gz'
    evidence = probe.inspect_resolution(source, feed_for(source))
    assert evidence['source_archives'] == ['other']
    assert any('Source-build' in line for line in evidence['limitations'])


def test_lock_contains_every_exact_archive_and_only_native_extra():
    rows = probe.packages(report())
    text = probe.lock_text(rows)
    lines = [line for line in text.splitlines() if not line.startswith('#')]
    assert len(lines) == 3
    assert lines[0] == 'nicegui[native]==3.18.0 --hash=sha256:' + 'a' * 64
    assert all('--hash=sha256:' in line and '==' in line for line in lines)
    assert 'https://' not in text and 'Not production adoption' in text


def test_install_verify_binds_artifacts_environment_and_installed_versions():
    source = report(); evidence = probe.inspect_resolution(source, feed_for(source))
    install = deepcopy(source)
    for r in install['install']: r['requested'] = True
    installed = {r['name']: r['version'] for r in evidence['packages']}
    done = probe.verify_install(evidence, source, install, installed)
    assert done['runtime_install_verified']
    assert not done['framework_imports_verified'] and not done['gui_acceptance']


@pytest.mark.parametrize('kind', ['artifact', 'missing', 'metadata', 'extra', 'environment', 'blocked'])
def test_install_disagreement_cannot_pass(kind):
    source = report(); evidence = probe.inspect_resolution(source, feed_for(source))
    install = deepcopy(source)
    installed = {r['name']: r['version'] for r in evidence['packages']}
    if kind == 'artifact': install['install'][2]['download_info']['archive_info']['hashes']['sha256'] = 'b' * 64
    if kind == 'missing': install['install'].pop()
    if kind == 'metadata': installed['other'] = '2.1'
    if kind == 'extra': installed['unexpected'] = '1'
    if kind == 'environment': install['environment']['sys_platform'] = 'win32'
    if kind == 'blocked': evidence['state'] = 'blocked_pending_dependency_review'
    with pytest.raises(probe.ProbeError): probe.verify_install(evidence, source, install, installed)


def test_release_transport_fixed_https_bounded_no_redirects(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, limit):
            calls.append(('limit', limit)); return b'{}'
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout)); return Response()
    monkeypatch.setattr(probe, 'build_opener', lambda *a: Opener())
    assert probe.fetch_release('Other_Package', '1.2+local') == {}
    assert calls == [('https://pypi.org/pypi/other-package/1.2%2Blocal/json', 10), ('limit', probe.MAX_BYTES + 1)]
    with pytest.raises(probe.ProbeError, match='release_redirect_refused'):
        probe.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')


def test_cli_requires_virtual_environment_and_writes_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.sys, 'prefix', probe.sys.base_prefix)
    assert probe.main(['prepare', '--directory', str(tmp_path)]) == 1
    result = json.loads((tmp_path / 'probe-error.json').read_text())
    assert result['error'] == 'isolated_environment_required'
    assert not (tmp_path / 'candidate-lock.txt').exists()


def test_cli_prepare_writes_hash_bound_evidence_without_importing_gui(tmp_path, monkeypatch):
    source = report(); source['environment']['sys_platform'] = sys.platform
    source['environment']['python_version'] = f'{sys.version_info.major}.{sys.version_info.minor}'
    raw = json.dumps(source).encode(); (tmp_path / 'resolution.json').write_bytes(raw)
    monkeypatch.setattr(probe.sys, 'prefix', 'synthetic-isolated-environment')
    real_inspect = probe.inspect_resolution
    monkeypatch.setattr(probe, 'inspect_resolution', lambda data: real_inspect(data, feed_for(data)))
    monkeypatch.setattr(probe, 'import_module', lambda *a: pytest.fail('prepare must not import GUI'))
    assert probe.main(['prepare', '--directory', str(tmp_path)]) == 0
    evidence = json.loads((tmp_path / 'dependency-evidence.json').read_text())
    assert evidence['resolution_report_sha256'] == probe.sha256(raw).hexdigest()
    assert (tmp_path / 'candidate-lock.txt').exists()


def test_workflow_is_separate_isolated_secretless_and_preserves_failures():
    text = (ROOT / '.github/workflows/gui-dependency-probe.yml').read_text()
    assert 'pull_request:' in text and 'pull_request_target:' not in text
    assert 'persist-credentials: false' in text and 'contents: read' in text
    assert 'secrets.' not in text and 'continue-on-error' not in text
    assert 'system_site_packages=False' in text and 'venv.EnvBuilder' in text
    assert '--require-hashes' in text and '--dry-run --ignore-installed' in text
    assert 'python -m pip check' in text and 'if: always()' in text
    assert 'windows-latest' in text and 'ubuntu-latest' in text
    assert '"3.12"' in text and '"3.13"' in text
    assert 'test.yml' not in text and 'requirements-dev.txt' not in text
    requirements = (ROOT / 'tools/gui_feasibility/requirements.txt').read_text()
    assert [s for s in requirements.splitlines() if s and not s.startswith('#')] == [
        'nicegui[native]==3.18.0', 'pywebview==6.2.1']


@pytest.mark.parametrize('kind', ['missing', 'findings', 'unverified', 'duplicate'])
def test_clean_marker_cannot_hide_missing_or_changed_release_evidence(kind):
    source = report(); evidence = probe.inspect_resolution(source, feed_for(source))
    installed = {r['name']: r['version'] for r in evidence['packages']}
    if kind == 'missing': evidence['release_observations'].pop()
    if kind == 'findings': evidence['release_observations'][0]['findings'] = [{'id': 'TEST'}]
    if kind == 'unverified': evidence['release_observations'][0]['artifact_verified_against_release'] = False
    if kind == 'duplicate': evidence['release_observations'][1] = evidence['release_observations'][0]
    with pytest.raises(probe.ProbeError, match='unverified_install_release_evidence'):
        probe.verify_install(evidence, source, source, installed)


def test_installed_coordinates_ignore_only_bootstrap_not_runtime_setuptools():
    class Distribution:
        def __init__(self, key, ver): self.metadata = {'Name': key}; self.version = ver
    rows = [Distribution('pip', '25.1'), Distribution('setuptools', '80.9.0'), Distribution('other', '2.0')]
    assert probe.installed_coordinates(rows, {'other'}) == {'other': '2.0'}
    assert probe.installed_coordinates(rows, {'setuptools', 'other'}) == {'setuptools': '80.9.0', 'other': '2.0'}
    rows.append(Distribution('Other', '3.0'))
    with pytest.raises(probe.ProbeError, match='duplicate_installed_distribution'):
        probe.installed_coordinates(rows, {'other'})
