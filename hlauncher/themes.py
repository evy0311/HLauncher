"""Validated layout themes stored alongside user settings."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .config import STATE_DIR
from .setup_state import atomic_json


THEME_ID = re.compile(r'[a-z][a-z0-9-]{0,31}')
SCREENS = ('home', 'settings', 'appearance_settings', 'system_settings', 'recovery_settings')
LAYOUTS = ('rail', 'list', 'grid')
COLORS = ('background', 'panel', 'accent', 'text', 'muted')
MAX_BYTES = 8192
MAX_CUSTOM = 24


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    layouts: dict
    colors: dict

    def document(self):
        return dict(format=1, id=self.id, name=self.name, layouts=self.layouts, colors=self.colors)


OEM = Theme('oem', 'OEM', {}, {})
RAIL = Theme('rail', 'Rail', dict.fromkeys(SCREENS, 'rail'),
             dict(background='#11191E', panel='#213139', accent='#82D4C4', text='#F4F8F6', muted='#A7BEC5'))
STACK = Theme('stack', 'Stack', dict.fromkeys(SCREENS, 'list'),
              dict(background='#1C1813', panel='#332B22', accent='#FFD393', text='#FFF6E9', muted='#D3BD9F'))
BUILTIN = {theme.id: theme for theme in (OEM, RAIL, STACK)}


def validate(document):
    if (not isinstance(document, dict) or set(document) != {'format', 'id', 'name', 'layouts', 'colors'}
            or type(document['format']) is not int or document['format'] != 1):
        raise ValueError('Expected a theme in format 1')
    identifier, name = document['id'], document['name']
    if not isinstance(identifier, str) or not THEME_ID.fullmatch(identifier) or identifier in BUILTIN:
        raise ValueError('Choose a unique theme ID using lowercase letters, numbers and hyphens')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or not name.isprintable():
        raise ValueError('Enter a theme name of 1 to 32 characters')
    layouts, colors = document['layouts'], document['colors']
    if (not isinstance(layouts, dict) or not layouts or any(
            screen not in SCREENS or layout not in LAYOUTS for screen, layout in layouts.items())):
        raise ValueError('Choose a supported layout for at least one screen')
    if (not isinstance(colors, dict) or set(colors) != set(COLORS) or any(
            not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value)
            for value in colors.values())):
        raise ValueError('Provide all five theme colors as #RRGGBB')
    return Theme(identifier, name.strip(), dict(layouts), dict(colors))


def read_theme(path):
    with path.open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Theme file exceeds 8 KiB')
    try:
        return validate(json.loads(data))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid theme file') from exc


class Themes:
    def __init__(self, state_dir):
        self.folder = Path(state_dir) / 'themes'
        self.choices = {}
        self.reload()

    def reload(self):
        self.choices = dict(BUILTIN)
        try:
            paths = sorted(self.folder.glob('*.json'))
        except OSError:
            return
        for path in paths[:MAX_CUSTOM]:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                theme = read_theme(path)
                if path.stem == theme.id:
                    self.choices[theme.id] = theme
            except (OSError, ValueError):
                continue

    def get(self, identifier):
        return self.choices.get(identifier, OEM)

    def install(self, source):
        return self._save(read_theme(source))

    def install_document(self, document):
        return self._save(validate(document))

    def _save(self, theme):
        path = self.folder / (theme.id + '.json')
        if not path.exists() and sum(1 for _ in self.folder.glob('*.json')) >= MAX_CUSTOM:
            raise ValueError('The custom theme limit has been reached')
        atomic_json(path, theme.document())
        self.reload()
        return theme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=STATE_DIR)
    commands = parser.add_subparsers(dest='command', required=True)
    copy = commands.add_parser('copy', help='Export a theme as an editable JSON file')
    copy.add_argument('source', help='Installed theme ID')
    copy.add_argument('id', help='New theme ID')
    copy.add_argument('name', help='New display name')
    copy.add_argument('output', type=Path)
    install = commands.add_parser('install', help='Import a JSON theme into HLauncher')
    install.add_argument('source', type=Path)
    args = parser.parse_args()
    themes = Themes(args.state_dir)
    try:
        if args.command == 'install':
            print(f'Installed {themes.install(args.source).name}')
        else:
            source = themes.choices.get(args.source)
            if source is None or source is OEM:
                raise ValueError('Select Rail, Stack or an installed custom theme as a template')
            document = dict(source.document(), id=args.id, name=args.name)
            validate(document)
            with args.output.open('x') as output:
                json.dump(document, output, indent=2)
                output.write('\n')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
