"""Avaliação local; não chama NVIDIA nem usa nomes como regra de extração."""

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.extracta.recovery import CallBudget
from app.extracta.workflow import analyze_document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--output", default="tmp/extracta/evaluation.json")
    args = parser.parse_args()
    results = []
    settings = get_settings()
    batch_calls = 0
    for filename in args.files:
        path = Path(filename)
        budget = CallBudget(
            settings.extracta_max_llm_calls_per_document,
            settings.extracta_max_llm_calls_per_batch,
            batch_calls=batch_calls,
        )
        result = analyze_document(path.read_bytes(), path.name, settings, budget)
        batch_calls = budget.batch_calls
        results.append(result.model_dump(mode="json"))
        print(
            json.dumps(
                {
                    "file": path.name,
                    "status": result.status,
                    "pages": result.page_count,
                    "items": [len(order.items) for order in result.orders],
                    "totals": [str(order.calculated_product_total) for order in result.orders],
                    "seconds": round(result.timings["total"], 2),
                    "errors": result.errors,
                },
                ensure_ascii=False,
            )
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
