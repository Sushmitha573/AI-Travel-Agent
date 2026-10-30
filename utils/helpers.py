"""Small helper functions: validation, number handling and Markdown export."""

import re
from datetime import date
from typing import Any, Dict, List, Optional

import config

# Letters (any language), digits, spaces and a few punctuation marks only.
_PLACE_PATTERN = re.compile(r"^[\w\s,.'()\-]+$", re.UNICODE)


# ---------------------------------------------------------------------------
# Number helpers
# ---------------------------------------------------------------------------
def to_number(value: Any) -> float:
    """Convert anything the AI returns (12000, "12,000", "₹12000") to a float.

    Returns 0.0 if the value cannot be understood or is negative.
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value)
        try:
            return max(float(cleaned), 0.0) if cleaned else 0.0
        except ValueError:
            return 0.0
    return 0.0


def format_inr(amount: float) -> str:
    """Format a number with Indian digit grouping, e.g. 1234567 -> ₹12,34,567."""
    amount = int(round(amount))
    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def clean_text(value: Optional[str]) -> str:
    """Trim and collapse whitespace."""
    return re.sub(r"\s+", " ", (value or "")).strip()


def validate_inputs(inputs: Dict[str, Any]) -> List[str]:
    """Check the user's form values. Returns a list of error messages (empty = OK)."""
    errors: List[str] = []

    for key, label in (("origin", "Starting location"), ("destination", "Destination")):
        value = clean_text(inputs.get(key))
        if not value:
            errors.append(f"{label} is required.")
        elif len(value) < 2:
            errors.append(f"{label} is too short.")
        elif len(value) > 80:
            errors.append(f"{label} is too long (maximum 80 characters).")
        elif not _PLACE_PATTERN.match(value):
            errors.append(
                f"{label} contains unsupported characters. "
                "Use letters, numbers, spaces, commas and hyphens only."
            )

    origin = clean_text(inputs.get("origin")).lower()
    destination = clean_text(inputs.get("destination")).lower()
    if origin and destination and origin == destination:
        errors.append("Starting location and destination must be different.")

    days = inputs.get("days")
    if not isinstance(days, int) or not (1 <= days <= config.MAX_DAYS):
        errors.append(f"Number of days must be between 1 and {config.MAX_DAYS}.")

    budget = inputs.get("budget")
    if not isinstance(budget, (int, float)) or budget < config.MIN_BUDGET_INR:
        errors.append(f"Budget must be at least {format_inr(config.MIN_BUDGET_INR)}.")

    travelers = inputs.get("travelers")
    if not isinstance(travelers, int) or not (1 <= travelers <= config.MAX_TRAVELERS):
        errors.append(f"Number of travelers must be between 1 and {config.MAX_TRAVELERS}.")
    else:
        travel_type = inputs.get("travel_type")
        if travel_type == "Solo" and travelers != 1:
            errors.append("A Solo trip must have exactly 1 traveler.")
        elif travel_type == "Couple" and travelers != 2:
            errors.append("A Couple trip must have exactly 2 travelers.")
        elif travel_type in ("Family", "Friends") and travelers < 2:
            errors.append(f"A {travel_type} trip needs at least 2 travelers.")

    if inputs.get("travel_type") not in config.TRAVEL_TYPES:
        errors.append("Please choose a valid travel type.")
    if inputs.get("travel_style") not in config.TRAVEL_STYLES:
        errors.append("Please choose a valid travel style.")

    start_date = inputs.get("start_date")
    if start_date is not None and start_date < date.today():
        errors.append("The start date cannot be in the past.")

    return errors


def describe_when(inputs: Dict[str, Any]) -> str:
    """Human-readable travel time ('12 Dec 2026' or 'December')."""
    start_date = inputs.get("start_date")
    if start_date:
        return start_date.strftime("%d %b %Y")
    return inputs.get("month") or "Not specified"


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------
def plan_to_markdown(inputs: Dict[str, Any], result: Dict[str, Any]) -> str:
    """Turn a finished plan into a Markdown document for download."""
    plan = result["plan"]
    totals = result["totals"]
    lines: List[str] = []

    lines.append(f"# {plan['trip_title']}")
    lines.append("")
    lines.append(
        f"**Route:** {inputs['origin']} → {inputs['destination']}  \n"
        f"**Duration:** {inputs['days']} day(s)  \n"
        f"**Travelers:** {inputs['travelers']} ({inputs['travel_type']})  \n"
        f"**Style:** {inputs['travel_style']}  \n"
        f"**When:** {describe_when(inputs)}  \n"
        f"**Budget:** {format_inr(inputs['budget'])}  \n"
        f"**Estimated total:** {format_inr(totals['grand_total'])}"
    )
    lines.append("")
    if plan["overview"]:
        lines.append(plan["overview"])
        lines.append("")
    if plan["budget_note"]:
        lines.append(f"> **Budget note:** {plan['budget_note']}")
        lines.append("")

    lines.append("## Day-by-day itinerary")
    for day in plan["days"]:
        lines.append("")
        lines.append(f"### Day {day['day']}: {day['title']}")
        for slot in ("morning", "afternoon", "evening"):
            item = day[slot]
            place = f" ({item['place']})" if item["place"] else ""
            lines.append(
                f"- **{slot.capitalize()}:** {item['activity']}{place} "
                f"— approx. {format_inr(item['cost'])}"
            )
        if day["food_recommendations"]:
            lines.append(f"- **Food to try:** {', '.join(day['food_recommendations'])}")
        lines.append(
            f"- **Transport:** {day['transport']['suggestion']} "
            f"— approx. {format_inr(day['transport']['cost'])}"
        )
        lines.append(
            f"- **Stay:** {day['accommodation']['suggestion']} "
            f"— approx. {format_inr(day['accommodation']['cost'])}"
        )
        lines.append(f"- **Food cost:** approx. {format_inr(day['food_cost'])}")
        lines.append(f"- **Day total:** approx. {format_inr(day['day_total'])}")

    lines.append("")
    lines.append("## Budget breakdown")
    lines.append("")
    lines.append("| Category | Estimated cost |")
    lines.append("|---|---|")
    for category, amount in totals["by_category"].items():
        lines.append(f"| {category} | {format_inr(amount)} |")
    lines.append(f"| **Total** | **{format_inr(totals['grand_total'])}** |")

    if plan["tips"]:
        lines.append("")
        lines.append("## Travel tips")
        lines.extend(f"- {tip}" for tip in plan["tips"])
    if plan["safety"]:
        lines.append("")
        lines.append("## Safety suggestions")
        lines.extend(f"- {tip}" for tip in plan["safety"])

    lines.append("")
    lines.append("---")
    lines.append(
        "*All prices are AI-generated estimates for the whole group, not live "
        "quotes. Check real prices before booking.*"
    )
    return "\n".join(lines) + "\n"
