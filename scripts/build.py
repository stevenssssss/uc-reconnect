#!/usr/bin/env python3
"""Compile the helper from AppleScript source without installing or launching it."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.1.0'
APP_NAME = 'UC Reconnect Helper.app'
HELPER_ID = 'org.uc-reconnect.helper'


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Build output already exists. Choose an empty output path.')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.uc-build-', dir=output.parent))
    try:
        app = temporary / APP_NAME
        subprocess.run(['/usr/bin/osacompile', '-o', str(app), str(ROOT / 'helper/launcher.applescript')], check=True)
        info_path = app / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleIdentifier=HELPER_ID, CFBundleName='UC Reconnect Helper',
                    CFBundleShortVersionString=VERSION, CFBundleVersion='1',
                    LSUIElement=True, LSMinimumSystemVersion='13.0',
                    NSAppleEventsUsageDescription='Select the configured Mac in Universal Control to reconnect its keyboard and mouse.')
        info_path.write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
        subprocess.run(['/usr/bin/osacompile', '-o', str(temporary / 'reconnect.scpt'), str(ROOT / 'helper/reconnect.applescript')], check=True)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
