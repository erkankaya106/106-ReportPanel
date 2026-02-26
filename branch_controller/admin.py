from datetime import date, timedelta

from django import forms
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.utils.html import format_html

from .models import Bayi, TransferLog, CSVValidationError


# ── Bayi ─────────────────────────────────────────────────────────────────────

@admin.register(Bayi)
class BayiAdmin(admin.ModelAdmin):
    list_display = ('name', 'branch_id', 'is_active', 'created_at')
    search_fields = ('name', 'branch_id')
    actions = ['regenerate_secret_keys']

    def regenerate_secret_keys(self, request, queryset):
        """Seçili bayiler için secret key'i yeniden oluştur."""
        new_keys = []
        for bayi in queryset:
            new_key = Bayi.generate_secret_key()
            bayi.secret_key = new_key
            bayi.save()
            new_keys.append(f"{bayi.name} ({bayi.branch_id}): {new_key}")

        message = (
            f"{queryset.count()} bayinin secret key'i yeniden oluşturuldu:\n"
            + "\n".join(new_keys)
        )
        self.message_user(request, message)

    regenerate_secret_keys.short_description = (
        "Seçili bayiler için secret key'i yeniden oluştur"
    )


# ── TransferLog ───────────────────────────────────────────────────────────────

@admin.register(TransferLog)
class TransferLogAdmin(admin.ModelAdmin):
    list_display = ('bayi', 'filename', 'status', 'created_at', 'ip_address')
    list_filter = ('status', 'bayi')
    readonly_fields = (
        'bayi', 'filename', 's3_path', 'status', 'error_message', 'ip_address', 'created_at'
    )

    def has_add_permission(self, request):
        return False


# ── CSVValidationError ────────────────────────────────────────────────────────

class ValidationDateFilter(SimpleListFilter):
    """
    validation_date alanı için Bugün / Dün / Tarih seç hızlı filtreleri.
    Tarih seçimi date_hierarchy üzerinden de yapılabilir.
    """
    title = "CSV Tarihi"
    parameter_name = "vdate"

    def lookups(self, request, model_admin):
        today = date.today()
        yesterday = today - timedelta(days=1)
        return [
            ("today",     f"Bugün ({today.strftime('%d.%m.%Y')})"),
            ("yesterday", f"Dün ({yesterday.strftime('%d.%m.%Y')})"),
            ("this_week", "Bu Hafta"),
            ("this_month", "Bu Ay"),
        ]

    def queryset(self, request, queryset):
        today = date.today()
        if self.value() == "today":
            return queryset.filter(validation_date=today)
        if self.value() == "yesterday":
            return queryset.filter(validation_date=today - timedelta(days=1))
        if self.value() == "this_week":
            week_start = today - timedelta(days=today.weekday())
            return queryset.filter(validation_date__gte=week_start, validation_date__lte=today)
        if self.value() == "this_month":
            return queryset.filter(
                validation_date__year=today.year,
                validation_date__month=today.month,
            )
        return queryset


@admin.register(CSVValidationError)
class CSVValidationErrorAdmin(admin.ModelAdmin):
    list_display = (
        'filename',
        'provider_id',
        'accuracy_display',
        'error_count',
        'total_rows',
        'bayi',
        'validation_date',
        'detected_at',
    )
    list_filter = (
        ValidationDateFilter,   # Bugün / Dün / Bu Hafta / Bu Ay
        'bayi',
        'filename',             # bet.csv / win.csv / canceled.csv
    )
    search_fields = ('filename', 'summary_message', 'bayi__branch_id', 'bayi__name')
    readonly_fields = (
        'bayi',
        'filename',
        'provider_id',
        'validation_date',
        'total_rows',
        'error_count',
        'accuracy_rate',
        'error_summary_display',
        'summary_message',
        'detected_at',
    )
    # date_hierarchy üzerinden yıl/ay/gün bazında tarihe göre drill-down
    date_hierarchy = 'validation_date'

    def accuracy_display(self, obj):
        """Doğruluk oranını renkli göster"""
        rate = float(obj.accuracy_rate)
        if rate == 100.0:
            color, icon = 'green', '✓'
        elif rate >= 80.0:
            color, icon = 'green', '○'
        elif rate >= 50.0:
            color, icon = 'orange', '△'
        else:
            color, icon = 'red', '✗'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{} %{}</span>',
            color, icon, f'{rate:.2f}'
        )

    accuracy_display.short_description = 'Doğruluk'
    accuracy_display.admin_order_field = 'accuracy_rate'

    def error_summary_display(self, obj):
        """Error summary'yi güzel formatla"""
        if not obj.error_summary:
            return "Hata yok"

        html_parts = []
        for error_type, details in obj.error_summary.items():
            total_count = sum(d['count'] for d in details.values())
            html_parts.append(f"<b>{error_type}</b>: {total_count} adet")

        return format_html('<br>'.join(html_parts))

    error_summary_display.short_description = 'Hata Özeti'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
