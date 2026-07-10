from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import gradio as gr

from job_scraper_agent.crew.crew import kickoff
from job_scraper_agent.settings import Settings
from job_scraper_agent.utils import company_domain_error, normalize_domain


SETTINGS = Settings()
SETTINGS.logs_dir.mkdir(parents=True, exist_ok=True)


def _format_trace_event(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("message") or "").strip()
    if message:
        return message
    stage = str(event.get("stage") or "workflow").strip()
    event_type = str(event.get("event_type") or "result").strip()
    return f"{stage.title()}: {event_type}"


def run_agent(company_domain: str):
    domain = normalize_domain(company_domain)
    error_message = company_domain_error(domain)
    if error_message:
        yield error_message, "", None, None, None, None
        return

    trace_queue: queue.Queue[str] = queue.Queue()
    result: dict[str, Any] = {}
    error: dict[str, str] = {}

    def on_trace_event(event: dict[str, Any]) -> None:
        trace_queue.put(_format_trace_event(event))

    def worker() -> None:
        try:
            result["artifacts"] = kickoff(domain, settings=SETTINGS, on_trace_event=on_trace_event)
        except Exception as exc:  # pragma: no cover
            error["message"] = f"{type(exc).__name__}: {exc}"
        finally:
            trace_queue.put("")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    log_lines: list[str] = []
    while thread.is_alive():
        try:
            item = trace_queue.get(timeout=0.15)
        except queue.Empty:
            item = None
        if item:
            log_lines.append(item)
            current_log = "\n".join(log_lines) + "\n"
            yield current_log, "", None, None, None, None

    while True:
        try:
            item = trace_queue.get_nowait()
        except queue.Empty:
            break
        if item:
            log_lines.append(item)

    thread.join()

    artifacts = result.get("artifacts")
    if error and artifacts is None:
        log_lines.append(f"Failed: {error['message']}")
        yield "\n".join(log_lines) + "\n", "", None, None, None, None
        return

    if artifacts is None:
        log_lines.append("Failed: crew did not return artifacts")
        yield "\n".join(log_lines) + "\n", "", None, None, None, None
        return

    code_path = Path(artifacts.generated_script) if artifacts.generated_script else None
    readme_path = Path(artifacts.readme) if artifacts.readme else None
    trace_path = Path(artifacts.trace_json) if artifacts.trace_json else None
    trace_md_path = Path(artifacts.trace_md) if getattr(artifacts, "trace_md", None) else None
    code_text = code_path.read_text(encoding="utf-8") if code_path and code_path.exists() else ""
    final_log = Path(artifacts.run_log).read_text(encoding="utf-8") if artifacts.run_log and Path(artifacts.run_log).exists() else "\n".join(log_lines) + "\n"
    yield final_log, code_text, str(code_path) if code_path else None, str(readme_path) if readme_path else None, str(trace_path) if trace_path else None, str(trace_md_path) if trace_md_path else None


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Job Scraper Crew Demo") as demo:
        gr.Markdown(
            "# Job Scraper Crew Demo\n"
            "Enter one company domain. The crew writes the final files into `logs/<domain>_<timestamp>/`."
        )
        company_domain = gr.Textbox(label="Company Domain", placeholder="swissre.com")
        run_button = gr.Button("Run agent", variant="primary")
        status_log = gr.Textbox(label="Status / Run Log", lines=18, interactive=False)
        code_box = gr.Code(label="Generated scraper.py", language="python")
        with gr.Row():
            scraper_file = gr.File(label="scraper.py")
            readme_file = gr.File(label="README.md")
            trace_file = gr.File(label="trace.json")
            trace_md_file = gr.File(label="trace.md")
        run_button.click(
            fn=run_agent,
            inputs=[company_domain],
            outputs=[status_log, code_box, scraper_file, readme_file, trace_file, trace_md_file],
        )
    return demo


if __name__ == "__main__":
    build_app().queue().launch()
