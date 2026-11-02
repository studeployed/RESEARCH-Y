"""Isolated GUI dependency evidence; not a production lock or GUI acceptance.

Use with the dedicated workflow, never the application runtime. Only public PyPI
package coordinates are sent to the release feed. No project, credential or user
configuration is read. Resolution and installation are delegated to pip; this
module validates their recorded artifacts and refuses incomplete feed evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module, metadata as installed_metadata
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

APPROVED = {'nicegui': '3.18.0', 'pywebview': '6.2.1'}
MAX_BYTES = 16 * 1024 * 1024
MAX_PACKAGES = 256
LIMITATIONS = [
    'Prototype only; production adoption is not approved.',
    'First resolution chooses transitive versions; the generated lock records that observation.',
    'Hash checks bind selected archives, not a reviewed or trusted software supply chain.',
    'Source-build dependencies and reproducible built wheels are not inventoried.',
    'Declared Python licences are collected, not a completed licence/legal review.',
    'Embedded frontend dependencies, native runtimes and their licences/advisories remain unaudited.',
    'An empty PyPI vulnerability list means no findings in that feed at that time, not no vulnerabilities.',
    'Imports do not prove browser security, offline assets, native launch or worker/window cleanup.',
]


class ProbeError(ValueError):
    """Static code only; do not echo arbitrary package/server/error text into logs."""


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,198}[A-Za-z0-9])?', value):
        raise ProbeError('invalid_package_name')
    return re.sub(r'[-_.]+', '-', value).lower()


def version(value):
    # A conservative filename/requirement-safe subset, not a replacement PEP 440 parser.
    if not isinstance(value, str) or not re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]{0,99}', value):
        raise ProbeError('invalid_package_version')
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ProbeError('duplicate_json_key')
        result[key] = value
    return result


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ProbeError('oversized_or_invalid_json')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProbeError('nonfinite_json')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProbeError):
            raise
        raise ProbeError('invalid_json') from None


def _text_list(value):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ProbeError('invalid_metadata_list')
    return list(value)


def _optional_text(value):
    if value is not None and not isinstance(value, str):
        raise ProbeError('invalid_metadata_text')
    return value


def packages(report, *, initial=True):
    """Normalize a version-1 pip report without following any report URL."""
    try:
        if report['version'] != '1' or not isinstance(report['pip_version'], str):
            raise ProbeError('unsupported_pip_report')
        environment = report['environment']
        if (not isinstance(environment, dict)
                or environment.get('sys_platform') not in ('win32', 'linux')
                or environment.get('python_version') not in ('3.12', '3.13')
                or environment.get('implementation_name') != 'cpython'):
            raise ProbeError('unsupported_probe_environment')
        rows = report['install']
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PACKAGES:
            raise ProbeError('invalid_package_count')
        result = {}
        requested = set()
        for row in rows:
            meta = row['metadata']
            key, ver = name(meta['name']), version(meta['version'])
            if key in result:
                raise ProbeError('duplicate_package')
            if row['is_direct'] is not False or row['is_yanked'] is not False:
                raise ProbeError('direct_or_yanked_distribution')
            if type(row['requested']) is not bool:
                raise ProbeError('invalid_request_marker')
            if row['requested']:
                requested.add(key)
            extras = _text_list(row.get('requested_extras', []))
            if row['requested'] and (initial or key in APPROVED) and set(extras) - ({'native'} if key == 'nicegui' else set()):
                raise ProbeError('unapproved_requested_extra')
            download = row['download_info']
            if set(download) != {'url', 'archive_info'}:
                raise ProbeError('nonarchive_distribution')
            url = download['url']
            if not isinstance(url, str) or any(c.isspace() for c in url):
                raise ProbeError('invalid_artifact_origin')
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.netloc != 'files.pythonhosted.org'
                    or not parsed.path.startswith('/packages/') or parsed.query or parsed.fragment
                    or '\\' in parsed.path):
                raise ProbeError('invalid_artifact_origin')
            digest = download['archive_info']['hashes']['sha256']
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ProbeError('missing_artifact_sha256')
            result[key] = {
                'name': key, 'version': ver, 'url': url, 'sha256': digest,
                'artifact_kind': 'wheel' if parsed.path.endswith('.whl') else 'source_archive',
                'requires_dist': _text_list(meta.get('requires_dist', [])),
                'requires_python': _optional_text(meta.get('requires_python')),
                'declared_license': _optional_text(meta.get('license')),
                'declared_license_expression': _optional_text(meta.get('license_expression')),
                'declared_license_files': _text_list(meta.get('license_file', [])),
                'declared_license_classifiers': [x for x in _text_list(meta.get('classifier', []))
                                                 if x.startswith('License ::')],
            }
        if any(result.get(k, {}).get('version') != v for k, v in APPROVED.items()):
            raise ProbeError('approved_candidates_changed_or_missing')
        if initial and requested != set(APPROVED):
            raise ProbeError('unapproved_top_level_requirement')
        return [result[k] for k in sorted(result)]
    except (KeyError, TypeError, AttributeError):
        raise ProbeError('malformed_pip_report') from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError('release_redirect_refused')


def fetch_release(package, package_version):
    url = f'https://pypi.org/pypi/{quote(name(package), safe="")}/{quote(version(package_version), safe="")}/json'
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers={'Accept': 'application/json',
                                   'User-Agent': 'RESEARCH-Y-isolated-dependency-feasibility/1'})
    with opener.open(request, timeout=10) as response:
        raw = response.read(MAX_BYTES + 1)
    return decode(raw)


def release_observation(package, fetch=fetch_release):
    """Unavailable/malformed release evidence must never turn into a clean audit."""
    base = {'name': package['name'], 'version': package['version'],
            'feed': 'PyPI release JSON', 'checked_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        data = fetch(package['name'], package['version'])
        info = data['info']
        if name(info['name']) != package['name'] or version(info['version']) != package['version']:
            raise ProbeError('release_identity_mismatch')
        matches = [f for f in data['urls'] if f['url'] == package['url']]
        if len(matches) != 1 or matches[0]['digests']['sha256'] != package['sha256']:
            raise ProbeError('release_artifact_mismatch')
        if matches[0]['yanked'] is not False:
            raise ProbeError('release_artifact_yanked')
        vulnerabilities = data['vulnerabilities']  # Required: missing is UNKNOWN, not [].
        if not isinstance(vulnerabilities, list):
            raise ProbeError('invalid_vulnerability_feed')
        findings = []
        for finding in vulnerabilities:
            if not isinstance(finding['id'], str) or not finding['id']:
                raise ProbeError('invalid_vulnerability_feed')
            findings.append({'id': finding['id'],
                             'aliases': _text_list(finding.get('aliases', [])),
                             'fixed_in': _text_list(finding.get('fixed_in', []))})
        return {**base, 'state': 'findings' if findings else 'no_findings_in_feed',
                'findings': findings, 'artifact_verified_against_release': True}
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProbeError) else 'release_lookup_failed'
        return {**base, 'state': 'unverified', 'error': code,
                'artifact_verified_against_release': False}


def lock_text(rows):
    lines = ['# Experimental runtime artifacts for ONE recorded platform/Python resolution.',
             '# Not production adoption; source-build and frontend inputs remain unpinned.']
    for row in rows:
        extra = '[native]' if row['name'] == 'nicegui' else ''
        lines.append(f"{row['name']}{extra}=={row['version']} --hash=sha256:{row['sha256']}")
    return '\n'.join(lines) + '\n'


def inspect_resolution(report, fetch=fetch_release):
    rows = packages(report)
    with ThreadPoolExecutor(max_workers=4) as pool:
        observations = list(pool.map(lambda row: release_observation(row, fetch), rows))
    allowed = all(o['state'] == 'no_findings_in_feed' for o in observations)
    return {
        'format': 'research-y-gui-dependency-probe-v1',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'approved_candidates': APPROVED.copy(), 'pip_version': report['pip_version'],
        'environment': report['environment'], 'packages': rows, 'release_observations': observations,
        'package_count': len(rows), 'source_archives': [r['name'] for r in rows if r['artifact_kind'] != 'wheel'],
        'state': 'ready_for_isolated_install' if allowed else 'blocked_pending_dependency_review',
        'runtime_install_verified': False, 'framework_imports_verified': False,
        'production_adoption_approved': False, 'gui_acceptance': False,
        'complete_security_audit': False, 'complete_license_review': False,
        'limitations': LIMITATIONS.copy(),
    }


def installed_coordinates(distributions, runtime_names):
    result = {}
    for distribution in distributions:
        key = name(distribution.metadata['Name'])
        if key in result:
            raise ProbeError('duplicate_installed_distribution')
        result[key] = version(distribution.version)
    return {k: v for k, v in result.items()
            if k not in ('pip', 'setuptools') or k in runtime_names}


def verify_install(evidence, resolution, installation, installed):
    """Bind installed coordinates/archives to the observed resolution, not pip's exit code."""
    rows, actual = packages(resolution), packages(installation, initial=False)
    if (evidence.get('state') != 'ready_for_isolated_install'
            or evidence.get('packages') != rows or evidence.get('environment') != resolution['environment']):
        raise ProbeError('unapproved_install_evidence')
    observations = evidence.get('release_observations', [])
    expected = {(r['name'], r['version']) for r in rows}
    if (not isinstance(observations, list) or len(observations) != len(rows)
            or {(o.get('name'), o.get('version')) for o in observations} != expected
            or any(o.get('state') != 'no_findings_in_feed'
                   or o.get('artifact_verified_against_release') is not True
                   or o.get('findings') != [] for o in observations)):
        raise ProbeError('unverified_install_release_evidence')
    if installation['environment'] != resolution['environment']:
        raise ProbeError('installation_environment_changed')
    identity = lambda xs: {(r['name'], r['version'], r['sha256'], r['url']) for r in xs}
    if identity(rows) != identity(actual):
        raise ProbeError('installed_artifacts_changed')
    if installed != {r['name']: r['version'] for r in rows}:
        raise ProbeError('installed_metadata_changed')
    return {**evidence, 'runtime_install_verified': True, 'state': 'runtime_install_verified_pending_imports'}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'verify'])
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = directory / 'dependency-evidence.json'
    try:
        if sys.prefix == sys.base_prefix:
            raise ProbeError('isolated_environment_required')
        resolution = decode((directory / 'resolution.json').read_bytes())
        if (resolution['environment']['sys_platform'] != sys.platform
                or resolution['environment']['python_version'] != f'{sys.version_info.major}.{sys.version_info.minor}'):
            raise ProbeError('resolution_not_from_this_runtime')
        if args.phase == 'prepare':
            evidence = inspect_resolution(resolution)
            raw_digest = sha256((directory / 'resolution.json').read_bytes()).hexdigest()
            evidence['resolution_report_sha256'] = raw_digest
            write_json(evidence_path, evidence)
            if evidence['state'] != 'ready_for_isolated_install':
                return 1
            lock = lock_text(evidence['packages'])
            (directory / 'candidate-lock.txt').write_text(lock, encoding='utf-8')
        else:
            evidence = decode(evidence_path.read_bytes())
            if evidence['resolution_report_sha256'] != sha256((directory / 'resolution.json').read_bytes()).hexdigest():
                raise ProbeError('resolution_report_changed')
            installation = decode((directory / 'installation.json').read_bytes())
            actual = installed_coordinates(installed_metadata.distributions(),
                                           {r['name'] for r in packages(resolution)})
            evidence = verify_install(evidence, resolution, installation, actual)
            for module in ('nicegui', 'webview'):
                try:
                    import_module(module)  # Import only, not native/server acceptance.
                except Exception:
                    raise ProbeError('framework_import_failed_' + module) from None
            evidence['installation_pip_version'] = installation['pip_version']
            evidence.update(framework_imports_verified=True, state='dependency_probe_passed_pending_review')
            write_json(evidence_path, evidence)
        print(f"GUI dependency probe: {args.phase} completed; production and GUI acceptance remain pending.")
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProbeError) else 'probe_failed'
        write_json(directory / 'probe-error.json', {'phase': args.phase, 'error': code,
                   'gui_acceptance': False, 'production_adoption_approved': False})
        print(f'GUI dependency probe failed: {code}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
