# ✈️ AI Travel Agent

**An Agentic AI System for Real-Time Travel Planning and Dynamic Itinerary Generation**
A college mini project built with Python, Streamlit and the Google Gemini API.

---

## 1. Project overview

You enter your starting location, destination, number of days, budget (in ₹), travel type, travel style, number of travelers and travel month/date. The app then:

1. **Validates** your inputs.
2. **Fetches a live weather forecast** for the destination (Open-Meteo, optional, no key needed).
3. **Asks Gemini** to write a day-by-day plan with estimated costs.
4. **Adds up the costs in Python** and compares the total with your budget.
5. **Asks Gemini to revise** the plan (up to 2 times) if it is over budget.
6. Shows the final itinerary, budget charts, weather, tips and a **Markdown download**.

### Honest note about the word "agentic"

This project is a **fixed, step-by-step workflow** that uses an AI model and one real external tool (the weather API). It is *not* a fully autonomous agent: the AI does not choose its own tools, browse the web, or book anything. The "Agent steps" tab in the app shows exactly what ran. This is good to mention in your viva/demo.

## 2. Features

- Input form: start, destination, days, budget (₹), travel type, style, travelers, month or exact date
- Input validation (e.g. Solo = 1 traveler, Couple = 2, start ≠ destination, no past dates)
- Morning / afternoon / evening plan for each day, attractions, local food, transport, stay
- Cost estimates per item, **totals recalculated by our code** (not trusted from the AI)
- Automatic budget check and revision loop; clear warning if the budget is probably too low
- Live weather forecast (optional; the app works without it)
- Budget table, bar chart and day-wise cost table
- Travel tips and safety suggestions
- Download the itinerary as a `.md` file
- Friendly messages for: missing/invalid API key, timeouts, network errors, rate limits, empty or malformed AI replies, unexpected errors

## 3. Technology stack

| Part | Technology |
|---|---|
| Language | Python 3.10 or newer |
| Web interface | Streamlit |
| AI | Google Gemini API via the `google-genai` SDK (`from google import genai`) |
| Weather | Open-Meteo (free, no API key) via `requests` |
| Secrets | `python-dotenv` and a `.env` file |
| Tables / charts | pandas + Streamlit charts |

## 4. Folder structure

```
AI_Travel_Agent/
├── app.py                  # Streamlit user interface (run this)
├── config.py               # Settings, form options, reads environment variables
├── requirements.txt        # Python packages
├── .env.example            # Template for your secret keys (copy to .env)
├── .gitignore              # Keeps .env out of Git
├── README.md               # This file
├── .streamlit/
│   └── config.toml         # Travel-themed colours
├── agents/
│   ├── __init__.py
│   └── travel_agent.py     # The planning workflow + Gemini calls
├── services/
│   ├── __init__.py
│   └── weather_service.py  # Open-Meteo weather lookup
├── utils/
│   ├── __init__.py
│   └── helpers.py          # Validation, ₹ formatting, Markdown export
└── tests/
    ├── __init__.py
    └── test_logic.py       # Offline tests (no internet or API key needed)
```

## 5. Setup on Windows with VS Code

### Step 1 – Install Python
1. Download Python 3.10 or newer from <https://www.python.org/downloads/>.
2. In the installer, **tick "Add python.exe to PATH"**, then click Install.
3. Open a new terminal and check: `python --version`

### Step 2 – Install VS Code and open the project
1. Install VS Code from <https://code.visualstudio.com/> and add the **Python** extension (by Microsoft).
2. Unzip `AI_Travel_Agent.zip`.
3. In VS Code: **File → Open Folder…** and choose the `AI_Travel_Agent` folder.
4. Open a terminal: **Terminal → New Terminal**.

### Step 3 – Create a virtual environment and install packages

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

When it works, your prompt starts with `(.venv)`.
If VS Code asks "We noticed a new environment…", click **Yes**.

### Step 4 – Get a Gemini API key
1. Go to **Google AI Studio**: <https://aistudio.google.com/apikey>
2. Sign in with a Google account.
3. Click **Create API key** and copy it.
4. The free tier has usage limits (requests per minute/day) that Google may change. See <https://ai.google.dev/gemini-api/docs/rate-limits>. Free-tier availability can also depend on your country.

### Step 5 – Create the `.env` file
1. Copy `.env.example` and name the copy `.env` (in the same folder):
   ```
   copy .env.example .env
   ```
2. Open `.env` and replace the placeholder:
   ```
   GEMINI_API_KEY=AIza...your_real_key...
   ```
   No quotes, no spaces. **Never share this file or upload it to GitHub.** (`.gitignore` already excludes it.)

### Step 6 – Run the app

```
python -m streamlit run app.py
```

Your browser opens at <http://localhost:8501>. Fill the sidebar form and click **Generate itinerary**.

### Optional – run the offline tests

```
python -m unittest discover -s tests -v
```

## 6. API keys you need

| Key | Required? | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | <https://aistudio.google.com/apikey> |
| Weather | No key needed | Open-Meteo is used without a key |

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python and tick **Add python.exe to PATH**, or try `py -m venv .venv`. |
| `.venv\Scripts\activate` is blocked in PowerShell ("running scripts is disabled") | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and activate again, or use **Command Prompt** instead of PowerShell. |
| `No module named streamlit` / `google` | The virtual environment is not active or packages are not installed. Run `.venv\Scripts\activate` then `pip install -r requirements.txt`. |
| "Gemini API key not found" | Make sure the file is named exactly `.env` (not `.env.txt`), is inside `AI_Travel_Agent`, and contains `GEMINI_API_KEY=...`. Restart Streamlit afterwards. Windows hides file extensions by default; enable **View → File name extensions** in File Explorer. |
| "Gemini rejected your API key" | The key is wrong, deleted or not allowed in your region. Create a new key. |
| "Rate limit or quota reached" | Wait a minute and retry. You hit the free-tier limit. |
| "Model … was not found" | Google retired the model. Check <https://ai.google.dev/gemini-api/docs/models>, then set `GEMINI_MODEL=<current model name>` in `.env`. |
| "Timed out" / "Network error" | Check your internet, VPN or college firewall/proxy. |
| Weather tab says unavailable | Weather is optional. The location may not have been found, or you are offline. |
| "AI response could not be read" | The reply may have been cut off. Retry or use fewer days. |
| Port already in use | `python -m streamlit run app.py --server.port 8502` |

## 8. Limitations

- **All prices are AI estimates.** The app does not know live hotel, flight, train or bus prices or availability, and **it cannot book anything**. Always verify before booking.
- The AI can be wrong about places, opening hours or distances. Check important details.
- Gemini does not search the internet here. Only the weather comes from a live source.
- Weather forecasts cover roughly the next 16 days. For later trips the app shows the *current* 7-day forecast and labels it as not being for your dates.
- Revisions use AI judgement; a plan may still be over budget, in which case the app warns you.
- Costs are for the whole group, in INR, rounded estimates.
- The default model name (`gemini-2.5-flash`) may be retired in the future; change `GEMINI_MODEL` in `.env` if so.
- Free-tier API usage may be subject to Google's data-use terms; do not enter private information.

## 9. Future enhancements

- Live flight/hotel prices through official partner APIs (needs approved access and keys)
- Maps and routes (e.g. a maps API) and distance-based transport costs
- Save/load trips, user accounts, PDF export
- Currency conversion and multi-city trips
- True tool-calling agent (Gemini function calling) that decides which tools to use
- Multi-language support
