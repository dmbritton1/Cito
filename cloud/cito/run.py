"""CLI runner — the manual trigger for the pipeline.

Examples:
  uv run python -m cito.run announce --source weather --source stocks
  uv run python -m cito.run announce --message "All-hands at 3pm."
  uv run python -m cito.run announce --source weather --print
"""

import argparse

from dotenv import load_dotenv

from cito import pipeline


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fire a Cito announcement.")
    sub = parser.add_subparsers(dest="command", required=True)

    ann = sub.add_parser("announce", help="generate and/or send an announcement")
    ann.add_argument("--source", action="append", default=[], dest="sources",
                     help="source key (repeatable): weather, stocks")
    ann.add_argument("--message", help="send this exact text, skipping generation")
    ann.add_argument("--print", action="store_true", dest="print_only",
                     help="print the script instead of sending")
    ann.add_argument("--voice", default=None,
                     help="override the saved voice/personality for this run")
    ann.add_argument("--document", help="path to a .txt/.docx/.pdf to base the announcement on")

    args = parser.parse_args()

    if args.message and args.message.strip():
        text = args.message
    else:
        document_text = ""
        if args.document:
            from cito import documents
            try:
                with open(args.document, "rb") as f:
                    document_text = documents.extract_text(args.document, f.read())
            except documents.DocumentError as exc:
                parser.error(str(exc))
            except OSError as exc:
                parser.error(f"could not read {args.document}: {exc}")
        if not args.sources and not document_text:
            parser.error("provide --message, --document, or at least one --source")
        text = pipeline.generate_announcement(
            args.sources, voice=args.voice, document_text=document_text)

    print(f"Script: {text}")
    if args.print_only:
        return
    result = pipeline.send_announcement(text)
    print(f"Sent {result.packets} packets.")


if __name__ == "__main__":
    main()
