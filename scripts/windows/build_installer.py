#!/usr/bin/env python3
"""Compile Windows .NET 4.8 launcher or self-contained offline installer. No installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import zipfile


def validate_windows_payload(payload):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'macos'))
    from install_payload import validate
    validate(payload, 'windows-x64')
    for path in payload.rglob('*'):
        if not path.is_file(): continue
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                if path.suffix.lower() in ('.exe', '.dll', '.pyd'):
                    raise ValueError('Not a Windows executable: ' + str(path.relative_to(payload)))
                continue
            stream.seek(60); offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(offset)
            if stream.read(4) != b'PE\0\0' or struct.unpack('<H', stream.read(2))[0] != 0x8664:
                raise ValueError('Wrong Windows executable architecture: ' + str(path.relative_to(payload)))


def compiler(sdk, references, work):
    if sdk:
        csc = sorted((sdk / 'sdk').glob('*/Roslyn/bincore/csc.dll'))[-1]
        prefix = [str(sdk / ('dotnet.exe' if os.name == 'nt' else 'dotnet')), str(csc)]
        folder = next(references.rglob('v4.8'))
    else:
        runtime = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319'
        prefix = [str(runtime / 'csc.exe')]
        folder = next(references.rglob('v4.8')) if references else Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Reference Assemblies/Microsoft/Framework/.NETFramework/v4.8'
        if not folder.exists():
            folder = runtime
    env = dict(os.environ, DOTNET_CLI_HOME=str(work / 'dotnet-home'), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_NOLOGO='1')
    common = prefix + ['/nologo', '/noconfig', '/nostdlib+', '/platform:x64', '/optimize+', '/target:exe']
    for name in ('mscorlib', 'System', 'System.Core', 'System.Drawing', 'System.Windows.Forms', 'System.Web.Extensions', 'System.IO.Compression'):
        common.append('/reference:' + str(folder / (name + '.dll')))
    return common, env


def build(output, sdk=None, references=None, payload=None):
    if output.exists():
        raise ValueError('Refusing to replace an existing executable')
    if payload is not None:
        validate_windows_payload(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='windows-build-', dir=output.parent) as temporary:
        work = Path(temporary)
        command, env = compiler(sdk, references, work)
        compiled = work / 'candidate.exe'
        if payload is None:
            source = Path(__file__).with_name('Launcher.cs')
            subprocess.run(command + ['/out:' + str(compiled), str(source)], check=True, env=env)
        else:
            command = ['/target:winexe' if arg == '/target:exe' else arg for arg in command]
            archive = work / 'payload.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
                for path in sorted(payload.rglob('*')):
                    if path.is_file():
                        stream.write(path, path.relative_to(payload).as_posix())
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            source = work / 'Installer.cs'
            source.write_text(Path(__file__).with_name('Installer.cs').read_text().replace('PAYLOAD_SHA256_PLACEHOLDER', digest))
            subprocess.run(command + ['/out:' + str(compiled), '/resource:' + str(archive) + ',payload.zip', str(source)], check=True, env=env)
            os.rename(compiled, output)
            (output.parent / (output.name + '.json')).write_text(json.dumps({'artifactSHA256': hashlib.sha256(output.read_bytes()).hexdigest(), 'embeddedPayloadSHA256': digest, 'authenticodeSigned': False, 'windowsExecuted': False}, indent=2) + '\n')
        if payload is None:
            os.rename(compiled, output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--references', type=Path)
    parser.add_argument('--payload', type=Path, help='Omit to compile only the native host launcher')
    args = parser.parse_args()
    build(args.output.absolute(), args.sdk.resolve() if args.sdk else None, args.references.resolve() if args.references else None, args.payload.resolve() if args.payload else None)
