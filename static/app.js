// ===== TICKET TRACKER – APP.JS =====

// Toggle password visibility
function togglePassword(fieldId, iconId) {
    const field = document.getElementById(fieldId);
    const icon = document.getElementById(iconId || 'eyeIcon');
    if (!field) return;
    if (field.type === 'password') {
        field.type = 'text';
        if (icon) icon.className = 'bi bi-eye-slash';
    } else {
        field.type = 'password';
        if (icon) icon.className = 'bi bi-eye';
    }
}

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function () {
    const alerts = document.querySelectorAll('.alert.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            } else {
                alert.style.opacity = '0';
                alert.style.transition = 'opacity 0.5s';
                setTimeout(() => alert.remove(), 500);
            }
        }, 5000);
    });

    // Activate all Bootstrap tooltips
    const tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipEls.forEach(function (el) {
        new bootstrap.Tooltip(el);
    });
});
