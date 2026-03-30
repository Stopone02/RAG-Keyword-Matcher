# Maps brand-specific feature display names to standardized snake_case keys.
# Used for RAG pipeline normalization. Extend as needed.

ALIAS_MAP: dict[str, str] = {
    # Powertrain
    "Horsepower": "max_power_hp",
    "Torque": "max_torque_lbft",
    "Engine Displacement": "engine_displacement_l",
    "Cylinders": "engine_cylinders",
    # Fuel economy
    "Fuel Economy City": "fuel_economy_city_mpg",
    "Fuel Economy Highway": "fuel_economy_hwy_mpg",
    "Fuel Economy Combined": "fuel_economy_combined_mpg",
    # Dimensions
    "Seating Capacity": "seating_capacity",
    "Cargo Volume": "cargo_volume_cuft",
    "Wheelbase": "wheelbase_in",
    "Overall Length": "length_in",
    "Overall Width": "width_in",
    "Overall Height": "height_in",
    # Drivetrain
    "Drive Type": "drive_type",
    "Transmission": "transmission",
}


def map_feature_name(name: str, brand: str = "") -> str:
    """Return a standardized key for the given feature name.
    Falls back to the original name if no alias is defined.
    """
    return ALIAS_MAP.get(name, name)
