import json
import random
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["Questions"])

_BANK_PATH = Path(__file__).parent.parent / "cpg_question_bank.json"
_CATEGORY_KEYS = ["sales_performance", "sku_product", "regional_zone", "target_vs_actual", "risk_anomaly"]

def _load_bank() -> dict:
    with open(_BANK_PATH) as f:
        return json.load(f)

_BANK: dict = _load_bank()


@router.get("/questions")
def get_questions(
    category: str = Query(default="all"),
    limit: int = Query(default=4, ge=1, le=20),
):
    if category == "all":
        pool = [
            {**q, "category": cat}
            for cat in _CATEGORY_KEYS
            for q in _BANK.get(cat, [])
        ]
    elif category in _CATEGORY_KEYS:
        pool = [{**q, "category": category} for q in _BANK.get(category, [])]
    else:
        pool = []

    sample = random.sample(pool, min(limit, len(pool)))
    return sample
