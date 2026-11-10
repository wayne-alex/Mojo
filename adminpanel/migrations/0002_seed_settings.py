import json
from django.db import migrations


DEFAULTS = [
    (
        "MOJO_BID_WEIGHTS",
        {"price_fit": 30, "rating": 30, "completion": 20, "skill": 10, "past_client": 10},
        "json",
    ),
    (
        "MOJO_NEW_WORKER",
        {"threshold": 5, "max_boost": 15},
        "json",
    ),
    (
        "MOJO_PASS_TIERS",
        [
            {"name": "small",  "min_budget": "0",      "max_budget": "10",     "pass_cost": 1},
            {"name": "medium", "min_budget": "10.01",  "max_budget": "50",     "pass_cost": 2},
            {"name": "large",  "min_budget": "50.01",  "max_budget": "200",    "pass_cost": 3},
            {"name": "xl",     "min_budget": "200.01", "max_budget": "999999", "pass_cost": 5},
        ],
        "json",
    ),
    ("MOJO_PLATFORM_FEE_PCT", "0.10", "decimal"),
    ("MOJO_PENDING_HOLD_HOURS", "48", "int"),
    ("MOJO_AUTO_APPROVE_DAYS", "5", "int"),
    ("MOJO_MAX_REVISIONS", "2", "int"),
]


def seed(apps, schema_editor):
    Setting = apps.get_model("adminpanel", "Setting")
    for key, value, vtype in DEFAULTS:
        serialized = json.dumps(value) if vtype == "json" else str(value)
        Setting.objects.get_or_create(
            key=key,
            defaults={
                "value": serialized,
                "value_type": vtype,
                "description": f"Seeded default for {key}",
            },
        )


def unseed(apps, schema_editor):
    Setting = apps.get_model("adminpanel", "Setting")
    Setting.objects.filter(
        key__in=[k for k, _, _ in DEFAULTS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("adminpanel", "0001_initial")]   # ← points at the real CreateModel
    operations = [migrations.RunPython(seed, unseed)]