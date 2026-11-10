import uuid
from django.db import models
from django.conf import settings


class PassTier(models.Model):
    """Admin-configurable bid pass cost by job budget. Defaults seeded from settings."""
    name = models.CharField(max_length=64)
    min_budget = models.DecimalField(max_digits=14, decimal_places=2)
    max_budget = models.DecimalField(max_digits=14, decimal_places=2)
    pass_cost = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["min_budget"]

    def __str__(self):
        return f"{self.name}: {self.min_budget}-{self.max_budget} = {self.pass_cost} pass"

    @classmethod
    def cost_for_budget(cls, budget):
        tier = cls.objects.filter(
            min_budget__lte=budget, max_budget__gte=budget
        ).first()
        return tier.pass_cost if tier else 1