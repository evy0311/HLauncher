"""Live CarPlay picture controls for SSH and the launcher settings page."""

import argparse
import json
from sdk.hlauncher_sdk.picture import PictureSettings, DEFAULTS, LIMITS


def interactive(settings):
    import curses
    def screen(window):
        curses.curs_set(0)
        window.keypad(True)
        window.timeout(200)
        selected = 0
        names = list(DEFAULTS)
        error = ''
        while True:
            settings.refresh()
            window.erase()
            lines = ['CarPlay picture — live HDMI preview', '',
                     'Up/Down: select   Left/Right: adjust   R: reset   Q: exit', '']
            for i, key in enumerate(names):
                low, high = LIMITS[key]
                value = settings.values[key]
                filled = round((value-low)/(high-low)*24)
                lines.append(f'{">" if i==selected else " "} {key:10} [{"="*filled}{" "*(24-filled)}] {value:+d}' if key=='brightness' else f'{">" if i==selected else " "} {key:10} [{"="*filled}{" "*(24-filled)}] {value}%')
            lines += ['', 'Leave CarPlay visible on the radio while adjusting.',
                      'Settings are saved automatically. Only CarPlay video changes.', error]
            h,w = window.getmaxyx()
            for y,line in enumerate(lines[:max(0,h-1)]):
                window.addnstr(y,0,line,max(0,w-1))
            window.refresh()
            c = window.getch()
            if c in (ord('q'),ord('Q'),27):return
            if c == curses.KEY_UP:selected=(selected-1)%len(names)
            elif c == curses.KEY_DOWN:selected=(selected+1)%len(names)
            else:
                values = dict(settings.values)
                key=names[selected]
                if c in (ord('r'),ord('R')):values=dict(DEFAULTS)
                elif c in (curses.KEY_LEFT,ord('-')):values[key]=max(LIMITS[key][0],values[key]-1)
                elif c in (curses.KEY_RIGHT,ord('+'),ord('=')):values[key]=min(LIMITS[key][1],values[key]+1)
                else:continue
                try:
                    settings.save(values)
                    error=''
                except OSError as exc:error=str(exc)
    curses.wrapper(screen)


def main(argv):
    parser=argparse.ArgumentParser(description='Live CarPlay picture adjustments')
    for key,(low,high) in LIMITS.items():
        parser.add_argument('--'+key,type=int,choices=range(low,high+1),metavar=f'{low}..{high}')
    parser.add_argument('--reset',action='store_true')
    parser.add_argument('--interactive',action='store_true')
    args=parser.parse_args(argv)
    settings=PictureSettings()
    changes={key:getattr(args,key) for key in DEFAULTS if getattr(args,key) is not None}
    if args.reset or changes:
        settings.save(dict(DEFAULTS) if args.reset else dict(settings.values,**changes))
    if args.interactive:interactive(settings)
    else:print(json.dumps(settings.values,indent=2))
