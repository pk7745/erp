/**
 * BMS College of Commerce & Management — ERP Service Worker
 * ==========================================================
 * Handles offline background Web Push notifications with native OS-level
 * sound alerts, vibration pulses, and deep-link click routing even when
 * the browser tab or application window is completely closed.
 */

self.addEventListener('install', function (event) {
  // Activate worker immediately without waiting for existing instances
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  // Claim all active ERP clients immediately
  event.waitUntil(self.clients.claim());
});

/**
 * Push Notification Receiver
 * Wakes up in background when Web Push payload arrives from Google FCM / Mozilla Autopush / Apple APNs.
 */
self.addEventListener('push', function (event) {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = {
        title: 'BMS ERP Alert',
        message: event.data.text()
      };
    }
  }

  const title = data.title || 'BMS College ERP Alert';
  const message = data.message || 'You have a new institutional notification.';
  const actionUrl = data.action_url || '/';
  const category = data.category || 'general';

  // Native notification configuration
  const options = {
    body: message,
    icon: '/static/bms_logo.png',
    badge: '/static/bms_logo.png',
    sound: '/static/sounds/notification_chime.wav', // Hardware OS chime playback
    silent: false, // Ensures operating system notification audio plays
    vibrate: [250, 100, 250, 100, 250], // Distinctive triple-pulse vibration
    tag: data.tag || ('bms-erp-' + (data.id || Date.now())),
    renotify: true,
    requireInteraction: true, // Keep banner on screen until acknowledged
    data: {
      action_url: actionUrl,
      id: data.id,
      category: category,
      timestamp: Date.now()
    },
    actions: [
      {
        action: 'view',
        title: 'View in ERP'
      },
      {
        action: 'close',
        title: 'Dismiss'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

/**
 * Click routing: Focuses an existing ERP window or opens action URL in new window.
 */
self.addEventListener('notificationclick', function (event) {
  event.notification.close();

  if (event.action === 'close') {
    return;
  }

  const actionUrl = (event.notification.data && event.notification.data.action_url)
    ? event.notification.data.action_url
    : '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      // If ERP tab is already open, navigate and focus it
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if (client.url && client.url.includes(self.location.origin) && 'focus' in client) {
          if ('navigate' in client) {
            client.navigate(actionUrl);
          }
          return client.focus();
        }
      }
      // If ERP is not currently open, launch new browser window to destination
      if (clients.openWindow) {
        return clients.openWindow(actionUrl);
      }
    })
  );
});
