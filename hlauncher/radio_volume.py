"""Experimental AVRCP controller on the existing head-unit control channel.

No PCM gain, absolute-volume guesses, repeats or automatic retries.
"""
import time


class RadioVolume:
    def __init__(self, report, clock=time.monotonic):
        self.report, self.clock = report, clock
        self.pending = {}
        self.label = 0
        self.until = 0
        self.failed = False

    def start(self, direction):
        now = self.clock()
        if direction not in ('up', 'down') or self.pending or now < self.until:
            return ()
        operation = 0x41 if direction == 'up' else 0x42
        packets = []
        for state in (0, 0x80):
            label = self.label
            self.label = (label + 1) % 16
            raw = bytes([label << 4, 0x11, 0x0e, 0, 0x48, 0x7c, operation | state, 0])
            self.pending[label] = raw
            packets.append(raw)
        self.until = now + 2
        self.failed = False
        self.report('Sent volume '+direction+' / waiting for radio')
        return tuple(packets)

    def receive(self, raw):
        # Consume responses separately from the target parser: no reply-to-reply.
        if not raw or not raw[0] & 2:
            return False
        sent = self.pending.get(raw[0] >> 4)
        if sent is None:
            return True
        if len(raw) == 3 and raw[0] & 0x0f == 3 and raw[1:] == sent[1:3]:
            self.pending.clear()
            self.failed = True
            self.report('Radio does not support AVRCP control')
        elif (len(raw) == 8 and raw[0] & 0x0f == 2
              and raw[1:3] == sent[1:3] and raw[4:] == sent[4:]
              and raw[3] in (8, 9, 10)):
            self.pending.pop(raw[0] >> 4)
            if raw[3] != 9:
                self.failed = True
                self.report('Radio '+('does not implement' if raw[3] == 8 else 'rejected')+' volume command')
            elif not self.pending and not self.failed:
                self.report('Radio accepted / check its volume display')
        return True

    def tick(self):
        if self.pending and self.clock() >= self.until:
            self.pending.clear()
            if not self.failed:
                self.report('No radio reply / volume change unconfirmed')
