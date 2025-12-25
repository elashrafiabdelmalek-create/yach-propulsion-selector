# Yacht Propulsion Selector (Web App)
# Built by: P.E. Abdelmalek Elashrafy
# Notes:
# - Early-stage sizing + selection tool (not a final naval-architecture design tool).
# - Replace catalogs with real products you source.

import math
import pandas as pd
from dataclasses import dataclass

import streamlit as st

# -----------------------------
# 1) Simple catalogs (EDIT ME)
# -----------------------------
ENGINE_CATALOG = [
    # name, manufacturer, power_kw, rated_rpm, dry_weight_kg, fuel, length_mm, width_mm, height_mm, price_usd_est
    ("D6-480", "Volvo Penta", 353, 3500, 900, "diesel", 1290,  750,  900, 75000),
    ("D8-600", "Volvo Penta", 441, 3000, 1200,"diesel", 1500,  850,  980, 98000),
    ("C12.9",  "Caterpillar", 745, 2300, 1550,"diesel", 1700,  900, 1200, 165000),
    ("QSB6.7", "Cummins",     410, 3000,  650,"diesel", 1200,  700,  900, 65000),
    ("QSC8.3", "Cummins",     600, 2600,  950,"diesel", 1350,  760,  980, 92000),
    ("6LY-440","Yanmar",      324, 3300,  620,"diesel", 1100,  650,  820, 52000),
    ("12V2000","MTU",        1200,2450, 2300,"diesel", 2300, 1100, 1400, 300000),
    ("8V2000", "MTU",         900,2450, 1900,"diesel", 2100, 1050, 1350, 240000),
]

GEARBOX_CATALOG = [
    # name, ratio_options, max_input_kw_est, max_input_rpm, price_usd_est
    ("ZF 45A",  [1.5, 1.75, 2.0, 2.5, 3.0], 600, 3500, 18000),
    ("ZF 63A",  [1.5, 1.75, 2.0, 2.5, 3.0, 3.5], 1000, 3000, 30000),
    ("Twin Disc MGX", [1.5, 2.0, 2.5, 3.0, 3.5, 4.0], 1200, 3500, 35000),
]

# -----------------------------
# 2) Inputs + helper functions
# -----------------------------
@dataclass
class BoatSpecs:
    hull_type: str              # "displacement", "semi-displacement", "planing"
    displacement_tonnes: float  # metric tonnes
    target_speed_kn: float
    shafts: int                 # 1,2,3,4
    fuel: str = "diesel"
    budget_usd: float = 1e9
    max_engine_length_mm: int = 10**9
    max_engine_weight_kg: float = 10**9
    desired_prop_rpm: int | None = None
    power_margin: float = 0.15  # 15% margin

def kw_to_hp(kw: float) -> float:
    return kw * 1.34102209

def hp_to_kw(hp: float) -> float:
    return hp / 1.34102209

def estimate_total_power_kw(spec: BoatSpecs) -> float:
    """
    Early-stage power estimate.

    Displacement hull: Admiralty-style estimate:
      HP ~ (D^(2/3) * V^3) / C

    Planing hull: Crouch-style estimate:
      V = C * sqrt(HP / W)  =>  HP = W * (V/C)^2

    Semi-displacement: blends the two based on speed.
    """
    D = spec.displacement_tonnes
    V = spec.target_speed_kn

    # 1 tonne = 2204.62 lb
    W_lb = D * 2204.62

    hull = spec.hull_type.strip().lower()

    # Default coefficients (tune later using real vessel data)
    admiralty_C = 130.0
    crouch_C = 185.0

    # Displacement estimate (HP)
    hp_disp = ((D ** (2/3)) * (V ** 3)) / admiralty_C

    # Planing estimate (HP)
    hp_plan = W_lb * (V / crouch_C) ** 2

    if hull == "displacement":
        hp = hp_disp
    elif hull == "planing":
        hp = hp_plan
    elif hull in ["semi-displacement", "semi", "semi displacement"]:
        # Blend (12 kn -> mostly displacement, 30 kn -> mostly planing)
        t = min(max((V - 12) / (30 - 12), 0.0), 1.0)
        hp = (1 - t) * hp_disp + t * hp_plan
    else:
        raise ValueError("hull_type must be: displacement, semi-displacement, or planing")

    return hp_to_kw(hp)

def choose_target_prop_rpm(spec: BoatSpecs) -> int:
    """Very rough target prop rpm selection."""
    if spec.desired_prop_rpm is not None:
        return int(spec.desired_prop_rpm)

    D = spec.displacement_tonnes
    hull = spec.hull_type.lower()

    if hull == "displacement":
        return 900 if D < 30 else 750
    if hull in ["semi-displacement", "semi", "semi displacement"]:
        return 1100 if D < 30 else 950
    if hull == "planing":
        return 1300 if D < 30 else 1150
    return 1000

def nearest_ratio(ratio: float, options: list[float]) -> float:
    return min(options, key=lambda x: abs(x - ratio))

def select_propulsion(spec: BoatSpecs) -> tuple[pd.DataFrame, float, float, float, int]:
    total_kw = estimate_total_power_kw(spec)
    total_kw_with_margin = total_kw * (1.0 + spec.power_margin)
    per_shaft_kw_req = total_kw_with_margin / spec.shafts
    target_prop_rpm = choose_target_prop_rpm(spec)

    engines = pd.DataFrame(ENGINE_CATALOG, columns=[
        "engine_model","manufacturer","power_kw","rated_rpm","dry_weight_kg","fuel",
        "length_mm","width_mm","height_mm","price_usd_est"
    ])

    engines_f = engines[
        (engines["fuel"].str.lower() == spec.fuel.lower()) &
        (engines["power_kw"] >= per_shaft_kw_req) &
        (engines["length_mm"] <= spec.max_engine_length_mm) &
        (engines["dry_weight_kg"] <= spec.max_engine_weight_kg) &
        (engines["price_usd_est"] <= spec.budget_usd)
    ].copy()

    if engines_f.empty:
        df = pd.DataFrame([{
            "status": "No engine matches found with current constraints.",
            "total_required_kw_est": round(total_kw, 1),
            "per_shaft_kw_required_with_margin": round(per_shaft_kw_req, 1),
            "hint": "Increase budget/space limits, reduce margin, add more engines to catalog, or lower target speed."
        }])
        return df, total_kw, total_kw_with_margin, per_shaft_kw_req, target_prop_rpm

    rows = []
    for _, e in engines_f.iterrows():
        engine_kw = float(e["power_kw"])
        engine_rpm = float(e["rated_rpm"])
        ideal_ratio = engine_rpm / target_prop_rpm

        for gb_name, ratios, gb_kw_max, gb_rpm_max, gb_price in GEARBOX_CATALOG:
            if engine_kw > gb_kw_max or engine_rpm > gb_rpm_max:
                continue

            chosen_ratio = nearest_ratio(ideal_ratio, ratios)
            achieved_prop_rpm = engine_rpm / chosen_ratio

            power_margin_pct = (engine_kw - per_shaft_kw_req) / per_shaft_kw_req
            ratio_error = abs(chosen_ratio - ideal_ratio) / ideal_ratio
            total_price_est = float(e["price_usd_est"]) + float(gb_price)

            # Simple “goodness” score for MVP ranking
            score = (
                0.55 * min(power_margin_pct, 1.0)  # prefer not massively oversized
                - 0.35 * ratio_error               # lower ratio error better
                - 0.10 * (total_price_est / max(spec.budget_usd, 1.0))
            )

            rows.append({
                "engine": f'{e["manufacturer"]} {e["engine_model"]}',
                "engine_power_kw": round(engine_kw, 1),
                "engine_power_hp": round(kw_to_hp(engine_kw), 0),
                "engine_rated_rpm": int(engine_rpm),
                "engine_weight_kg": int(e["dry_weight_kg"]),
                "engine_length_mm": int(e["length_mm"]),
                "gearbox": gb_name,
                "gear_ratio": chosen_ratio,
                "target_prop_rpm": int(target_prop_rpm),
                "achieved_prop_rpm": int(round(achieved_prop_rpm)),
                "per_shaft_kw_required": round(per_shaft_kw_req, 1),
                "power_margin_pct": round(100 * power_margin_pct, 1),
                "price_est_usd": int(round(total_price_est)),
                "score": float(score),
            })

    out = pd.DataFrame(rows)
    if out.empty:
        df = pd.DataFrame([{
            "status": "Engines matched, but no gearbox matched power/rpm constraints.",
            "hint": "Add gearbox models to catalog or raise gearbox limits."
        }])
        return df, total_kw, total_kw_with_margin, per_shaft_kw_req, target_prop_rpm

    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    return out, total_kw, total_kw_with_margin, per_shaft_kw_req, target_prop_rpm

# -----------------------------
# 3) Streamlit UI (Website)
# -----------------------------
st.set_page_config(
    page_title="Yacht Propulsion Selector",
    page_icon="🛥️",
    layout="wide",
)

# Branding sidebar (your name)
with st.sidebar:
    st.markdown("### 🛥️ Yacht Propulsion Selector")
    st.markdown("**Built by:**  \n**P.E. Abdelmalek Elashrafy**")
    st.divider()
    st.caption("Early-stage sizing + selection. Not a final naval-architecture design tool.")
    st.divider()

st.title("Yacht Propulsion Selector")
st.caption("Enter simple specs → get ranked engine + gearbox matches (MVP selector).")

colA, colB, colC = st.columns(3)

# OPTION 3: hull type dropdown with 3 options
# (This is the cleanest interpretation of your “option 3” request.)
with colA:
    hull_type = st.selectbox(
        "Hull type (Option 3)",
        options=["displacement", "semi-displacement", "planing"],
        index=1
    )
    displacement_tonnes = st.number_input("Displacement (tonnes)", min_value=1.0, value=25.0, step=1.0)
    target_speed_kn = st.number_input("Target speed (knots)", min_value=1.0, value=15.0, step=0.5)

with colB:
    shafts = st.selectbox("Number of shafts", options=[1, 2, 3, 4], index=1)
    fuel = st.selectbox("Fuel", options=["diesel"], index=0)
    power_margin = st.slider("Power margin", min_value=0.0, max_value=0.40, value=0.15, step=0.01)

with colC:
    budget_usd = st.number_input("Max engine price per shaft (USD)", min_value=1000.0, value=250000.0, step=5000.0)
    max_engine_length_mm = st.number_input("Max engine length (mm)", min_value=500, value=1800, step=50)
    max_engine_weight_kg = st.number_input("Max engine dry weight (kg)", min_value=100, value=1800, step=50)

advanced = st.expander("Advanced options")
with advanced:
    desired_prop_rpm = st.number_input("Desired prop RPM (0 = auto)", min_value=0, value=0, step=50)
    desired_prop_rpm = None if desired_prop_rpm == 0 else int(desired_prop_rpm)

run = st.button("Run selection", type="primary")

if run:
    spec = BoatSpecs(
        hull_type=hull_type,
        displacement_tonnes=float(displacement_tonnes),
        target_speed_kn=float(target_speed_kn),
        shafts=int(shafts),
        fuel=fuel,
        budget_usd=float(budget_usd),
        max_engine_length_mm=int(max_engine_length_mm),
        max_engine_weight_kg=float(max_engine_weight_kg),
        desired_prop_rpm=desired_prop_rpm,
        power_margin=float(power_margin),
    )

    results, total_kw, total_kw_with_margin, per_shaft_kw_req, target_prop_rpm = select_propulsion(spec)

    st.subheader("Inputs")
    st.json({
        "hull_type": spec.hull_type,
        "displacement_tonnes": spec.displacement_tonnes,
        "target_speed_kn": spec.target_speed_kn,
        "shafts": spec.shafts,
        "fuel": spec.fuel,
        "budget_usd_per_shaft_engine_only": spec.budget_usd,
        "max_engine_length_mm": spec.max_engine_length_mm,
        "max_engine_weight_kg": spec.max_engine_weight_kg,
        "desired_prop_rpm": spec.desired_prop_rpm,
        "power_margin": spec.power_margin,
    })

    st.subheader("Power estimate (quick)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total required (no margin)", f"{total_kw:.1f} kW")
    c2.metric("Total required (with margin)", f"{total_kw_with_margin:.1f} kW")
    c3.metric("Per shaft required (with margin)", f"{per_shaft_kw_req:.1f} kW")
    c4.metric("Target prop RPM", f"{target_prop_rpm} rpm")

    st.subheader("Top matches")
    st.dataframe(results.head(20), use_container_width=True)

    # Download results
    csv = results.to_csv(index=False).encode("utf-8")
    st.download_button("Download results as CSV", data=csv, file_name="propulsion_matches.csv", mime="text/csv")

# Footer credit (visible branding)
st.divider()
st.caption("© Built by P.E. Abdelmalek Elashrafy — Yacht Propulsion Selector (MVP)")
