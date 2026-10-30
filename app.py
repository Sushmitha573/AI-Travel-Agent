"""AI Travel Agent - Streamlit user interface.

Run with:  python -m streamlit run app.py
"""

import re
from datetime import date
from typing import Any, Dict

import pandas as pd
import streamlit as st

import config
from agents.travel_agent import MissingAPIKeyError, TravelAgent, TravelAgentError
from utils.helpers import describe_when, format_inr, plan_to_markdown, validate_inputs

st.set_page_config(page_title="AI Travel Agent", page_icon="✈️", layout="wide")

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .hero {
        background: linear-gradient(120deg, #0E7C86 0%, #1B9AAA 55%, #F4A259 100%);
        padding: 1.6rem 1.8rem; border-radius: 16px; color: #ffffff; margin-bottom: 1rem;
    }
    .hero h1 { color: #ffffff; margin: 0; font-size: 2rem; }
    .hero p { margin: .3rem 0 0 0; font-size: 1.05rem; opacity: .95; }
    .step-card {
        background: #ffffff; border: 1px solid #cfe6e9; border-radius: 12px;
        padding: 1rem; height: 100%; color: #12313A;
    }
    .slot-title { font-weight: 700; color: #0E7C86; margin-bottom: .2rem; }
    .cost-chip {
        display: inline-block; background: #FFF1E0; color: #8a4b00; border-radius: 999px;
        padding: .1rem .7rem; font-size: .85rem; font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>✈️ AI Travel Agent</h1>
      <p>Personalised day-by-day itineraries with budget checking and a weather forecast.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar: user input
# ---------------------------------------------------------------------------
def read_sidebar() -> Dict[str, Any]:
    """Draw the sidebar widgets and return their values."""
    st.sidebar.header("🧳 Plan your trip")
    origin = st.sidebar.text_input("📍 Starting location", placeholder="e.g. Hyderabad")
    destination = st.sidebar.text_input("🏖️ Destination", placeholder="e.g. Goa")

    col_a, col_b = st.sidebar.columns(2)
    days = col_a.number_input("📅 Days", min_value=1, max_value=config.MAX_DAYS, value=4, step=1)
    travelers = col_b.number_input("👥 Travelers", min_value=1, max_value=config.MAX_TRAVELERS, value=2, step=1)

    budget = st.sidebar.number_input(
        "💰 Total budget (₹, whole group)", min_value=0, value=30000, step=1000
    )
    travel_type = st.sidebar.selectbox("🧑‍🤝‍🧑 Travel type", config.TRAVEL_TYPES, index=3)
    travel_style = st.sidebar.selectbox("🎯 Travel style", config.TRAVEL_STYLES)

    exact_date = st.sidebar.checkbox("I know my exact start date")
    start_date = None
    if exact_date:
        start_date = st.sidebar.date_input("🗓️ Start date", value=date.today(), min_value=date.today())
        month = start_date.strftime("%B")
    else:
        month = st.sidebar.selectbox("🗓️ Travel month", config.MONTHS, index=date.today().month - 1)

    clicked = st.sidebar.button("🚀 Generate itinerary", type="primary")

    st.sidebar.divider()
    if config.api_key_is_placeholder(config.get_api_key()):
        st.sidebar.warning("Gemini API key not configured. See README.md (step: create .env).")
    else:
        st.sidebar.success("Gemini API key found.")
    st.sidebar.caption("Prices are AI estimates, not live quotes. Weather uses Open-Meteo (no key needed).")

    return {
        "clicked": clicked,
        "inputs": {
            "origin": origin,
            "destination": destination,
            "days": int(days),
            "travelers": int(travelers),
            "budget": int(budget),
            "travel_type": travel_type,
            "travel_style": travel_style,
            "start_date": start_date,
            "month": month,
        },
    }


# ---------------------------------------------------------------------------
# Result display
# ---------------------------------------------------------------------------
def render_slot(label: str, icon: str, slot: Dict[str, Any]) -> None:
    st.markdown(f"<div class='slot-title'>{icon} {label}</div>", unsafe_allow_html=True)
    st.write(slot["activity"])
    if slot["place"]:
        st.caption(f"📍 {slot['place']}")
    st.markdown(f"<span class='cost-chip'>≈ {format_inr(slot['cost'])}</span>", unsafe_allow_html=True)


def render_result(inputs: Dict[str, Any], result: Dict[str, Any]) -> None:
    plan, totals = result["plan"], result["totals"]
    total, budget = totals["grand_total"], result["budget"]

    st.subheader(f"🗺️ {plan['trip_title']}")
    if plan["overview"]:
        st.write(plan["overview"])

    # --- Trip summary ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estimated total", format_inr(total))
    c2.metric("Your budget", format_inr(budget))
    if result["within_budget"]:
        c3.metric("Remaining", format_inr(budget - total))
    else:
        c3.metric("Over budget by", format_inr(total - budget), delta="over", delta_color="inverse")
    c4.metric("Per person (approx.)", format_inr(total / inputs["travelers"]))

    st.caption(
        f"{inputs['origin']} → {inputs['destination']} · {inputs['days']} day(s) · "
        f"{inputs['travelers']} traveler(s), {inputs['travel_type']} · {inputs['travel_style']} · "
        f"{describe_when(inputs)}"
    )

    if result["within_budget"]:
        st.success("✅ The estimated cost fits within your budget.")
    for warning in result["warnings"]:
        st.warning("⚠️ " + warning)
    if plan["budget_note"]:
        st.info("💡 " + plan["budget_note"])

    st.download_button(
        "📥 Download itinerary (Markdown)",
        data=plan_to_markdown(inputs, result),
        file_name=re.sub(r"[^A-Za-z0-9_-]+", "_", f"itinerary_{inputs['destination']}") + ".md",
        mime="text/markdown",
    )

    tab_plan, tab_budget, tab_weather, tab_tips, tab_agent = st.tabs(
        ["🗓️ Itinerary", "💰 Budget", "🌦️ Weather", "🛡️ Tips & Safety", "🤖 Agent steps"]
    )

    with tab_plan:
        transport = plan["intercity_transport"]
        st.markdown(
            f"**🚆 Getting there and back:** {transport['suggestion']} "
            f"<span class='cost-chip'>≈ {format_inr(transport['cost'])}</span>",
            unsafe_allow_html=True,
        )
        for day in plan["days"]:
            with st.expander(
                f"Day {day['day']}: {day['title']}  —  ≈ {format_inr(day['day_total'])}",
                expanded=(day["day"] == 1),
            ):
                col_m, col_a, col_e = st.columns(3)
                with col_m:
                    render_slot("Morning", "🌅", day["morning"])
                with col_a:
                    render_slot("Afternoon", "☀️", day["afternoon"])
                with col_e:
                    render_slot("Evening", "🌙", day["evening"])
                st.divider()
                if day["food_recommendations"]:
                    st.markdown("**🍽️ Food to try:** " + ", ".join(day["food_recommendations"]))
                st.markdown(
                    f"**🚕 Transport:** {day['transport']['suggestion']} (≈ {format_inr(day['transport']['cost'])})"
                )
                st.markdown(
                    f"**🏨 Stay:** {day['accommodation']['suggestion']} (≈ {format_inr(day['accommodation']['cost'])})"
                )
                st.markdown(f"**🥘 Food cost:** ≈ {format_inr(day['food_cost'])}")

    with tab_budget:
        left, right = st.columns(2)
        category_df = pd.DataFrame(
            {"Category": list(totals["by_category"].keys()), "Amount (₹)": list(totals["by_category"].values())}
        )
        with left:
            st.markdown("**Budget breakdown (estimates)**")
            table_df = category_df.copy()
            table_df["Amount (₹)"] = table_df["Amount (₹)"].map(format_inr)
            st.dataframe(table_df, hide_index=True)
            st.markdown(f"**Total: {format_inr(total)}**")
        with right:
            st.markdown("**Spending by category**")
            st.bar_chart(category_df.set_index("Category"))

        st.markdown("**Day-wise cost (excluding round-trip travel and miscellaneous)**")
        day_df = pd.DataFrame(
            [{"Day": f"Day {d['day']}", "Estimated cost": format_inr(d["day_total"])} for d in plan["days"]]
        )
        st.dataframe(day_df, hide_index=True)

    with tab_weather:
        weather = result["weather"]
        if not weather:
            st.info("Weather was not available (offline or location not found). The plan was made without it.")
        else:
            st.markdown(f"**Forecast for {weather['place']}**")
            (st.success if weather["is_for_trip_dates"] else st.warning)(weather["note"])
            weather_df = pd.DataFrame(
                [
                    {
                        "Date": row["date"],
                        "Conditions": row["summary"],
                        "Min °C": row["temp_min"],
                        "Max °C": row["temp_max"],
                        "Rain chance %": row["rain_chance"],
                    }
                    for row in weather["days"]
                ]
            )
            st.dataframe(weather_df, hide_index=True)

    with tab_tips:
        col_t, col_s = st.columns(2)
        with col_t:
            st.markdown("**🧭 Travel tips**")
            for tip in plan["tips"] or ["No tips were returned."]:
                st.markdown(f"- {tip}")
        with col_s:
            st.markdown("**🛡️ Safety suggestions**")
            for tip in plan["safety"] or ["No safety notes were returned."]:
                st.markdown(f"- {tip}")

    with tab_agent:
        st.caption(
            "This is a fixed planning workflow that calls Gemini (and Open-Meteo for weather). "
            "It is not a fully autonomous agent."
        )
        icons = {"done": "✅", "over": "⚠️", "skipped": "⏭️", "running": "⏳"}
        for step in result["steps"]:
            detail = f" — {step['detail']}" if step["detail"] else ""
            st.markdown(f"{icons.get(step['status'], '•')} **{step['step']}**{detail}")
        st.markdown(f"Revision rounds used: **{result['revisions']}** (max {config.MAX_REVISIONS})")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def show_intro() -> None:
    st.markdown("### How it works")
    cols = st.columns(4)
    cards = [
        ("1️⃣ Tell us your trip", "Fill in the form in the sidebar."),
        ("2️⃣ AI plans it", "Gemini writes a day-by-day itinerary with cost estimates."),
        ("3️⃣ Budget check", "We add up the costs and ask the AI to revise if you are over budget."),
        ("4️⃣ Download", "Review the plan, charts and weather, then save it as Markdown."),
    ]
    for col, (title, text) in zip(cols, cards):
        col.markdown(f"<div class='step-card'><b>{title}</b><br>{text}</div>", unsafe_allow_html=True)
    st.caption("⚠️ All prices are AI-generated estimates, not live hotel or flight prices. No bookings are made.")


def main() -> None:
    sidebar = read_sidebar()
    inputs = sidebar["inputs"]

    if sidebar["clicked"]:
        problems = validate_inputs(inputs)
        if problems:
            for problem in problems:
                st.error("❌ " + problem)
        else:
            try:
                agent = TravelAgent()
                with st.status("🤖 Travel agent is working...", expanded=True) as status:
                    result = agent.run(inputs, on_step=lambda message: st.write("• " + message))
                    status.update(label="✅ Itinerary ready!", state="complete", expanded=False)
                st.session_state["result"] = result
                st.session_state["inputs"] = dict(inputs)
            except MissingAPIKeyError as exc:
                st.error("🔑 " + str(exc))
            except TravelAgentError as exc:
                st.error("❌ " + str(exc))
            except Exception as exc:  # last safety net: never show a raw crash
                st.error(f"Something unexpected went wrong ({type(exc).__name__}). Please try again.")
                with st.expander("Technical details"):
                    st.code(str(exc))

    if "result" in st.session_state:
        render_result(st.session_state["inputs"], st.session_state["result"])
    elif not sidebar["clicked"]:
        show_intro()


main()
