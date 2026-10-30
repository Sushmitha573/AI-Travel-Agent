"""The travel planning workflow.

IMPORTANT - what this "agent" really is
---------------------------------------
This is a fixed, step-by-step workflow written in plain Python that calls the
Gemini model, not a fully autonomous agent. The steps are:

    1. Validate the user's requirements        (Python code)
    2. Fetch a weather forecast (optional)     (Open-Meteo API, real tool call)
    3. Ask Gemini to create a plan             (Gemini API)
    4. Check the plan's cost against the budget (Python code - totals are
       recalculated by us; we do not trust the AI's own arithmetic)
    5. If over budget, ask Gemini to revise it (up to MAX_REVISIONS times)
    6. Return the final, organised itinerary

The model does not browse the internet. Prices are AI estimates, not live data.
"""

import json
import re
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from google import genai
from google.genai import errors, types

import config
from services import weather_service
from services.weather_service import WeatherError
from utils.helpers import clean_text, format_inr, to_number, validate_inputs

StepCallback = Optional[Callable[[str], None]]


# ---------------------------------------------------------------------------
# Exceptions (all messages are written for the end user)
# ---------------------------------------------------------------------------
class TravelAgentError(Exception):
    """Any problem the user should be told about in plain language."""


class MissingAPIKeyError(TravelAgentError):
    """GEMINI_API_KEY is missing or still a placeholder."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are an expert travel planner for travelers from India. "
    "You create realistic, budget-aware itineraries. All money is in Indian Rupees (INR). "
    "You have NO access to live prices, bookings or availability, so every price you give "
    "is a rough estimate. Never claim that something is booked, available or currently priced. "
    "Reply with ONE valid JSON object only: no Markdown, no code fences, no extra text."
)

JSON_SHAPE = """{
  "trip_title": "short catchy title",
  "overview": "2-3 sentence summary of the trip",
  "intercity_transport": {"suggestion": "how to travel from the starting location to the destination and back", "est_cost_inr": 0},
  "days": [
    {
      "day": 1,
      "title": "theme of the day",
      "morning":   {"activity": "...", "place": "attraction or area", "est_cost_inr": 0},
      "afternoon": {"activity": "...", "place": "attraction or area", "est_cost_inr": 0},
      "evening":   {"activity": "...", "place": "attraction or area", "est_cost_inr": 0},
      "food_recommendations": ["local dish or eatery type", "..."],
      "transport": {"suggestion": "local transport for the day", "est_cost_inr": 0},
      "accommodation": {"suggestion": "type/area of stay for the night", "est_cost_inr": 0},
      "food_cost_inr": 0
    }
  ],
  "miscellaneous_cost_inr": 0,
  "budget_note": "one or two sentences on how the plan fits the budget, or why the budget may be insufficient",
  "tips": ["travel tip", "..."],
  "safety": ["safety suggestion", "..."]
}"""

COST_RULES = (
    "COST RULES:\n"
    "- Every est_cost_inr / food_cost_inr / miscellaneous_cost_inr is a plain number in INR "
    "for the WHOLE GROUP (all travelers together), not per person.\n"
    "- accommodation.est_cost_inr is the cost of ONE night for the whole group (enough rooms "
    "for everyone). Use 0 on the last day because the group leaves (nights = days - 1).\n"
    "- intercity_transport.est_cost_inr is the round trip for all travelers.\n"
    "- Activity costs are entry tickets / experiences only; put meals in food_cost_inr.\n"
    "- Produce exactly one entry in \"days\" for each trip day, numbered from 1.\n"
)


def _trip_facts(inputs: Dict[str, Any]) -> str:
    when = inputs["start_date"].strftime("%d %B %Y") if inputs.get("start_date") else inputs["month"]
    return (
        f"- Starting location: {inputs['origin']}\n"
        f"- Destination: {inputs['destination']}\n"
        f"- Duration: {inputs['days']} day(s)\n"
        f"- Travel time: {when}\n"
        f"- Total budget: {format_inr(inputs['budget'])} for the whole group\n"
        f"- Travelers: {inputs['travelers']} ({inputs['travel_type']})\n"
        f"- Preferred style: {inputs['travel_style']}\n"
    )


def build_plan_prompt(inputs: Dict[str, Any], weather_text: Optional[str]) -> str:
    prompt = (
        "Create a day-by-day trip plan.\n\nTRIP DETAILS:\n" + _trip_facts(inputs) + "\n"
        "Aim for a total cost at or just below the budget (roughly 85-100% of it). "
        "If the budget is clearly too low for this trip, build the cheapest realistic plan and "
        "explain this honestly in budget_note.\n"
        "Include morning, afternoon and evening activities, tourist attractions, local food, "
        "transport options, accommodation, travel tips and safety suggestions that suit the "
        "travel type and style.\n\n" + COST_RULES + "\n"
    )
    if weather_text:
        prompt += "Use this real forecast to adapt the plan if relevant:\n" + weather_text + "\n\n"
    prompt += "Return JSON in exactly this shape:\n" + JSON_SHAPE
    return prompt


def build_revision_prompt(
    inputs: Dict[str, Any], previous_plan_json: str, total: float, weather_text: Optional[str]
) -> str:
    over_by = total - inputs["budget"]
    prompt = (
        "The trip plan below is too expensive and must be revised.\n\nTRIP DETAILS:\n"
        + _trip_facts(inputs)
        + f"\nCurrent estimated total: {format_inr(total)}\n"
        f"Budget: {format_inr(inputs['budget'])}\n"
        f"Over budget by: {format_inr(over_by)}\n\n"
        "Revise the plan so the total is at or below the budget. Options: cheaper stays, "
        "cheaper transport, free or low-cost attractions, budget food. Keep the same number "
        "of days and keep the plan realistic and enjoyable. If it truly cannot fit the budget, "
        "make it as cheap as realistically possible and say so honestly in budget_note.\n\n"
        + COST_RULES + "\nCURRENT PLAN (JSON):\n" + previous_plan_json + "\n\n"
    )
    if weather_text:
        prompt += "Forecast:\n" + weather_text + "\n\n"
    prompt += "Return the full revised plan as JSON in exactly this shape:\n" + JSON_SHAPE
    return prompt


# ---------------------------------------------------------------------------
# Parsing and normalising the AI's answer
# ---------------------------------------------------------------------------
def parse_json_text(text: str) -> Dict[str, Any]:
    """Parse JSON from the model, tolerating accidental code fences."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object found")
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    return data


def _text(value: Any) -> str:
    return clean_text(str(value)) if value is not None else ""


def _str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _slot(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "activity": _text(raw.get("activity")) or "Free time / flexible activity",
        "place": _text(raw.get("place")),
        "cost": to_number(raw.get("est_cost_inr")),
    }


def _priced(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {"suggestion": _text(raw.get("suggestion")) or "Not specified", "cost": to_number(raw.get("est_cost_inr"))}


def normalize_plan(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the AI's JSON into a clean, predictable structure."""
    raw_days = raw.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise TravelAgentError("The AI response did not contain any itinerary days. Please try again.")

    days = []
    for index, raw_day in enumerate(raw_days, start=1):
        if not isinstance(raw_day, dict):
            continue
        day = {
            "day": index,
            "title": _text(raw_day.get("title")) or f"Day {index}",
            "morning": _slot(raw_day.get("morning")),
            "afternoon": _slot(raw_day.get("afternoon")),
            "evening": _slot(raw_day.get("evening")),
            "food_recommendations": _str_list(raw_day.get("food_recommendations")),
            "transport": _priced(raw_day.get("transport")),
            "accommodation": _priced(raw_day.get("accommodation")),
            "food_cost": to_number(raw_day.get("food_cost_inr")),
        }
        day["activities_cost"] = sum(day[s]["cost"] for s in ("morning", "afternoon", "evening"))
        day["day_total"] = (
            day["activities_cost"] + day["transport"]["cost"]
            + day["accommodation"]["cost"] + day["food_cost"]
        )
        days.append(day)

    if not days:
        raise TravelAgentError("The AI response had no usable itinerary days. Please try again.")

    return {
        "trip_title": _text(raw.get("trip_title")) or "Your Trip",
        "overview": _text(raw.get("overview")),
        "intercity_transport": _priced(raw.get("intercity_transport")),
        "days": days,
        "miscellaneous_cost": to_number(raw.get("miscellaneous_cost_inr")),
        "budget_note": _text(raw.get("budget_note")),
        "tips": _str_list(raw.get("tips")),
        "safety": _str_list(raw.get("safety")),
    }


def compute_totals(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Add up the costs ourselves (never trust the AI's arithmetic)."""
    days = plan["days"]
    by_category = OrderedDict(
        [
            ("Accommodation", sum(d["accommodation"]["cost"] for d in days)),
            ("Food", sum(d["food_cost"] for d in days)),
            (
                "Transport",
                sum(d["transport"]["cost"] for d in days) + plan["intercity_transport"]["cost"],
            ),
            ("Activities", sum(d["activities_cost"] for d in days)),
            ("Miscellaneous", plan["miscellaneous_cost"]),
        ]
    )
    return {"by_category": by_category, "grand_total": sum(by_category.values())}


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------
class TravelAgent:
    """Runs the planning workflow.

    `generate_fn` is only for automated tests: a function (prompt) -> str that
    replaces the real Gemini call.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        generate_fn: Optional[Callable[[str], str]] = None,
    ):
        self.model = model or config.get_model_name()
        self._generate_fn = generate_fn
        self.client = None

        if generate_fn is None:
            key = config.get_api_key() if api_key is None else api_key.strip()
            if config.api_key_is_placeholder(key):
                raise MissingAPIKeyError(
                    "Gemini API key not found. Create a file named .env in the project folder "
                    "containing GEMINI_API_KEY=your_real_key (see README.md), then restart the app."
                )
            self.client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT_SECONDS * 1000),
            )

    # ----- talking to Gemini -------------------------------------------------
    def _call_model(self, prompt: str) -> str:
        if self._generate_fn is not None:
            return self._generate_fn(prompt)

        last_error: Optional[TravelAgentError] = None
        for attempt in range(2):  # one automatic retry for temporary server problems
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.7,
                        max_output_tokens=16384,
                        response_mime_type="application/json",
                    ),
                )
            except Exception as exc:  # translated into a friendly message below
                last_error, retryable = self._translate_error(exc)
                if retryable and attempt == 0:
                    time.sleep(3)
                    continue
                raise last_error
            text = (response.text or "").strip() if response is not None else ""
            if not text:
                raise TravelAgentError(
                    "The AI returned an empty response (it may have been blocked or cut off). "
                    "Please try again, or change your inputs slightly."
                )
            return text
        raise last_error or TravelAgentError("The AI request failed. Please try again.")

    def _translate_error(self, exc: Exception):
        """Return (friendly TravelAgentError, is_retryable)."""
        name = type(exc).__name__.lower()

        if isinstance(exc, errors.APIError):
            code = getattr(exc, "code", None)
            detail = _text(getattr(exc, "message", "") or str(exc))[:300]
            if code == 429:
                return TravelAgentError(
                    "Gemini rate limit or quota reached. Wait a minute and try again. "
                    "If it keeps happening, check your usage limits in Google AI Studio."
                ), False
            if code in (401, 403) or (code == 400 and "api key" in detail.lower()):
                return TravelAgentError(
                    "Gemini rejected your API key. Check that GEMINI_API_KEY in .env is correct "
                    "and that the key is enabled (and available in your region)."
                ), False
            if code == 404:
                return TravelAgentError(
                    f"The Gemini model '{self.model}' was not found. It may have been retired. "
                    "Set GEMINI_MODEL in .env to a currently available model (see README)."
                ), False
            if isinstance(code, int) and code >= 500 or code in (408,):
                return TravelAgentError(
                    "Gemini is temporarily unavailable or overloaded. Please try again shortly."
                ), True
            return TravelAgentError(f"Gemini returned an error ({code}): {detail}"), False

        if "timeout" in name or isinstance(exc, TimeoutError):
            return TravelAgentError(
                "The request to Gemini timed out. Check your internet and try again "
                "(shorter trips respond faster)."
            ), True
        if "connect" in name or isinstance(exc, (ConnectionError, OSError)):
            return TravelAgentError(
                "Network error: could not reach the Gemini service. Check your internet connection."
            ), True
        return TravelAgentError(f"Unexpected error while contacting the AI ({type(exc).__name__}): {exc}"), False

    def _generate_json(self, prompt: str) -> Dict[str, Any]:
        for attempt in range(2):
            text = self._call_model(prompt)
            try:
                return parse_json_text(text)
            except ValueError:
                if attempt == 0:
                    prompt += "\n\nYour previous reply was not valid JSON. Reply again with ONLY the JSON object."
        raise TravelAgentError(
            "The AI returned a response that could not be read (it may have been cut off). "
            "Try again, or reduce the number of days."
        )

    # ----- the workflow ----------------------------------------------------
    def run(self, user_inputs: Dict[str, Any], on_step: StepCallback = None) -> Dict[str, Any]:
        steps: List[Dict[str, str]] = []
        warnings: List[str] = []

        def log(label: str, status: str, detail: str = "") -> None:
            steps.append({"step": label, "status": status, "detail": detail})
            if on_step:
                on_step(f"{label}: {detail}" if detail else label)

        # Step 1: collect and validate
        inputs = dict(user_inputs)
        inputs["origin"] = clean_text(inputs.get("origin"))
        inputs["destination"] = clean_text(inputs.get("destination"))
        problems = validate_inputs(inputs)
        if problems:
            raise TravelAgentError("Please fix these inputs: " + " ".join(problems))
        log("1. Validate requirements", "done", "All inputs are valid.")

        # Step 2: optional weather tool
        weather = None
        weather_text = None
        try:
            weather = weather_service.get_weather(inputs["destination"], inputs.get("start_date"), inputs["days"])
            weather_text = weather_service.weather_to_prompt_text(weather)
            log("2. Fetch weather (Open-Meteo)", "done", f"Forecast loaded for {weather['place']}.")
        except WeatherError as exc:
            log("2. Fetch weather (Open-Meteo)", "skipped", f"{exc} Continuing without weather.")
        except Exception:  # weather must never break trip planning
            log("2. Fetch weather (Open-Meteo)", "skipped", "Weather unavailable. Continuing without it.")

        # Step 3: first plan from the AI
        log("3. Create plan with Gemini", "running", f"Model: {self.model}")
        plan = normalize_plan(self._generate_json(build_plan_prompt(inputs, weather_text)))
        totals = compute_totals(plan)
        if totals["grand_total"] <= 0:
            raise TravelAgentError("The AI did not provide any cost estimates. Please try again.")
        log("3. Create plan with Gemini", "done", f"Estimated total {format_inr(totals['grand_total'])}.")

        # Steps 4-5: check budget, revise if needed
        budget = inputs["budget"]
        revisions = 0
        while totals["grand_total"] > budget and revisions < config.MAX_REVISIONS:
            revisions += 1
            log(
                f"4. Budget check (round {revisions})", "over",
                f"{format_inr(totals['grand_total'])} exceeds {format_inr(budget)}. Asking Gemini to revise.",
            )
            previous_json = json.dumps(_plan_for_revision(plan), ensure_ascii=False)
            revised = normalize_plan(
                self._generate_json(build_revision_prompt(inputs, previous_json, totals["grand_total"], weather_text))
            )
            revised_totals = compute_totals(revised)
            if 0 < revised_totals["grand_total"] < totals["grand_total"]:
                plan, totals = revised, revised_totals
                log(f"5. Revise plan (round {revisions})", "done", f"New estimate {format_inr(totals['grand_total'])}.")
            else:
                log(f"5. Revise plan (round {revisions})", "done", "Revision was not cheaper; kept the previous plan.")

        within_budget = totals["grand_total"] <= budget
        if within_budget:
            log("4. Budget check", "done", f"{format_inr(totals['grand_total'])} is within {format_inr(budget)}.")
        else:
            shortfall = totals["grand_total"] - budget
            warnings.append(
                f"Your budget may be insufficient: the cheapest plan found is about "
                f"{format_inr(totals['grand_total'])}, which is {format_inr(shortfall)} above your "
                f"{format_inr(budget)} budget. Consider more budget, fewer days, or a closer destination."
            )
            log("4. Budget check", "over", "Still over budget after revisions. See warning.")

        if len(plan["days"]) != inputs["days"]:
            warnings.append(
                f"You asked for {inputs['days']} day(s) but the AI produced {len(plan['days'])}. "
                "You may want to regenerate the plan."
            )

        log("6. Final itinerary ready", "done")
        return {
            "plan": plan,
            "totals": totals,
            "budget": budget,
            "within_budget": within_budget,
            "revisions": revisions,
            "steps": steps,
            "warnings": warnings,
            "weather": weather,
        }


def _plan_for_revision(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Convert our normalised plan back into the JSON shape the AI understands."""
    def slot(s):
        return {"activity": s["activity"], "place": s["place"], "est_cost_inr": s["cost"]}

    def priced(p):
        return {"suggestion": p["suggestion"], "est_cost_inr": p["cost"]}

    return {
        "trip_title": plan["trip_title"],
        "overview": plan["overview"],
        "intercity_transport": priced(plan["intercity_transport"]),
        "days": [
            {
                "day": d["day"],
                "title": d["title"],
                "morning": slot(d["morning"]),
                "afternoon": slot(d["afternoon"]),
                "evening": slot(d["evening"]),
                "food_recommendations": d["food_recommendations"],
                "transport": priced(d["transport"]),
                "accommodation": priced(d["accommodation"]),
                "food_cost_inr": d["food_cost"],
            }
            for d in plan["days"]
        ],
        "miscellaneous_cost_inr": plan["miscellaneous_cost"],
        "budget_note": plan["budget_note"],
        "tips": plan["tips"],
        "safety": plan["safety"],
    }
