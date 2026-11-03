#!/usr/bin/env python3
"""Prepare or notarize an already signed reviewed app COPY using a named Keychain profile."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
from install_payload import digest, check_bundle, bundle_digest


def assess(app, reviewed_source):
    if not re.fullmatch('[a-f0-9]{40}', reviewed_source):
        raise ValueError('Use the full reviewed source commit')
    build = json.loads((app / 'Contents/Resources/BUILD.json').read_text())
    if build['sourceCommit'] != reviewed_source or build['sourceDirty']:
        raise ValueError('App source does not match the exact reviewed clean commit')
    check_bundle(app)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if info['CFBundleIdentifier'] not in ('org.lessonshelf.companion', 'org.lessonshelf.installer'):
        raise ValueError('Unsupported bundle identifier')
    details = subprocess.check_output(['/usr/bin/codesign', '--display', '--verbose=4', str(app)], stderr=subprocess.STDOUT, text=True)
    eligible = 'Authority=Developer ID Application:' in details and 'Timestamp=' in details and 'runtime' in details
    component = 'companion' if info['CFBundleIdentifier'].endswith('.companion') else 'installer'
    if component == 'installer':
        embedded = app / 'Contents/Helpers/LessonShelf Companion.app'
        check_bundle(embedded)
        if eligible:
            subprocess.run(['xcrun', 'stapler', 'validate', str(embedded)], check=True, capture_output=True)
    return {'inputBundleSHA256': bundle_digest(app), 'schema': 1, 'sourceCommit': reviewed_source, 'component': component, 'eligibleForSubmission': eligible,
            'requiresHumanKeychainProfile': True, 'notarized': False, 'browserDownloadVerified': False}


def notarize(app, output, reviewed_source, profile=None, submit=False, reviewed_bundle_sha256=None):
    app, output = app.resolve(), output.absolute()
    plan = assess(app, reviewed_source)
    if not submit:
        return plan
    if not plan['eligibleForSubmission']:
        raise ValueError('Submit requires Developer ID Application signing, secure timestamps and hardened runtime')
    if reviewed_bundle_sha256 != plan['inputBundleSHA256']:
        raise ValueError('The app fingerprint must match the approved signed bundle SHA-256')
    if not profile or any(c in profile for c in ('\n', '\r', '\0')):
        raise ValueError('Use a named Keychain profile created by the account holder')
    archive = output.with_suffix('.zip')
    sidecar = output.parent / (output.name + '.notary.json')
    upload = output.parent / (output.name + '.submission.zip')
    if output.exists() or archive.exists() or sidecar.exists() or upload.exists() or output.resolve().is_relative_to(app):
        raise ValueError('Use new output paths outside the input app')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='notarization-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        candidate = temporary / output.name
        shutil.copytree(app, candidate)
        if bundle_digest(candidate) != plan['inputBundleSHA256']:
            raise ValueError('The signed app changed while preparing the upload')
        subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(candidate), str(upload)], check=True)
        plan.update({'uploadSHA256': digest(upload), 'uploadBytes': upload.stat().st_size, 'status': 'Submission pending'})
        sidecar.write_text(json.dumps(plan, indent=2) + '\n')
        # Profile names are handles only. Never accept passwords, API keys or private key paths here.
        response = subprocess.run(['xcrun', 'notarytool', 'submit', str(upload), '--keychain-profile', profile,
                                   '--wait', '--output-format', 'json'], capture_output=True, text=True, check=True)
        data = json.loads(response.stdout)
        plan.update({'submittedAt': datetime.now(timezone.utc).isoformat(), 'submissionId': data.get('id'), 'status': data.get('status')})
        sidecar.write_text(json.dumps(plan, indent=2) + '\n')
        if data.get('status') != 'Accepted':
            if data.get('id'):
                subprocess.run(['xcrun', 'notarytool', 'log', data['id'], '--keychain-profile', profile,
                                str(output.parent / (output.name + '.notary-log.json'))], check=False)
            raise ValueError('Apple did not accept this candidate. Submission evidence was retained')
        subprocess.run(['xcrun', 'stapler', 'staple', str(candidate)], check=True)
        subprocess.run(['xcrun', 'stapler', 'validate', str(candidate)], check=True)
        check_bundle(candidate)
        subprocess.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', str(candidate)], check=True)
        candidate.rename(output)
        subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(output), str(archive)], check=True)
    plan.update({'notarized': True, 'stapledTicketValidated': True, 'developmentMacGatekeeperAssessment': True,
                 'archiveSHA256': digest(archive), 'archiveBytes': archive.stat().st_size})
    sidecar.write_text(json.dumps(plan, indent=2) + '\n')
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewed-source', required=True)
    parser.add_argument('--reviewed-bundle-sha256')
    parser.add_argument('--keychain-profile')
    parser.add_argument('--submit', action='store_true', help='Explicit credential-enabled Apple code upload')
    args = parser.parse_args()
    try:
        print(json.dumps(notarize(args.app, args.output, args.reviewed_source, args.keychain_profile, args.submit, args.reviewed_bundle_sha256), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Notarization stopped: ' + str(error) + '\n')
