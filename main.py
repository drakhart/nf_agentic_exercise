import argparse
import json
import logging

from dotenv import load_dotenv

from agents.impact_analyst import impact_question
from orchestrator import IncidentOrchestrator
from orchestrator.incident_orchestrator import INCIDENTS_DIR
from orchestrator.stretch import ranked_actions
from project_paths import ENV_FILE
from run_metrics import RunMetrics


def main() -> None:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(
        description="Investigate incidents and produce an evidence-grounded report."
    )
    parser.add_argument("incident_id", nargs="?", default="INC-2043")
    parser.add_argument(
        "--all", action="store_true", help="Investigate every incident and rank its actions."
    )
    parser.add_argument("--critic", action="store_true", help="Review report claims against the evidence.")
    parser.add_argument("--impact", action="store_true", help="Ask the impact specialist for missing information.")
    parser.add_argument("--post-update", action="store_true", help="Post a validated update to the local stub.")
    parser.add_argument("--tool-budget", type=int, help="Maximum tool calls allowed for each incident.")
    parser.add_argument("--timeout", type=float, help="Deadline in seconds for the parallel investigation.")
    args = parser.parse_args()

    if args.tool_budget is not None and args.tool_budget < 0:
        parser.error("--tool-budget must be nonnegative")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    orchestrator = IncidentOrchestrator(
        timeout=args.timeout,
        impact_specialist=impact_question if args.impact else None,
        critic=args.critic,
        post_update=args.post_update,
    )

    if args.all:
        incident_ids = sorted(path.stem for path in INCIDENTS_DIR.glob("INC-*.md"))
        if not incident_ids:
            parser.error("No incident reports were found in data/incidents.")
    else:
        incident_ids = [args.incident_id]

    reports = []
    for incident_id in incident_ids:
        metrics = RunMetrics(tool_budget=args.tool_budget) if args.tool_budget is not None else None
        reports.append(orchestrator.run(incident_id, metrics=metrics))

    if args.all:
        print(json.dumps({
            "incidents": [report.model_dump() for report in reports],
            "actions": ranked_actions(reports),
        }, indent=2))
    else:
        print(reports[0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
