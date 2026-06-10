#!/usr/bin/env python3
"""Validate and sync datasets/foods.csv into the configured food database."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config  # noqa: E402
from models.models import Food, db  # noqa: E402


REQUIRED_FIELDS = [
    "food_id",
    "food_name",
    "cuisine",
    "category",
    "calories",
    "protein",
    "carbs",
    "fats",
    "spice_level",
    "veg_nonveg",
    "price",
    "meal_type",
    "image_url",
    "description",
    "ingredients",
    "allergens",
]

VALID_CUISINES = {"Indian", "Italian", "Chinese", "American", "Japanese", "Mexican"}
VALID_CATEGORIES = {"Breakfast", "Lunch", "Dinner", "Snacks"}
VALID_SPICE_LEVELS = {"Low", "Medium", "High"}
VALID_DIETS = {"Veg", "Non-Veg"}
VALID_MEAL_TYPES = {"Light", "Heavy", "Snack"}
VALID_ALLERGENS = {
    "Gluten",
    "Dairy",
    "Nuts",
    "Peanuts",
    "Eggs",
    "Soy",
    "Fish",
    "Shellfish",
    "Sesame",
}

NUMERIC_FIELDS = {
    "calories": int,
    "protein": float,
    "carbs": float,
    "fats": float,
    "price": float,
}


def create_sync_app() -> Flask:
    app = Flask(
        "sync_foods",
        instance_path=str(PROJECT_ROOT / "instance"),
        root_path=str(PROJECT_ROOT),
    )
    app.config.from_object(Config)
    db.init_app(app)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and upsert foods from datasets/foods.csv."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the configured database. Omit for dry run.",
    )
    parser.add_argument(
        "--csv",
        default=str(PROJECT_ROOT / "datasets" / "foods.csv"),
        help="Path to the foods CSV file.",
    )
    return parser.parse_args()


def parse_allergens(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace(",", "|").split("|") if item.strip()]


def validate_row(row: dict[str, str], row_number: int, seen_ids: set[str]) -> list[str]:
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in row:
            errors.append(f"row {row_number}: missing column {field}")
        elif field != "allergens" and not row[field].strip():
            errors.append(f"row {row_number}: {field} is required")

    if errors:
        return errors

    food_id = row["food_id"].strip()
    if food_id in seen_ids:
        errors.append(f"row {row_number}: duplicate food_id {food_id}")
    seen_ids.add(food_id)

    if row["cuisine"] not in VALID_CUISINES:
        errors.append(f"row {row_number}: invalid cuisine {row['cuisine']}")
    if row["category"] not in VALID_CATEGORIES:
        errors.append(f"row {row_number}: invalid category {row['category']}")
    if row["spice_level"] not in VALID_SPICE_LEVELS:
        errors.append(f"row {row_number}: invalid spice_level {row['spice_level']}")
    if row["veg_nonveg"] not in VALID_DIETS:
        errors.append(f"row {row_number}: invalid veg_nonveg {row['veg_nonveg']}")
    if row["meal_type"] not in VALID_MEAL_TYPES:
        errors.append(f"row {row_number}: invalid meal_type {row['meal_type']}")
    if not (row["image_url"].startswith("https://") or row["image_url"].startswith("/food-image/")):
        errors.append(f"row {row_number}: image_url must start with https:// or /food-image/")
    if "source.unsplash.com" in row["image_url"]:
        errors.append(f"row {row_number}: source.unsplash.com image URLs are unavailable")
    if "loremflickr.com" in row["image_url"]:
        errors.append(f"row {row_number}: loremflickr image URLs can return unrelated photos")

    for field, caster in NUMERIC_FIELDS.items():
        try:
            value = caster(row[field])
        except ValueError:
            errors.append(f"row {row_number}: {field} must be numeric")
            continue
        if value < 0:
            errors.append(f"row {row_number}: {field} cannot be negative")

    invalid_allergens = [a for a in parse_allergens(row["allergens"]) if a not in VALID_ALLERGENS]
    if invalid_allergens:
        errors.append(
            f"row {row_number}: invalid allergens {', '.join(invalid_allergens)}"
        )

    return errors


def load_food_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    errors = []
    rows = []
    seen_ids: set[str] = set()

    if not csv_path.exists():
        return [], [f"CSV file not found: {csv_path}"]

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REQUIRED_FIELDS:
            errors.append(
                "CSV header must exactly match: " + ", ".join(REQUIRED_FIELDS)
            )
            return [], errors

        for row_number, row in enumerate(reader, start=2):
            cleaned = {key: (value or "").strip() for key, value in row.items()}
            errors.extend(validate_row(cleaned, row_number, seen_ids))
            rows.append(cleaned)

    return rows, errors


def row_to_food_values(row: dict[str, str]) -> dict[str, object]:
    return {
        "food_id": row["food_id"],
        "food_name": row["food_name"],
        "cuisine": row["cuisine"],
        "category": row["category"],
        "calories": int(row["calories"]),
        "protein": float(row["protein"]),
        "carbs": float(row["carbs"]),
        "fats": float(row["fats"]),
        "spice_level": row["spice_level"],
        "veg_nonveg": row["veg_nonveg"],
        "price": float(row["price"]),
        "meal_type": row["meal_type"],
        "image_url": row["image_url"],
        "description": row["description"],
        "ingredients": row["ingredients"],
        "allergens": row["allergens"],
    }


def food_has_changes(food: Food, values: dict[str, object]) -> bool:
    return any(getattr(food, key) != value for key, value in values.items())


def sync_foods(rows: list[dict[str, str]], apply_changes: bool) -> dict[str, int]:
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    if apply_changes:
        db.create_all()

    for row in rows:
        values = row_to_food_values(row)
        existing = db.session.get(Food, values["food_id"])

        if existing is None:
            stats["inserted"] += 1
            if apply_changes:
                db.session.add(Food(**values))
            continue

        if food_has_changes(existing, values):
            stats["updated"] += 1
            if apply_changes:
                for key, value in values.items():
                    setattr(existing, key, value)
        else:
            stats["skipped"] += 1

    if apply_changes:
        db.session.commit()
    else:
        db.session.rollback()

    return stats


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv).expanduser().resolve()
    rows, errors = load_food_rows(csv_path)

    print(f"CSV rows read: {len(rows)}")
    print(f"Validation errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")

    if errors:
        return 1

    app = create_sync_app()
    with app.app_context():
        try:
            stats = sync_foods(rows, args.apply)
        except SQLAlchemyError as exc:
            db.session.rollback()
            print(f"Database sync failed: {exc}")
            return 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"Mode: {mode}")
    print(f"Inserted: {stats['inserted']}")
    print(f"Updated: {stats['updated']}")
    print(f"Skipped: {stats['skipped']}")
    print("No rows were deleted.")

    if not args.apply:
        print("Run with --apply to write these changes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
