"""Offline tests. They never call Gemini or the internet.

Run from the project folder with:  python -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from agents.travel_agent import (  # noqa: E402
    MissingAPIKeyError, TravelAgent, TravelAgentError, parse_json_text,
)
from services.weather_service import WeatherError  # noqa: E402
from utils.helpers import format_inr, plan_to_markdown, to_number, validate_inputs  # noqa: E402


def make_inputs(**overrides):
    base = {
        "origin": "Hyderabad", "destination": "Goa", "days": 2, "travelers": 2,
        "budget": 20000, "travel_type": "Couple", "travel_style": "Food",
        "start_date": None, "month": "December",
    }
    base.update(overrides)
    return base


def fake_plan(scale=1.0):
    """A small AI-style JSON reply. `scale` multiplies every cost."""
    def slot(cost):
        return {"activity": "Walk", "place": "Beach", "est_cost_inr": cost * scale}

    days = [
        {
            "day": n, "title": f"Day {n}",
            "morning": slot(500), "afternoon": slot(500), "evening": slot(500),
            "food_recommendations": ["Fish curry"],
            "transport": {"suggestion": "Taxi", "est_cost_inr": 1000 * scale},
            "accommodation": {"suggestion": "Hotel", "est_cost_inr": (3000 if n == 1 else 0) * scale},
            "food_cost_inr": 1500 * scale,
        }
        for n in (1, 2)
    ]
    return json.dumps({
        "trip_title": "Goa Test", "overview": "Fun",
        "intercity_transport": {"suggestion": "Train", "est_cost_inr": 6000 * scale},
        "days": days, "miscellaneous_cost_inr": 1000 * scale,
        "budget_note": "ok", "tips": ["Tip"], "safety": ["Safe"],
    })


class HelperTests(unittest.TestCase):
    def test_format_inr(self):
        self.assertEqual(format_inr(1234567), "₹12,34,567")
        self.assertEqual(format_inr(999), "₹999")
        self.assertEqual(format_inr(30000), "₹30,000")

    def test_to_number(self):
        self.assertEqual(to_number("₹12,500"), 12500.0)
        self.assertEqual(to_number(None), 0.0)
        self.assertEqual(to_number(-5), 0.0)

    def test_validation_ok(self):
        self.assertEqual(validate_inputs(make_inputs()), [])

    def test_validation_errors(self):
        self.assertTrue(validate_inputs(make_inputs(origin="")))
        self.assertTrue(validate_inputs(make_inputs(destination="hyderabad")))
        self.assertTrue(validate_inputs(make_inputs(budget=10)))
        self.assertTrue(validate_inputs(make_inputs(days=0)))
        self.assertTrue(validate_inputs(make_inputs(travel_type="Solo", travelers=3)))
        self.assertTrue(validate_inputs(make_inputs(destination="Goa <script>{}")))
        self.assertTrue(validate_inputs(make_inputs(start_date=date.today() - timedelta(days=1))))


class ParsingTests(unittest.TestCase):
    def test_plain_and_fenced_json(self):
        self.assertEqual(parse_json_text('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json_text('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json_text('Here: {"a": 1} done'), {"a": 1})

    def test_bad_json(self):
        with self.assertRaises(ValueError):
            parse_json_text("not json")


class AgentTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch(
            "services.weather_service.get_weather", side_effect=WeatherError("offline")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_api_key(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(MissingAPIKeyError):
                TravelAgent()
        with self.assertRaises(MissingAPIKeyError):
            TravelAgent(api_key="your_gemini_api_key_here")

    def test_within_budget_no_revision(self):
        agent = TravelAgent(generate_fn=lambda prompt: fake_plan(1.0))  # costs 18,000
        result = agent.run(make_inputs(budget=25000))
        self.assertTrue(result["within_budget"])
        self.assertEqual(result["revisions"], 0)
        self.assertEqual(result["totals"]["grand_total"], sum(result["totals"]["by_category"].values()))
        self.assertIsNone(result["weather"])  # weather failed but the plan still works

    def test_revision_makes_plan_cheaper(self):
        replies = iter([fake_plan(2.0), fake_plan(1.0)])
        agent = TravelAgent(generate_fn=lambda prompt: next(replies))
        result = agent.run(make_inputs(budget=25000))
        self.assertEqual(result["revisions"], 1)
        self.assertTrue(result["within_budget"])

    def test_still_over_budget_warns(self):
        agent = TravelAgent(generate_fn=lambda prompt: fake_plan(3.0))
        result = agent.run(make_inputs(budget=5000))
        self.assertFalse(result["within_budget"])
        self.assertEqual(result["revisions"], config.MAX_REVISIONS)
        self.assertTrue(result["warnings"])

    def test_bad_json_then_good(self):
        replies = iter(["oops", fake_plan(1.0)])
        agent = TravelAgent(generate_fn=lambda prompt: next(replies))
        self.assertTrue(agent.run(make_inputs(budget=25000))["plan"]["days"])

    def test_always_bad_json(self):
        agent = TravelAgent(generate_fn=lambda prompt: "nope")
        with self.assertRaises(TravelAgentError):
            agent.run(make_inputs())

    def test_invalid_inputs_rejected(self):
        agent = TravelAgent(generate_fn=lambda prompt: fake_plan())
        with self.assertRaises(TravelAgentError):
            agent.run(make_inputs(origin=""))

    def test_markdown_export(self):
        agent = TravelAgent(generate_fn=lambda prompt: fake_plan(1.0))
        inputs = make_inputs(budget=25000)
        markdown = plan_to_markdown(inputs, agent.run(inputs))
        self.assertIn("# Goa Test", markdown)
        self.assertIn("## Budget breakdown", markdown)
        self.assertIn("estimates", markdown)


if __name__ == "__main__":
    unittest.main()
