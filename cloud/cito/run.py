"""CLI runner — the manual trigger for the pipeline.

Examples:
  uv run python -m cito.run announce --source weather --source stocks
  uv run python -m cito.run announce --message "All-hands at 3pm."
  uv run python -m cito.run announce --source weather --print
"""

import argparse

from cito import pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Fire a Cito announcement.")
    sub = parser.add_subparsers(dest="command", required=True)

    ann = sub.add_parser("announce", help="generate and/or send an announcement")
    ann.add_argument("--source", action="append", default=[], dest="sources",
                     help="source key (repeatable): weather, stocks")
    ann.add_argument("--message", help="send this exact text, skipping generation")
    ann.add_argument("--print", action="store_true", dest="print_only",
                     help="print the script instead of sending")

    args = parser.parse_args()

    if args.message and args.message.strip():
        text = args.message
    else:
        if not args.sources:
            parser.error("provide --message or at least one --source")
        text = pipeline.generate_announcement(args.sources)

    print(f"Script: {text}")
    if args.print_only:
        return
    result = pipeline.send_announcement(text)
    print(f"Sent {result.packets} packets.")


if __name__ == "__main__":
    main()
