#!/usr/bin/env python3
"""Windows/cross-platform equivalent of the original new_edit.sh, using its templates."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template')
    parser.add_argument('destination')
    parser.add_argument('--skip-install', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.template == 'finance-explainer':
        # Style A uses the sibling engine shipped in the original repository.
        source = (root.parent / 'finance-explainer' / 'templates' / 'engine').resolve()
        allowed_root = (root.parent / 'finance-explainer' / 'templates').resolve()
    else:
        source = (root / 'templates' / args.template).resolve()
        allowed_root = (root / 'templates').resolve()
    if not source.is_relative_to(allowed_root) or not (source / 'package.json').is_file():
        parser.error('Unknown original template: ' + args.template)
    destination = Path(args.destination).resolve()
    if (destination / 'src').exists():
        parser.error('Existing src/ will not be overwritten: ' + str(destination))
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', 'out', '.git'))
    # Keep the original dependency versions and composition; do not substitute an editor.
    modules_from = os.environ.get('DH_NODE_MODULES_FROM')
    if modules_from:
        modules = Path(modules_from) / 'node_modules'
        if all((modules / name).is_dir() for name in ('remotion', 'lottie-web', 'd3-geo')):
            shutil.copytree(modules, destination / 'node_modules')
    if not args.skip_install and not (destination / 'node_modules').exists():
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            parser.error('Node/npm is required; template has been preserved at ' + str(destination))
        subprocess.run([npm, 'ci' if (destination / 'package-lock.json').exists() else 'install'], cwd=destination, check=True)
    subprocess.run([sys.executable, '-X', 'utf8', str(root / 'scripts/make_assets.py'), str(destination / 'public')], check=True)
    print('Original template ready:', destination)
    if args.template == 'finance-explainer':
        print('Use finance-explainer/scripts/build_timeline.py to prepare public/timeline.json and place local host/voice assets in public/.')
    elif args.template.startswith('reference/'):
        print('Adapt the original example scenes, timeline and public/ assets to the current episode; see templates/reference/README.md.')
    else:
        print('Place main.mp4 / voice.wav in public/, align to src/tl.json, edit src/edit.json, then run check_edit.py.')


if __name__ == '__main__':
    main()
