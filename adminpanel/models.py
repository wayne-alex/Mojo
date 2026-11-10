from django.db import models


class Setting(models.Model):
    """
    Runtime-editable domain settings. If a row exists, its value wins over
    settings.MOJO_*. If absent, callers fall back to the settings.py default.
    """
    class ValueType(models.TextChoices):
        INT = "int", "Integer"
        DECIMAL = "decimal", "Decimal"
        STRING = "string", "String"
        BOOL = "bool", "Boolean"
        JSON = "json", "JSON"

    key = models.CharField(max_length=64, unique=True)
    value = models.TextField()
    value_type = models.CharField(
        max_length=16, choices=ValueType.choices, default=ValueType.STRING,
    )
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"

    def coerced_value(self):
        from decimal import Decimal
        import json
        t = self.value_type
        if t == self.ValueType.INT:
            return int(self.value)
        if t == self.ValueType.DECIMAL:
            return Decimal(self.value)
        if t == self.ValueType.BOOL:
            return self.value.lower() in ("1", "true", "yes", "on")
        if t == self.ValueType.JSON:
            return json.loads(self.value)
        return self.value