"""Check a claim from the terminal and watch every step:

    python -m factslap "Cracking your knuckles causes arthritis" --tone debate
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from factslap.models import CheckResult, Tone
from factslap.pipeline import FactSlap


async def main(claim: str, tone: Tone | None) -> None:
    async for event in FactSlap().run(claim, tone, use_cache=False):
        if isinstance(event, CheckResult):
            print(f"\nVERDICT: {event.verdict.label.value} (confidence {event.verdict.confidence:.2f})")
            print(f"  {event.verdict.explanation}\n")
            print((event.styled_answer or event.answer).text + "\n")
            for e in event.evidence:
                p = e.passage
                print(f"[{e.ref}] {e.stance.value:8} {p.title} ({p.year}, {p.study_type.value}) {p.url or ''}")
                print(f'      "{e.quote}"')
            failed = [c.detail for c in event.verification.checks if not c.passed]
            print(f"\nchecks: {'all passed' if not failed else failed}  ·  {event.latency_ms} ms  ·  ${event.cost_usd:.4f}")
        else:
            print(f"· {event.step:9} {event.ms:>6} ms  {event.message}")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("claim")
    parser.add_argument("--tone", choices=[t.value for t in Tone], default=None)
    args = parser.parse_args()
    asyncio.run(main(args.claim, Tone(args.tone) if args.tone else None))
