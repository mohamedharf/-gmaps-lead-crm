/* Data Explorer - JavaScript Logic */

// Global modal references
let followUpModal;
let messageModal;

/**
 * Main Initialization
 */
document.addEventListener('DOMContentLoaded', function () {
    // 1. Mobile dropdown handling
    initMobileDropdowns();

    // 2. Bulk selection logic
    initBulkSelection();

    // 3. Status select visual styling
    initStatusStyling();

    // 4. Keyboard shortcuts
    initKeyboardShortcuts();

    // 5. Bulk Actions AJAX
    initBulkActionsAJAX();
});

/**
 * Mobile Dropdown Logic
 */
function initMobileDropdowns() {
    const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', function (e) {
            if (window.innerWidth <= 768) {
                e.preventDefault();
                e.stopPropagation();

                const dropdown = this.closest('.dropdown');
                const menu = dropdown.querySelector('.dropdown-menu');
                const isShowing = menu.classList.contains('show');

                // Close others
                document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));

                if (!isShowing) {
                    menu.classList.add('show');
                    dropdown.classList.add('show');
                    toggleBackdrop(true);

                    // Center positioning for mobile
                    Object.assign(menu.style, {
                        position: 'fixed',
                        top: '50%',
                        left: '50%',
                        transform: 'translate(-50%, -50%)',
                        width: '90%',
                        maxWidth: '300px',
                        zIndex: '1060'
                    });
                    document.body.classList.add('dropdown-open');
                } else {
                    closeAllDropdowns();
                }
            }
        });
    });

    document.addEventListener('click', e => {
        if (e.target.classList.contains('dropdown-backdrop')) closeAllDropdowns();
    });
}

function toggleBackdrop(show) {
    let backdrop = document.querySelector('.dropdown-backdrop');
    if (!backdrop && show) {
        backdrop = document.createElement('div');
        backdrop.className = 'dropdown-backdrop';
        document.body.appendChild(backdrop);
    }
    if (backdrop) backdrop.classList.toggle('show', show);
}

function closeAllDropdowns() {
    document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
        menu.classList.remove('show');
        menu.parentElement.classList.remove('show');
        menu.style.position = '';
    });
    toggleBackdrop(false);
    document.body.classList.remove('dropdown-open');
}

function handleResize() {
    if (window.innerWidth > 768) closeAllDropdowns();
}

/**
 * Bulk Selection Logic
 */
function initBulkSelection() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.row-checkbox');
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');

    if (!selectAll) return;

    const updateUI = () => {
        const checked = document.querySelectorAll('.row-checkbox:checked');
        if (selectedCount) selectedCount.textContent = checked.length;
        if (bulkActions) bulkActions.style.display = checked.length > 0 ? 'block' : 'none';
        selectAll.checked = checked.length === checkboxes.length && checkboxes.length > 0;
        selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
    };

    selectAll.addEventListener('change', () => {
        checkboxes.forEach(cb => cb.checked = selectAll.checked);
        updateUI();
    });

    checkboxes.forEach(cb => cb.addEventListener('change', updateUI));
    updateUI();
}

/**
 * Status and Styles
 */
function initStatusStyling() {
    document.querySelectorAll('.status-select').forEach(select => {
        select.classList.add(getStatusClass(select.value));
        select.addEventListener('change', function () {
            this.classList.remove('bg-light', 'bg-info', 'bg-success', 'bg-warning', 'bg-danger', 'bg-primary', 'text-white', 'text-dark');
            this.classList.add(getStatusClass(this.value));
        });
    });
}

function getStatusClass(status) {
    switch (status) {
        case 'NOT_CONTACTED': return 'bg-light';
        case 'SENT': return 'bg-info text-white';
        case 'REPLIED': return 'bg-warning text-dark';
        case 'FOLLOW_UP': return 'bg-primary text-white';
        case 'DEAL': return 'bg-success text-white';
        case 'NO_DEAL': return 'bg-danger text-white';
        default: return 'bg-light';
    }
}

/**
 * Status Update AJAX
 */
function handleStatusChange(selectElement, pk) {
    const status = selectElement.value;
    if (status === 'FOLLOW_UP') {
        if (!followUpModal) {
            const el = document.getElementById('followUpModal');
            if (el) followUpModal = new bootstrap.Modal(el);
        }
        document.getElementById('followUpLeadId').value = pk;
        document.getElementById('followUpDateInput').value = document.getElementById(`follow_up_date_${pk}`).value || '';
        document.getElementById('followUpNotesInput').value = document.getElementById(`follow_up_notes_${pk}`).value || '';
        followUpModal?.show();
    } else {
        updateStatusAjax(selectElement, pk);
    }
}

function submitFollowUpModal() {
    const pk = document.getElementById('followUpLeadId').value;
    const date = document.getElementById('followUpDateInput').value;
    const notes = document.getElementById('followUpNotesInput').value;

    if (!date) return alert('Please select a follow-up date.');

    document.getElementById(`follow_up_date_${pk}`).value = date;
    document.getElementById(`follow_up_notes_${pk}`).value = notes;

    const select = document.getElementById(`status_select_${pk}`);
    if (select) updateStatusAjax(select, pk);
    followUpModal?.hide();
}

function updateStatusAjax(element, pk) {
    const form = element.closest('form');
    if (!form) {
        console.error("Status update failed: Form not found for primary key", pk);
        return;
    }

    const statusSelect = form.querySelector('select[name="status"]');
    const status = statusSelect?.value || '';
    const dateInput = document.getElementById(`follow_up_date_${pk}`);
    const date = dateInput?.value || '';
    const notesInput = document.getElementById(`follow_up_notes_${pk}`);
    const notes = notesInput?.value || '';

    // CSRF token retrieval with fallback
    const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]')?.value ||
        document.querySelector('[name=csrfmiddlewaretoken]')?.value;

    if (!csrfToken) {
        console.error("Status update failed: CSRF token missing.");
        showToast('Security Error: Refresh page', 'error');
        return;
    }

    const params = new URLSearchParams();
    params.append('status', String(status));
    params.append('follow_up_date', String(date));
    params.append('follow_up_notes', String(notes));

    fetch(form.action, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: params
    })
        .then(async r => {
            if (!r.ok) {
                const text = await r.text();
                throw new Error(`Server returned ${r.status}: ${text}`);
            }
            return r.json();
        })
        .then(data => {
            if (data.status === 'success') {
                showToast('Success!', 'success');
                const infoDiv = document.getElementById(`follow_up_info_${pk}`);
                if (infoDiv) {
                    if (status === 'FOLLOW_UP' && date) {
                        const d = new Date(date);
                        const displayDate = d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' });
                        const displayTime = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
                        infoDiv.innerHTML = `<small class="text-danger fw-bold mt-1" title="${notes || ''}"><i class="bi bi-clock"></i> ${displayDate} ${displayTime}</small>`;
                    } else {
                        infoDiv.innerHTML = '';
                    }
                }
            } else {
                showToast(data.message || 'Update failed', 'error');
                console.warn("Status update warning:", data);
            }
        })
        .catch(err => {
            console.error("Status update network/server error:", err);
            showToast('Network error: Check connection', 'error');
        });
}

/**
 * Message Modal AJAX
 */
function openMessageModal(id, msg, type = 'first') {
    if (!messageModal) {
        const el = document.getElementById('messageModal');
        if (el) messageModal = new bootstrap.Modal(el);
    }
    document.getElementById('msgLeadId').value = id;
    document.getElementById('msgBody').value = msg || '';
    document.getElementById('msgType').value = type;
    messageModal?.show();
}

function saveMessage() {
    const id = document.getElementById('msgLeadId').value;
    const body = document.getElementById('msgBody').value;
    const type = document.getElementById('msgType').value;
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;

    fetch(`/update-message/${id}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ message: body, message_type: type })
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('Updated!', 'success');
                if (messageModal) {
                    messageModal.hide();
                } else {
                    const el = document.getElementById('messageModal');
                    if (el) {
                        const m = bootstrap.Modal.getInstance(el) || new bootstrap.Modal(el);
                        m.hide();
                    }
                }
                // Update data attributes in DOM
                const selector = type === 'second' ? `[data-msg-type="second"][data-id="${id}"]` : `[data-id="${id}"]:not([data-msg-type])`;
                const icon = document.querySelector(selector);
                if (icon) {
                    icon.setAttribute('data-msg', body);
                    const copyBtn = icon.previousElementSibling;
                    if (copyBtn?.tagName === 'BUTTON') copyBtn.setAttribute('data-copy-text', body);
                }
            } else {
                showToast(data.message || 'Update failed', 'error');
            }
        });
}

/**
 * Bulk Actions AJAX
 */
function initBulkActionsAJAX() {
    const bulkForm = document.getElementById('bulkForm');
    if (!bulkForm) return;

    bulkForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const actionBtn = e.submitter;
        if (!actionBtn || (actionBtn.value !== 'selected' && actionBtn.value !== 'unassign')) {
            // If it's not the "selected" or "unassign" button, let it bubble
            return;
        }

        const formData = new FormData(bulkForm);
        formData.append('action_type', actionBtn.value);

        // Ensure all selected agents are included if multiple
        const agentSelect = bulkForm.querySelector('select[name="assignee_id"]');
        if (agentSelect && agentSelect.multiple) {
            formData.delete('assignee_id');
            Array.from(agentSelect.selectedOptions).forEach(opt => formData.append('assignee_id', opt.value));
        }

        const csrf = bulkForm.querySelector('[name=csrfmiddlewaretoken]').value;

        fetch(bulkForm.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf },
            body: formData
        })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast(data.message, 'success');
                    setTimeout(() => location.reload(), 1000);
                } else {
                    // To avoid reload, we ideally update the table. Let's redirect to refresh filters properly.
                    // Actually, let's just reload for bulk as it affects many rows.
                    window.location.reload();
                }
            });
    });
}

function submitAssignAll() {
    const bulkForm = document.getElementById('bulkForm');
    const modalSelect = document.querySelector('select[name="assignee_id_all"]');
    const selectedAgents = Array.from(modalSelect.selectedOptions).map(opt => opt.value);
    const csrf = bulkForm.querySelector('[name=csrfmiddlewaretoken]').value;

    if (selectedAgents.length === 0) return alert('Please select at least one agent.');

    const formData = new FormData(bulkForm);
    formData.append('action_type', 'all_filtered');

    // Clear and re-add assignee_id for multiple
    formData.delete('assignee_id');
    selectedAgents.forEach(id => formData.append('assignee_id', id));

    fetch(bulkForm.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf },
        body: formData
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('All matching leads assigned!', 'success');
                setTimeout(() => location.reload(), 1000);
            }
        });
}

/**
 * UI Helpers
 */
function showToast(message, type = 'success') {
    const toastContainer = document.getElementById('toastWrapper');
    if (!toastContainer) {
        // Fallback for simple status if wrapper not found
        alert(message);
        return;
    }

    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');

    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="bi bi-${type === 'success' ? 'check-circle' : 'exclamation-circle'} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    toastContainer.appendChild(toastEl);
    const bsToast = new bootstrap.Toast(toastEl, { delay: 3000 });
    bsToast.show();

    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

function copyToClipboard(text, msg) {
    if (!text) return showToast('Nothing to copy!', 'error');

    // Modern approach
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(msg || 'Copied to clipboard!', 'success');
        }).catch(() => {
            // Fallback
            fallbackCopy(text, msg);
        });
    } else {
        fallbackCopy(text, msg);
    }
}

function fallbackCopy(text, msg) {
    const tempInput = document.createElement("textarea");
    tempInput.value = text;
    document.body.appendChild(tempInput);
    tempInput.style.position = "fixed";  // Avoid scrolling to bottom
    tempInput.select();
    try {
        document.execCommand("copy");
        showToast(msg || 'Copied to clipboard!', 'success');
    } catch (err) {
        showToast('Failed to copy', 'error');
    }
    document.body.removeChild(tempInput);
}

/**
 * Helpers
 */
function initKeyboardShortcuts() {
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            document.querySelector('input[name="q"]')?.focus();
        }
        if (e.key === 'Escape') closeAllDropdowns();
    });
}

function initMobileTouchBehavior() {
    document.addEventListener('touchstart', () => { }, { passive: true });
    document.addEventListener('dblclick', e => {
        if (window.innerWidth <= 768) e.preventDefault();
    }, { passive: false });
}
