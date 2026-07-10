  # Job Scraper Agent

CrewAI-based multi-agent system that investigates a company careers site, designs a scraper, generates a standalone `scraper_<domain>.py`, verifies it, and iterates until it passes or reaches the retry limit.

## What it produces

- A standalone Python scraper script for the requested company domain
- `jobs.jsonl` when the generated scraper is executed
- `trace.json` and `trace.md` for the orchestration run
- Verification and evaluation artifacts under `outputs/`

## Architecture

1. Discovery Agent
2. Investigation Agent
3. Scraper Design Agent
4. Code Generation Agent
5. Verification Agent
6. Evaluation Agent

The implementation uses CrewAI-compatible agent and task definitions, OpenAI-backed reasoning, Playwright inspection, and a generated standalone scraper template.

## Setup

1. Copy `.env.example` to `.env`
2. Fill in any required API keys
3. Install dependencies
4. Install Playwright browsers

Python note: CrewAI currently publishes support for Python `>=3.10 <3.14`, so if you want the full CrewAI runtime path, use Python 3.12 or 3.13. The project also has a fallback mode that can still run without CrewAI on Python 3.14.

```bash
pip install -r requirements.txt
playwright install chromium
```

## How to Run

### 1. Start the UI (Gradio App)

The easiest way to use the agent is through the web interface. Run:

```bash
python app.py
```

This will launch a local web server (usually at `http://127.0.0.1:7860`). Enter the target company domain (e.g., `f22labs.com`) in the UI and click "Generate Scraper".

### 2. View the Output

Once the generation is complete, the agent will save all outputs in the `logs/` directory, inside a specific folder named after the domain and timestamp:

```text
logs/<company_slug>_<timestamp>/
├── scraper.py     # The standalone generated Python scraper
├── README.md      # Instructions on how to run this specific scraper
├── trace.json     # Detailed LLM and tool execution traces
└── run.log        # Human-readable progress log
```

### 3. Run the Generated Scraper

To actually scrape the jobs, you need to run the generated standalone script. 

1. Navigate to the specific output folder in your terminal:
   ```bash
   cd logs/<company_slug>_<timestamp>
   ```
2. Run the generated script (it does not require CrewAI or LLMs to run):
   ```bash
   python scraper.py --output jobs.jsonl
   ```
   
This will execute the scraper and save the extracted jobs directly into a `jobs.jsonl` file in that folder.
