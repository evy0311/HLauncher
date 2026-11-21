"""Local vehicle identity catalog; currently selects Home artwork only."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class VehicleModel:
    name: str
    body: str


MODELS = {
    'FB2': VehicleModel('Civic Sedan', 'sedan'),
    'FB4': VehicleModel('Civic Hybrid Sedan', 'sedan'),
    'FB5': VehicleModel('Civic Natural-gas Sedan', 'sedan'),
    'FB6': VehicleModel('Civic Si Sedan', 'sedan'),
    'FG3': VehicleModel('Civic Coupe', 'coupe'),
    'FG4': VehicleModel('Civic Si Coupe', 'coupe'),
}
HONDA_PASSENGER_WMIS = {'1HG', '19X', '2HG', '3HG', 'JHM'}


def normalize_vin(vin):
    if not isinstance(vin, str):
        return None
    vin = vin.strip(' \t\r\n\0').upper()
    if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin):
        return None
    return vin


def model_from_vin(vin):
    vin = normalize_vin(vin)
    if vin is None or vin[:3] not in HONDA_PASSENGER_WMIS:
        return None
    # Honda's model descriptor starts at VIN position 4.
    code = vin[3:6]
    return code if code in MODELS else None


def selected_model(selection, vin):
    return selection if selection in MODELS else model_from_vin(vin)


def icon_for_model(code):
    return 'vehicle-coupe' if code in MODELS and MODELS[code].body == 'coupe' else 'vehicle'
