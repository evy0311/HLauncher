"""Projection controls shared by physical keys and the hardware test page."""
import time

LABELS = {'previous':'Previous', 'play_pause':'Play / pause', 'next':'Next',
          'answer':'Answer', 'hang_up':'End call', 'voice_assistant':'Voice'}
CARPLAY = {'previous':'prev', 'next':'next', 'play_pause':'playOrPause',
           'play':'play', 'pause':'pause', 'stop':'pause', 'answer':'acceptPhone',
           'hang_up':'rejectPhone', 'voice_assistant':'siri'}
ANDROID = {'previous':88, 'next':87, 'play_pause':85, 'play':126, 'pause':127,
           'stop':86, 'answer':5, 'hang_up':6, 'voice_assistant':84}
BUTTONS = frozenset(CARPLAY) | {'dial', 'redial'}
ACTIONS = frozenset(('down', 'up', 'repeat', 'trigger', 'activate', 'deactivate'))

class ButtonGate:
    """One action per press; bound duplicates from overlapping input sources."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = {}
        self.held = set()
        self.epochs = {}

    def command(self, message, mapping):
        name, action = message.get('button'), message.get('action')
        key = (message.get('source', ''), name)
        source, epoch = key[0], message.get('input_epoch', 0)
        if self.epochs.get(source) != epoch:
            self.held = {held for held in self.held if held[0] != source}
            self.epochs[source] = epoch
        if action in ('up', 'deactivate'):
            self.held.discard(key)
            return None
        if name not in mapping or action not in ('down','trigger','activate'):
            return None
        if key in self.held:
            return None
        if action in ('down', 'activate'):
            self.held.add(key)
        now = self.clock()
        if now-self.last.get(name, -100) < .18:
            return None
        self.last[name] = now
        return mapping[name]
