"""Impact estimates: what congestion costs right now, and what a just-in-time arrival would save.

These are transparent, order-of-magnitude estimates, not measurements. Every
assumption is returned alongside the numbers so the UI can show its working,
and each one can be overridden through environment variables.

Model
-----
* Idle ship time: ships waiting × average wait × a typical daily operating cost.
* Just-in-time (JIT) arrival for one inbound ship that is `JIT_HOURS_OUT` hours
  away at its service speed. Instead of sailing at full speed and then waiting
  at anchor for the current average wait, it slows down to arrive when the wait
  would have ended. Main-engine fuel per day scales with roughly the cube of
  speed (the standard propeller law), so fuel per voyage scales with speed².
  The saving also counts the auxiliary fuel no longer burned at anchor.
"""

import os


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


SERVICE_SPEED_KN = _env_float("IMPACT_SERVICE_SPEED_KN", 18.0)
MIN_SPEED_KN = _env_float("IMPACT_MIN_SPEED_KN", 10.0)  # below this, engines run inefficiently
FUEL_T_PER_DAY_AT_SERVICE = _env_float("IMPACT_FUEL_T_PER_DAY", 60.0)  # mid-size container ship
ANCHOR_FUEL_T_PER_DAY = _env_float("IMPACT_ANCHOR_FUEL_T_PER_DAY", 3.0)  # auxiliary engines at anchor
FUEL_PRICE_USD_PER_T = _env_float("IMPACT_FUEL_PRICE_USD_PER_T", 600.0)  # very-low-sulphur fuel oil
CO2_T_PER_T_FUEL = _env_float("IMPACT_CO2_FACTOR", 3.114)  # IMO emission factor for heavy fuel oil
SHIP_DAILY_COST_USD = _env_float("IMPACT_SHIP_DAILY_COST_USD", 30000.0)  # charter + operating cost
JIT_HOURS_OUT = _env_float("IMPACT_JIT_HOURS_OUT", 24.0)


def _voyage_fuel_t(distance_nm: float, speed_kn: float) -> float:
    hours = distance_nm / speed_kn
    daily = FUEL_T_PER_DAY_AT_SERVICE * (speed_kn / SERVICE_SPEED_KN) ** 3
    return daily * hours / 24


def estimate_impact(snapshot: dict) -> dict:
    queue = int(snapshot.get("vessel_queue_length", 0))
    wait_h = float(snapshot.get("avg_waiting_time_hours", 0.0))

    idle_ship_hours = queue * wait_h
    idle_cost_usd = idle_ship_hours / 24 * SHIP_DAILY_COST_USD

    distance_nm = SERVICE_SPEED_KN * JIT_HOURS_OUT
    rushed_fuel = _voyage_fuel_t(distance_nm, SERVICE_SPEED_KN) + wait_h / 24 * ANCHOR_FUEL_T_PER_DAY

    jit_speed = distance_nm / (JIT_HOURS_OUT + wait_h) if wait_h > 0 else SERVICE_SPEED_KN
    jit_speed = max(MIN_SPEED_KN, jit_speed)
    # If the speed floor stops it absorbing the whole wait, it still anchors for the remainder.
    remaining_wait_h = max(0.0, JIT_HOURS_OUT + wait_h - distance_nm / jit_speed)
    jit_fuel = _voyage_fuel_t(distance_nm, jit_speed) + remaining_wait_h / 24 * ANCHOR_FUEL_T_PER_DAY

    fuel_saved = max(0.0, rushed_fuel - jit_fuel)

    return {
        "idle": {
            "ships_waiting": queue,
            "idle_ship_hours": round(idle_ship_hours, 1),
            "idle_cost_usd": round(idle_cost_usd),
        },
        "jit_per_ship": {
            "service_speed_kn": SERVICE_SPEED_KN,
            "recommended_speed_kn": round(jit_speed, 1),
            "wait_absorbed_hours": round(wait_h - remaining_wait_h, 1),
            "fuel_saved_t": round(fuel_saved, 1),
            "co2_saved_t": round(fuel_saved * CO2_T_PER_T_FUEL, 1),
            "cost_saved_usd": round(fuel_saved * FUEL_PRICE_USD_PER_T),
        },
        "assumptions": {
            "ship_hours_out": JIT_HOURS_OUT,
            "service_speed_kn": SERVICE_SPEED_KN,
            "min_speed_kn": MIN_SPEED_KN,
            "fuel_t_per_day_at_service_speed": FUEL_T_PER_DAY_AT_SERVICE,
            "anchor_fuel_t_per_day": ANCHOR_FUEL_T_PER_DAY,
            "fuel_price_usd_per_t": FUEL_PRICE_USD_PER_T,
            "co2_t_per_t_fuel": CO2_T_PER_T_FUEL,
            "ship_daily_cost_usd": SHIP_DAILY_COST_USD,
        },
        "is_estimate": True,
    }
