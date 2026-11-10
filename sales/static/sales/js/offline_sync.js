// offline_sync.js
const DB_NAME = 'RMS_OFFLINE_DB';
const DB_VERSION = 1;
const STORE_NAME = 'requests';

let db;

// Initialize DB
const request = indexedDB.open(DB_NAME, DB_VERSION);
request.onupgradeneeded = (e) => {
    db = e.target.result;
    if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
    }
};
request.onsuccess = (e) => {
    db = e.target.result;
    console.log('IndexedDB initialized');
    syncRequests();
};

// Function to store request
async function queueRequest(url, method, body, headers = {}) {
    const transaction = db.transaction([STORE_NAME], 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const entry = {
        url,
        method,
        body,
        headers,
        timestamp: Date.now(),
        idempotencyKey: crypto.randomUUID()
    };
    store.add(entry);
    console.log('Request queued for offline sync:', entry);
    // Show notification to user
    alert('You are offline. Your changes have been saved locally and will sync when you are back online.');
}

// Function to sync requests
async function syncRequests() {
    if (!navigator.onLine) return;

    const transaction = db.transaction([STORE_NAME], 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const cursorRequest = store.openCursor();

    cursorRequest.onsuccess = async (e) => {
        const cursor = e.target.result;
        if (cursor) {
            const entry = cursor.value;
            try {
                const response = await fetch(entry.url, {
                    method: entry.method,
                    headers: {
                        ...entry.headers,
                        'X-Idempotency-Key': entry.idempotencyKey
                    },
                    body: entry.body
                });

                if (response.ok) {
                    store.delete(cursor.key);
                    console.log('Successfully synced offline request:', entry);
                }
            } catch (err) {
                console.error('Failed to sync request:', err);
            }
            cursor.continue();
        }
    };
}

// Intercept form submissions if offline
window.addEventListener('submit', async (e) => {
    if (!navigator.onLine) {
        const form = e.target;
        const formData = new FormData(form);
        const url = form.action;
        const method = form.method || 'POST';

        // Only intercept data-modifying requests
        if (method.toUpperCase() === 'POST') {
            e.preventDefault();
            const body = new URLSearchParams(formData).toString();
            const headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            };
            await queueRequest(url, method, body, headers);
        }
    }
});

// Listen for online event
window.addEventListener('online', syncRequests);
