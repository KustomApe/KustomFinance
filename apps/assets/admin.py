from django.contrib import admin

from .models import DepreciationRate


@admin.register(DepreciationRate)
class DepreciationRateAdmin(admin.ModelAdmin):
    list_display = ["useful_life", "straight_line_rate", "declining_rate", "revised_rate", "guarantee_rate"]
