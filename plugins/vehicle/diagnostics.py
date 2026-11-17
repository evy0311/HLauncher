"""Decode the known code fields and retain every record for inspection."""

from hlauncher.protocol.vehicle_signals import MESSAGES

# Five-byte F-CAN layouts whose first two fields are the DTC bytes.
FCAN_DTC = {
    0x400: 'Engine', 0x403: 'Transmission', 0x406: 'Stability control',
    0x409: 'AWD', 0x40a: 'Tire pressure', 0x421: 'Power steering',
    0x427: 'Parking brake', 0x52a: 'Gateway', 0x537: 'Adaptive cruise',
    0x53b: 'RTC', 0x53d: 'Drive motor', 0x53e: 'Battery', 0x543: 'Lane keeping',
    0x551: 'Power steering', 0x555: 'Airbags', 0x562: 'Drive motor',
    0x590: 'Stability control', 0x591: 'Powertrain 1', 0x592: 'Powertrain 2',
    0x595: 'Brake control', 0x597: 'SS30', 0x598: 'CAPA', 0x59d: 'AFP',
}


def sae_code(raw):
    return 'PCBU'[raw[0] >> 6] + f'{raw[0] & 0x3f:02X}{raw[1]:02X}'


def fault_codes(kind, records):
    codes = {}
    for mid, hex_data in records:
        raw = bytes.fromhex(hex_data)
        if kind == 1 and len(raw) == 8 and raw[0] == 0x53 and raw[1]:
            # SID 0x53 reports two-byte body codes, with up to three per record.
            module = MESSAGES.get(mid, {}).get('name', '').removeprefix('DIAG_')
            if not MESSAGES.get(mid, {}).get('name', '').startswith('DIAG_'):
                continue
            for start in range(2, 2 + 2 * min(3, raw[1]), 2):
                word = raw[start:start+2]
                if any(word):
                    codes[(mid, word)] = ('-'.join(f'{b:02X}' for b in word), module.replace('_', ' '))
        elif kind == 2 and len(raw) == 5 and mid in FCAN_DTC:
            word = raw[:3] if mid == 0x555 else raw[:2]
            if any(word):
                code = (sae_code(word) if mid in (0x400, 0x403) else word.hex(' ').upper())
                codes[(mid, word)] = (code, FCAN_DTC[mid])
    return list(codes.values())


def record_title(kind, mid, raw):
    if kind == 3 and mid in (0x40c, 0x40f) and len(raw) == 16:
        header = int(raw[:2], 16)
        name = 'Engine' if mid == 0x40c else 'Transmission'
        return f'{name} · level {header >> 6} · part {header & 15}'
    if mid in FCAN_DTC and kind == 2:
        return FCAN_DTC[mid]
    return MESSAGES.get(mid, {}).get('name', 'Vehicle record').replace('_', ' ')
