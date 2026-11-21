"""Display preferences and factory service information shared by Vehicle and Settings."""

from .protocol.vehicle_signals import BY_ID, UNITS, label


MINDER_IDS = dict(zip('AB0123456789', (124, 125, *range(114, 124))))
# Honda 2014 Civic Sedan Owner’s Manual, page 359 (i-MID).
SERVICE_ITEMS = {
    'A': ('Engine oil', 'Replace the engine oil'),
    'B': ('Oil, filter and inspections',
          'Replace oil and filter. Inspect the brakes, steering, suspension, driveshaft boots, '
          'brake hoses and lines, fluid levels and condition, exhaust, and fuel lines and connections. '
          'Check parking brake adjustment and the tire repair kit expiration if equipped.'),
    '1': ('Tire rotation', 'Rotate the tires'),
    '2': ('Air filters and drive belt', 'Replace the engine air and cabin filters. Inspect the drive belt.'),
    '3': ('Transmission fluid', 'Replace the transmission fluid'),
    '4': ('Spark plugs and valve clearance', 'Replace the spark plugs and inspect valve clearance'),
    '5': ('Engine coolant', 'Replace the engine coolant'),
}
DIAGNOSTIC_FIELDS = {'bc-dtc': 'B-CAN trouble codes', 'fc-dtc': 'F-CAN trouble codes',
                     'freeze': 'F-CAN freeze frames'}
DIAGNOSTIC_KEYS = dict(enumerate(DIAGNOSTIC_FIELDS, 1))
EXTRA_LABELS = {
    'vin': 'Vehicle VIN', 'head-unit': 'Head-unit ID', 'latitude': 'Latitude', 'longitude': 'Longitude',
    'brake': 'Parking brake (radio)', '42': 'Engine oil life', '69': 'Minder display status',
    '70': 'Minder interval value', '71': 'Minder date unit code', '72': 'Cluster oil-life code',
    '73': 'Minder type code', '74': 'Minder interval unit code', '75': 'Odometer',
    '39': 'Charging system', '43': 'Engine oil pressure', '46': 'Check engine', '2': 'Anti-lock brakes',
    '47': 'Electric power steering', '109': 'Airbag system', '159': 'Brake system',
    '162': 'Stability control', '168': 'Brake fluid', '22': 'Indirect tire pressure warning',
    '130': 'Puncture warning', '139': 'TPMS system fault', '138': 'Severe low pressure',
    '142': 'Trip A distance', '144': 'Estimated range', '132': 'Ignition cycles',
    '1002': 'Intake temperature', '1003': 'VTEC status',
    '126': 'Front left pressure', '127': 'Front right pressure',
    '128': 'Rear left pressure', '129': 'Rear right pressure',
    '134': 'Front left warning', '135': 'Front right warning',
    '136': 'Rear left warning', '137': 'Rear right warning',
    **{str(ident): f'Service code {code}' for code, ident in MINDER_IDS.items()},
    **DIAGNOSTIC_FIELDS,
}

_GROUPS = (
    ('maintenance', 'Maintenance Minder', (42, 72, 69, 70, 74, 71, 73, *MINDER_IDS.values(),
                                            10, 11, 1004, 1005, 1006, 1007, 1008, *range(1010, 1022))),
    ('tires', 'Tires and TPMS', (126, 127, 128, 129, 134, 135, 136, 137, 22, 130, 138, 139)),
    ('warnings', 'Warning indicators', (46, 39, 43, 168, 2, 162, 159, 47, 109, 104, 107, 41, 3, 7,
                                         14, 15, 20, 23, 24, 25, 48, 49, 50, 67, 78, 79, 94, 110,
                                         111, 112, 131)),
    ('diagnostics', 'Fault codes and freeze frames', tuple(DIAGNOSTIC_FIELDS)),
    ('mileage', 'Mileage, fuel and trips', (75, 61, 144, 145, 142, 143, 141, 133, *range(51, 61),
                                           *range(26, 38))),
    ('powertrain', 'Engine and drivetrain', (40, 44, 12, 21, 62, 63, 64, 140, 152, 167, 4, 38, 45,
                                             *range(95, 102), 1001, 1002, 1003)),
    ('identity', 'Identity and environment', ('vin', 'head-unit', 132, 65, 66, 77, 'latitude', 'longitude')),
)
GROUPS = {key: (title, tuple(map(str, fields))) for key, title, fields in _GROUPS}
used = {field for _, fields in GROUPS.values() for field in fields}
GROUPS['other'] = ('Other vehicle readings', ('brake', *(str(i) for i in BY_ID if str(i) not in used)))
FIELD_GROUP = {field: key for key, (_, fields) in GROUPS.items() for field in fields}


def field_label(key):
    if key in EXTRA_LABELS:
        return EXTRA_LABELS[key]
    return label(BY_ID[int(key)])


def visible(field, hidden):
    return field not in hidden and FIELD_GROUP[field] not in hidden


def unit(field):
    if field in ('latitude', 'longitude'):
        return '°'
    return UNITS.get(int(field), '') if field.isdecimal() else ''


def minder_oil_life(code):
    """Percent from the original Connect app's cluster-code conversion (0xE1EC)."""
    if type(code) is not int:
        return None
    if 1 <= code <= 9:
        return 110 - 10 * code
    if 10 <= code <= 13:
        return 65 - 5 * code
    return 0 if code == 14 else None
