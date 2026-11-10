/* Lead Detail - JavaScript Logic */

/**
 * Copy Checkout Link
 */
function copyCheckoutLink() {
    const copyText = document.getElementById("checkoutLinkInput");
    if (!copyText) return;

    copyText.select();
    copyText.setSelectionRange(0, 99999);

    navigator.clipboard.writeText(copyText.value).then(() => {
        const btn = document.querySelector('button[onclick="copyCheckoutLink()"]');
        if (!btn) return;

        const originalHtml = btn.innerHTML;
        const originalClass = btn.className;

        btn.innerHTML = '<i class="bi bi-check-circle"></i> Copied!';
        btn.className = 'btn btn-success action-btn';

        showToast('Checkout link copied to clipboard!', 'success');

        setTimeout(() => {
            btn.innerHTML = originalHtml;
            btn.className = originalClass;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showToast('Failed to copy link', 'error');
    });
}

/**
 * Copy Message Text
 */
function copyMessage(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    const text = element.textContent || element.innerText;

    navigator.clipboard.writeText(text).then(() => {
        const copyBtn = document.querySelector(`button[onclick="copyMessage('${elementId}')"]`);
        if (!copyBtn) return;
        const originalHtml = copyBtn.innerHTML;

        copyBtn.innerHTML = '<i class="bi bi-check"></i> Copied';
        copyBtn.classList.remove('btn-outline-secondary');
        copyBtn.classList.add('btn-success');

        showToast('Message copied to clipboard!', 'success');

        setTimeout(() => {
            copyBtn.innerHTML = originalHtml;
            copyBtn.classList.remove('btn-success');
            copyBtn.classList.add('btn-outline-secondary');
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showToast('Failed to copy message', 'error');
    });
}

/**
 * Handle Status Input Change
 */
function onStatusInputChange(select, leadId) {
    const editor = document.getElementById('followUpEditor');
    const status = select.value;

    if (status === 'FOLLOW_UP') {
        if (editor) editor.style.display = 'block';
        showToast('Please set a follow-up date and click Save below.', 'info');
    } else {
        if (editor) editor.style.display = 'none';
        saveStatusOnly(leadId, status);
    }

    // Update styling
    select.classList.remove('bg-light', 'bg-info', 'bg-success', 'bg-warning', 'bg-danger', 'bg-primary', 'text-white', 'text-dark');
    const cls = getStatusClass(status);
    select.classList.add(cls);

    if (['DEAL', 'SENT', 'FOLLOW_UP', 'NO_DEAL'].includes(status)) {
        select.classList.add('text-white');
    } else if (status === 'REPLIED') {
        select.classList.add('text-dark');
    }
}

function saveStatusOnly(leadId, status) {
    const statusFormData = new URLSearchParams();
    statusFormData.append('status', status);

    fetch(`/update-status/${leadId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: statusFormData
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('Status updated successfully!', 'success');
            } else {
                showToast('Failed to update status', 'error');
            }
        })
        .catch(err => showToast('Connection error', 'error'));
}

function getStatusClass(status) {
    switch (status) {
        case 'NOT_CONTACTED': return 'bg-light';
        case 'SENT': return 'bg-info';
        case 'REPLIED': return 'bg-warning';
        case 'FOLLOW_UP': return 'bg-primary';
        case 'DEAL': return 'bg-success';
        case 'NO_DEAL': return 'bg-danger';
        default: return 'bg-light';
    }
}

/**
 * Save All Documentation
 */
function saveAllSettings(leadId) {
    const statusSelect = document.querySelector('select[name="status"]');
    const status = statusSelect ? statusSelect.value : '';
    const notesInput = document.getElementById('salesNotes');
    const notes = notesInput ? notesInput.value : '';
    const followUpDateInput = document.getElementById('followUpDateDetail');
    const followUpDate = followUpDateInput ? followUpDateInput.value : '';
    const followUpNotesInput = document.getElementById('followUpNotesDetail');
    const followUpNotes = followUpNotesInput ? followUpNotesInput.value : '';

    const saveBtn = document.querySelector('button[onclick^="saveAllSettings"]');
    const originalHtml = saveBtn ? saveBtn.innerHTML : '';

    if (status === 'FOLLOW_UP' && !followUpDate) return showToast('Please select a follow-up date.', 'error');

    if (saveBtn) {
        saveBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Saving...';
        saveBtn.disabled = true;
    }

    const statusFormData = new URLSearchParams({
        'status': status,
        'follow_up_date': followUpDate,
        'follow_up_notes': followUpNotes
    });

    fetch(`/update-status/${leadId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: statusFormData
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                return fetch(`/update-notes/${leadId}/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                    body: JSON.stringify({ notes: notes })
                });
            }
            throw new Error(data.message || 'Status update failed');
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                if (saveBtn) {
                    saveBtn.innerHTML = '<i class="bi bi-check-circle"></i> All Saved!';
                    saveBtn.className = 'btn btn-success action-btn w-100 shadow-sm';
                }
                showToast('Information updated!', 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                throw new Error(data.message || 'Notes update failed');
            }
        })
        .catch(err => {
            if (saveBtn) {
                saveBtn.innerHTML = originalHtml;
                saveBtn.disabled = false;
            }
            showToast('Error: ' + err.message, 'error');
        });
}

/**
 * Helpers
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;min-width:250px;';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-success' : type === 'error' ? 'bg-danger' : type === 'warning' ? 'bg-warning' : 'bg-info';
    toast.className = `toast align-items-center text-white ${bgColor} border-0 show`;
    toast.style.marginBottom = '10px';
    toast.innerHTML = `<div class="d-flex align-items-center"><div class="toast-body">${message}</div><button type="button" class="btn-close btn-close-white me-2" data-bs-dismiss="toast"></button></div>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

document.addEventListener('DOMContentLoaded', function () {
    const textarea = document.getElementById('salesNotes');
    if (textarea) {
        textarea.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
        textarea.dispatchEvent(new Event('input'));
    }
});
