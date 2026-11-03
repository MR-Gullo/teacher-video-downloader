#!/usr/bin/env python3
"""Sign a reviewed app COPY. Ad hoc tests need no credentials and are never distributable."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from install_payload import digest, validate, check_bundle, bundle_digest

MACHO_MAGICS = {bytes.fromhex(value) for value in ('cffaedfe', 'feedfacf', 'cefaedfe', 'feedface', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}


def code_objects(app):
    objects = []
    for path in app.rglob('*'):
        if path.is_symlink():
            raise ValueError('Refusing an app containing symbolic links')
        if path.is_file():
            with path.open('rb') as stream:
                if stream.read(4) in MACHO_MAGICS:
                    objects.append(path)
    return sorted(objects, key=lambda path: (-len(path.parts), path.as_posix()))


def inspect(app, reviewed_source):
    if not re.fullmatch('[a-f0-9]{40}', reviewed_source):
        raise ValueError('Use the full reviewed 40-character source commit')
    resources = app / 'Contents/Resources'
    build = json.loads((resources / 'BUILD.json').read_text())
    if build['sourceCommit'] != reviewed_source or build['sourceDirty']:
        raise ValueError('The input must come from the exact reviewed clean source commit')
    embedded = app / 'Contents/Helpers/LessonShelf Companion.app'
    if build.get('component') not in ('companion', 'installer') or build.get('component') == 'installer' and not embedded.exists():
        raise ValueError('Use the current sealed-companion and installer builders')
    payload = embedded / 'Contents/Resources/payload' if embedded.exists() else resources / 'payload'
    spec = json.loads((payload / 'payload.json').read_text())
    validate(payload, spec['target'])
    provenance = json.loads((payload / 'PROVENANCE.json').read_text())
    if provenance['sourceCommit'] != reviewed_source or provenance['sourceDirty']:
        raise ValueError('The payload must come from the exact reviewed clean source commit')
    objects = [path for path in code_objects(app) if not embedded.exists() or embedded not in path.parents]
    if not objects:
        raise ValueError('No Mach-O signing inputs found')
    for name in (() if embedded.exists() else ('ffmpeg', 'ffprobe', 'N_m3u8DL-RE')):
        if provenance.get('toolSourceSHA256', {}).get(name) != digest(payload / 'tools' / name):
            raise ValueError('Source tool provenance does not match the unsigned input: ' + name)
    return build, spec, objects, embedded if embedded.exists() else None


def sign(app, output, reviewed_source, identity=None, adhoc_test=False, plan_only=False, reviewed_bundle_sha256=None):
    app, output = app.resolve(), output.absolute()
    build, spec, objects, embedded = inspect(app, reviewed_source)
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(app):
        raise ValueError('Use a new output outside the input app')
    if not adhoc_test and not plan_only and (not identity or not identity.startswith('Developer ID Application: ')):
        raise ValueError('A Developer ID Application identity is required; Apple Development is not suitable')
    input_bundle_sha = bundle_digest(app)
    if not adhoc_test and not plan_only and reviewed_bundle_sha256 != input_bundle_sha:
        raise ValueError('The app fingerprint must match the parent-reviewed bundle SHA-256')
    if adhoc_test and identity:
        raise ValueError('Ad hoc tests must not use a credential identity')
    if embedded is not None:
        check_bundle(embedded)
        if not adhoc_test and not plan_only:
            if not build.get('embeddedCompanionNotarizationRequired'):
                raise ValueError('A test-only outer installer cannot be signed for distribution')
            subprocess.run(['xcrun', 'stapler', 'validate', str(embedded)], check=True, capture_output=True)
    plan = {'inputBundleSHA256': input_bundle_sha, 'component': 'installer' if embedded else 'companion', 'schema': 1, 'sourceCommit': reviewed_source, 'inputApp': str(app), 'inputPayloadSHA256': digest((embedded / 'Contents/Resources/payload/payload.json') if embedded else app / 'Contents/Resources/payload/payload.json'),
            'codeObjectCount': len(objects), 'codeObjects': [path.relative_to(app).as_posix() for path in objects],
            'hardenedRuntime': True, 'entitlements': {}, 'libraryValidationDisabled': False,
            'mode': 'adhoc-test' if adhoc_test else 'Developer ID Application', 'notarized': False}
    if plan_only:
        return plan
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='signing-', dir=output.parent) as temporary:
        candidate = Path(temporary) / output.name
        shutil.copytree(app, candidate)
        if bundle_digest(candidate) != input_bundle_sha:
            raise ValueError('The app changed while preparing its signing copy')
        signing_identity = '-' if adhoc_test else identity
        command = ['/usr/bin/codesign', '--force', '--sign', signing_identity, '--options', 'runtime']
        command += ['--timestamp=none'] if adhoc_test else ['--timestamp']
        candidate_embedded = candidate / 'Contents/Helpers/LessonShelf Companion.app'
        embedded_digest = bundle_digest(candidate_embedded) if embedded else None
        for path in [p for p in code_objects(candidate) if not embedded or candidate_embedded not in p.parents]:
            subprocess.run(command + [str(path)], check=True, capture_output=True)
            subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(path)], check=True, capture_output=True)
        resources = candidate / 'Contents/Resources'
        payload = candidate_embedded / 'Contents/Resources/payload' if embedded else resources / 'payload'
        # Signing modifies Mach-O files. Preserve original provenance and refresh current-file hashes.
        if not embedded:
            spec['files'] = {name: digest(payload / name) for name in spec['files']}
            (payload / 'payload.json').write_text(json.dumps(spec, indent=2) + '\n')
        validate(payload, spec['target'])
        build['buildWasDistributionSigned'] = build.pop('signedForDistribution')
        build['buildWasNotarized'] = build.pop('notarized')
        build['inputExecutableSHA256'] = build.pop('executableSHA256')
        build['inputPayloadManifestSHA256'] = build.pop('payloadManifestSHA256')
        build['signingMode'] = plan['mode']
        build['payloadManifestSHA256'] = digest(payload / 'payload.json')
        (resources / 'BUILD.json').write_text(json.dumps(build, indent=2) + '\n')
        (resources / 'REVIEW-ONLY.txt').write_text('Ad hoc signing test only. Not for teachers.\n' if adhoc_test else 'Developer ID signed candidate. Notarization and release review remain required.\n')
        subprocess.run(command + [str(candidate)], check=True, capture_output=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(candidate)], check=True, capture_output=True)
        details = subprocess.check_output(['/usr/bin/codesign', '--display', '--verbose=4', str(candidate)], stderr=subprocess.STDOUT, text=True)
        if 'runtime' not in details:
            raise ValueError('Hardened runtime was not recorded by codesign')
        if not adhoc_test and 'Authority=Developer ID Application:' not in details:
            raise ValueError('The resulting app is not Developer ID Application signed')
        if embedded and bundle_digest(candidate_embedded) != embedded_digest:
            raise ValueError('Outer signing changed the sealed companion')
        plan.update({'embeddedCompanionUnchanged': True if embedded else None, 'completedAt': datetime.now(timezone.utc).isoformat(), 'codeSignStrictVerified': True,
                     'distributionSigned': not adhoc_test, 'teacherReady': False, 'payloadSHA256': digest(payload / 'payload.json'), 'outputBundleSHA256': bundle_digest(candidate),
                     'files': {p.relative_to(candidate).as_posix(): digest(p) for p in sorted(candidate.rglob('*')) if p.is_file()}})
        candidate.rename(output)
    (output.parent / (output.name + '.signing.json')).write_text(json.dumps(plan, indent=2) + '\n')
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewed-source', required=True)
    parser.add_argument('--reviewed-bundle-sha256')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--identity')
    group.add_argument('--adhoc-test', action='store_true')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    try:
        plan = sign(args.app, args.output, args.reviewed_source, args.identity, args.adhoc_test, args.plan_only, args.reviewed_bundle_sha256)
        print(json.dumps({key: plan[key] for key in ('sourceCommit', 'codeObjectCount', 'mode', 'notarized')}, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Signing stopped: ' + str(error) + '\n')
