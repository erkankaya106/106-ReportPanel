from django import forms
from django.contrib import admin
from django.utils.html import format_html
from .models import Bayi, TransferLog, CSVValidationError


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
        
        message = f"{queryset.count()} bayinin secret key'i yeniden oluşturuldu:\n" + "\n".join(new_keys)
        self.message_user(request, message)
    regenerate_secret_keys.short_description = "Seçili bayiler için secret key'i yeniden oluştur"

@admin.register(TransferLog)
class TransferLogAdmin(admin.ModelAdmin):
    list_display = ('bayi', 'filename', 'status', 'created_at', 'ip_address')
    list_filter = ('status', 'bayi')
    readonly_fields = ('bayi', 'filename', 's3_path', 'status', 'error_message', 'ip_address', 'created_at')

    def has_add_permission(self, request): return False # Elle log eklenemesin


@admin.register(CSVValidationError)
class CSVValidationErrorAdmin(admin.ModelAdmin):
    list_display = ('filename', 'accuracy_display', 'error_count', 'total_rows', 'bayi', 'validation_date', 'detected_at')
    list_filter = ('bayi', 'validation_date', 'detected_at')
    search_fields = ('filename', 'summary_message')
    readonly_fields = ('bayi', 'filename', 'validation_date', 'total_rows', 'error_count', 
                      'accuracy_rate', 'error_summary_display', 'summary_message', 'detected_at')
    date_hierarchy = 'detected_at'
    
    def accuracy_display(self, obj):
        """Doğruluk oranını renkli göster"""
        rate = float(obj.accuracy_rate)
        if rate == 100.0:
            color = 'green'
            icon = '✓'
        elif rate >= 80.0:
            color = 'green'
            icon = '○'
        elif rate >= 50.0:
            color = 'orange'
            icon = '△'
        else:
            color = 'red'
            icon = '✗'
        
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
    
    def accuracy_rate_range(self, obj):
        """Filtreleme için accuracy range döndürür"""
        rate = float(obj.accuracy_rate)
        if rate == 100.0:
            return '100% Mükemmel'
        elif rate >= 80.0:
            return '80-99% İyi'
        elif rate >= 50.0:
            return '50-79% Orta'
        else:
            return '0-49% Kritik'
    accuracy_rate_range.short_description = 'Doğruluk Kategorisi'
    
    def has_add_permission(self, request): return False # Elle eklenemesin
    
    def has_change_permission(self, request, obj=None): return False # Değiştirilemez