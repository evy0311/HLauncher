"""Local vehicle identity catalog; currently selects Home artwork only."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class VehicleModel:
    name: str
    body: str
    icon: str = 'vehicle'


MODELS = {
    'FB2': VehicleModel('Civic Sedan', 'sedan'),
    'FB4': VehicleModel('Civic Hybrid Sedan', 'sedan'),
    'FB5': VehicleModel('Civic Natural-gas Sedan', 'sedan'),
    'FB6': VehicleModel('Civic Si Sedan', 'sedan'),
    'FG3': VehicleModel('Civic Coupe', 'coupe', 'vehicle-coupe'),
    'FG4': VehicleModel('Civic Si Coupe', 'coupe', 'vehicle-coupe'),
    'RM3': VehicleModel('CR-V FWD', 'suv', 'vehicle-crv'),
    'RM4': VehicleModel('CR-V AWD', 'suv', 'vehicle-crv'),
    'RU5': VehicleModel('HR-V FWD', 'suv', 'vehicle-hrv'),
    'RU6': VehicleModel('HR-V AWD', 'suv', 'vehicle-hrv'),
    'GE8': VehicleModel('Fit (2013 / GE8)', 'hatchback', 'vehicle-fit-ge8'),
    'GK5': VehicleModel('Fit (2015 / GK5)', 'hatchback', 'vehicle-fit-gk5'),
}
# Include Honda MPV manufacturers for CR-V and HR-V, as well as passenger cars.
# Honda's Part 565 filing: https://vpic.nhtsa.dot.gov/mid/home/displayfile/69a24a5d-780c-4562-b28c-5eaf08531280
HONDA_WMIS = {'1HG', '19X', '2HG', '3HG', 'JHM', '5J6', '2HK', '3CZ', 'JHL'}


def normalize_vin(vin):
    if not isinstance(vin, str):
        return None
    vin = vin.strip(' \t\r\n\0').upper()
    if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin):
        return None
    return vin


def model_from_vin(vin):
    vin = normalize_vin(vin)
    if vin is None or vin[:3] not in HONDA_WMIS:
        return None
    # Honda's model descriptor starts at VIN position 4.
    code = vin[3:6]
    return code if code in MODELS else None


def selected_model(selection, vin):
    return selection if selection in MODELS else model_from_vin(vin)


def icon_for_model(code):
    return MODELS[code].icon if code in MODELS else 'vehicle'
