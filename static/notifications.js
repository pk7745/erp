/**
 * BMS College ERP — Centralized Notification & Sound Client Engine
 * =================================================================
 * Provides Web Audio API harmonic chime synthesis, user gesture autoplay unlocking,
 * Socket.IO real-time push handling, unread badge counter orchestration,
 * native W3C Web Push (Service Worker + VAPID) for closed-window background alerts,
 * physical sound asset playback, and preferences synchronization.
 */

(function () {
  'use strict';

  // State Management
  let soundEnabled = true;
  let browserEnabled = true;
  let currentVolume = 0.7;
  let unreadCount = 0;
  let activeTab = 'all'; // 'all' or 'unread'
  let cachedNotifications = [];
  let isAudioUnlocked = false;
  let lastChimeTime = 0;
  const MIN_CHIME_INTERVAL_MS = 1500; // Rate limit: maximum 1 sound per 1.5s

  let audioCtx = null;
  let socket = null;
  let swRegistration = null;
  let pushSubscribed = false;

  // 1. Web Audio API & Sound Engine
  function getAudioContext() {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    return audioCtx;
  }

  function unlockAudioContext() {
    const ctx = getAudioContext();
    if (ctx && ctx.state === 'suspended') {
      ctx.resume().then(() => {
        isAudioUnlocked = true;
        updateAudioStatusUI();
      }).catch(err => console.debug("Audio unlock notice:", err));
    } else if (ctx && ctx.state === 'running') {
      isAudioUnlocked = true;
      updateAudioStatusUI();
    }
  }

  // Register modern browser interaction listeners for autoplay unlock
  ['click', 'keydown', 'touchstart'].forEach(evt => {
    document.addEventListener(evt, unlockAudioContext, { once: true, passive: true });
  });

  function playNotificationChime(volume = 0.7, force = false) {
    if (!soundEnabled && !force) return;
    const now = Date.now();
    if (!force && (now - lastChimeTime < MIN_CHIME_INTERVAL_MS)) {
      return; // Rate limit cascade suppression
    }
    lastChimeTime = now;

    let synthesized = false;
    const ctx = getAudioContext();
    if (ctx) {
      if (ctx.state === 'suspended') {
        ctx.resume().then(() => synthesizeChime(ctx, volume)).catch(() => {});
      } else {
        synthesizeChime(ctx, volume);
        synthesized = true;
      }
    }

    // Hardware/Physical Audio Fallback using static WAV asset
    if (!synthesized) {
      try {
        const audio = new Audio('/static/sounds/notification_chime.wav');
        audio.volume = Math.max(0.1, Math.min(1.0, volume));
        audio.play().catch(e => console.debug("Audio file playback note:", e));
      } catch (e) {}
    }
  }

  function synthesizeChime(ctx, volume) {
    try {
      const t = ctx.currentTime;
      const gainNode = ctx.createGain();
      gainNode.gain.setValueAtTime(0.0001, t);
      
      const effectiveVol = Math.max(0.05, Math.min(1.0, volume)) * 0.35;
      gainNode.gain.exponentialRampToValueAtTime(effectiveVol, t + 0.03);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, t + 0.45);
      gainNode.connect(ctx.destination);

      // Primary tone: D5 (587.33 Hz) gliding upward to A5 (880 Hz)
      const osc1 = ctx.createOscillator();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(587.33, t);
      osc1.frequency.exponentialRampToValueAtTime(880.00, t + 0.12);
      osc1.connect(gainNode);
      osc1.start(t);
      osc1.stop(t + 0.45);

      // Harmonic overtone: D6 (1174.66 Hz)
      const osc2 = ctx.createOscillator();
      osc2.type = 'triangle';
      osc2.frequency.setValueAtTime(1174.66, t + 0.06);
      osc2.connect(gainNode);
      osc2.start(t + 0.06);
      osc2.stop(t + 0.42);
    } catch (e) {
      console.warn("Chime synthesis warning:", e);
    }
  }

  function updateAudioStatusUI() {
    const el = document.getElementById('notif-audio-status');
    if (el) {
      if (isAudioUnlocked) {
        el.innerHTML = '<i class="fas fa-check-circle" style="color: #10b981;"></i> Audio Ready';
      } else {
        el.innerHTML = '<i class="fas fa-info-circle" style="color: #64748b;"></i> Click page to activate sound';
      }
    }

    const pushEl = document.getElementById('notif-push-status');
    if (pushEl) {
      if (pushSubscribed) {
        pushEl.innerHTML = '<i class="fas fa-check-circle" style="color: #10b981;"></i> Background Active (Window Closed)';
      } else {
        pushEl.innerHTML = '<i class="fas fa-exclamation-triangle" style="color: #f59e0b;"></i> Background Inactive';
      }
    }
  }

  // 2. DOM Rendering & Dropdown Controller
  function updateBadgeUI(count) {
    unreadCount = Math.max(0, count || 0);
    const badge = document.getElementById('notif-badge');
    const pill = document.getElementById('notif-unread-pill');

    if (badge) {
      if (unreadCount > 0) {
        badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
        badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }
    if (pill) {
      pill.textContent = `${unreadCount} unread`;
    }
  }

  function getCategoryIcon(cat) {
    switch (cat) {
      case 'attendance': return { icon: 'fa-user-check', class: 'notif-cat-attendance' };
      case 'marks': return { icon: 'fa-award', class: 'notif-cat-marks' };
      case 'assignments': return { icon: 'fa-clipboard-list', class: 'notif-cat-assignments' };
      case 'study_materials': return { icon: 'fa-book-open', class: 'notif-cat-study_materials' };
      case 'vault': return { icon: 'fa-shield-alt', class: 'notif-cat-vault' };
      case 'payroll': return { icon: 'fa-file-invoice-dollar', class: 'notif-cat-payroll' };
      case 'security': return { icon: 'fa-lock', class: 'notif-cat-security' };
      case 'tasks': return { icon: 'fa-tasks', class: 'notif-cat-tasks' };
      default: return { icon: 'fa-bell', class: 'notif-cat-general' };
    }
  }

  function renderNotificationsList() {
    const container = document.getElementById('notif-list-container');
    if (!container) return;

    let items = cachedNotifications;
    if (activeTab === 'unread') {
      items = cachedNotifications.filter(n => !n.is_read);
    }

    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="notif-empty">
          <i class="fas fa-bell-slash"></i>
          <div style="font-weight: 600;">No notifications found</div>
          <div style="font-size: 0.75rem;">${activeTab === 'unread' ? 'You have read all your alerts.' : 'New institutional alerts will appear here.'}</div>
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(n => {
      const cat = getCategoryIcon(n.category);
      return `
        <div class="notif-item ${n.is_read ? '' : 'unread'}" data-id="${n.id}" data-url="${n.action_url || ''}" onclick="window.BMSNotifications.handleItemClick(event, ${n.id}, '${n.action_url || ''}')">
          <div class="notif-icon-box ${cat.class}">
            <i class="fas ${cat.icon}"></i>
          </div>
          <div class="notif-content">
            <div class="notif-item-header">
              <span class="notif-item-title" title="${escapeHtml(n.title)}">${escapeHtml(n.title)}</span>
              <span class="notif-item-time">${escapeHtml(n.time_display || n.timestamp)}</span>
            </div>
            <div class="notif-item-body">${escapeHtml(n.message)}</div>
            ${n.action_url ? `<span class="notif-item-action"><i class="fas fa-external-link-alt"></i> View Details</span>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // 3. API Communication
  function fetchNotifications() {
    fetch('/api/notifications')
      .then(res => res.json())
      .then(data => {
        if (data && data.notifications) {
          cachedNotifications = data.notifications;
          updateBadgeUI(data.unread_count);
          renderNotificationsList();
        } else if (Array.isArray(data)) {
          cachedNotifications = data;
          updateBadgeUI(data.length);
          renderNotificationsList();
        }
      })
      .catch(err => console.debug("Notifications fetch notice:", err));
  }

  function markSingleAsRead(id) {
    fetch(`/api/notifications/${id}/read`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          updateBadgeUI(data.unread_count);
          const item = cachedNotifications.find(n => n.id === id);
          if (item) item.is_read = true;
          renderNotificationsList();
        }
      })
      .catch(err => console.warn("Mark read error:", err));
  }

  function markAllAsRead() {
    fetch('/api/notifications/mark_all_read', { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          updateBadgeUI(0);
          cachedNotifications.forEach(n => n.is_read = true);
          renderNotificationsList();
        }
      })
      .catch(err => console.warn("Mark all read error:", err));
  }

  function loadPreferences() {
    fetch('/api/notifications/preferences')
      .then(res => res.json())
      .then(pref => {
        soundEnabled = pref.sound_enabled !== false;
        browserEnabled = pref.browser_enabled !== false;
        currentVolume = pref.volume !== undefined ? pref.volume : 0.7;
        updateControlsUI();
      })
      .catch(() => {
        try {
          soundEnabled = localStorage.getItem('bms_notif_sound') !== 'false';
          browserEnabled = localStorage.getItem('bms_notif_browser') === 'true';
          currentVolume = parseFloat(localStorage.getItem('bms_notif_vol') || '0.7');
        } catch (e) {}
        updateControlsUI();
      });
  }

  function savePreferences() {
    fetch('/api/notifications/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sound_enabled: soundEnabled,
        browser_enabled: browserEnabled,
        volume: currentVolume
      })
    }).catch(() => {});

    try {
      localStorage.setItem('bms_notif_sound', soundEnabled);
      localStorage.setItem('bms_notif_browser', browserEnabled);
      localStorage.setItem('bms_notif_vol', currentVolume);
    } catch (e) {}

    updateControlsUI();
  }

  function updateControlsUI() {
    const soundBtn = document.getElementById('notif-sound-btn');
    if (soundBtn) {
      if (soundEnabled) {
        soundBtn.innerHTML = '<i class="fas fa-volume-up"></i> Sound ON';
        soundBtn.classList.add('active');
      } else {
        soundBtn.innerHTML = '<i class="fas fa-volume-mute"></i> Sound OFF';
        soundBtn.classList.remove('active');
      }
    }

    const browserBtn = document.getElementById('notif-browser-btn');
    if (browserBtn) {
      const isGranted = ('Notification' in window) && Notification.permission === 'granted';
      if (browserEnabled && isGranted) {
        browserBtn.innerHTML = '<i class="fas fa-desktop"></i> Desktop ON';
        browserBtn.classList.add('active');
      } else {
        browserBtn.innerHTML = '<i class="fas fa-desktop"></i> Desktop OFF';
        browserBtn.classList.remove('active');
      }
    }

    const volSlider = document.getElementById('notif-vol-slider');
    if (volSlider) {
      volSlider.value = Math.round(currentVolume * 100);
    }

    updateAudioStatusUI();
  }

  // 4. W3C Web Push & Service Worker Engine
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding)
      .replace(/\-/g, '+')
      .replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  function initServiceWorkerAndPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      console.info("Web Push / ServiceWorker not supported on this browser.");
      return;
    }

    navigator.serviceWorker.register('/static/sw.js')
      .then(function (reg) {
        swRegistration = reg;
        return reg.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (subscription) {
          pushSubscribed = true;
          syncPushSubscriptionOnServer(subscription);
        } else if (browserEnabled && ('Notification' in window) && Notification.permission === 'granted') {
          subscribeToPush();
        }
        updateControlsUI();
      })
      .catch(function (err) {
        console.warn("Service Worker / Push initialization notice:", err);
      });
  }

  function subscribeToPush() {
    if (!swRegistration) return Promise.reject("Service Worker not active");

    return fetch('/api/push/vapid_public_key')
      .then(res => res.json())
      .then(data => {
        if (!data.publicKey) throw new Error("VAPID public key unavailable");
        const appServerKey = urlBase64ToUint8Array(data.publicKey);
        return swRegistration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: appServerKey
        });
      })
      .then(subscription => {
        pushSubscribed = true;
        return syncPushSubscriptionOnServer(subscription);
      })
      .catch(err => {
        console.warn("Push registration error:", err);
        pushSubscribed = false;
        updateControlsUI();
      });
  }

  function unsubscribeFromPush() {
    if (!swRegistration) return Promise.resolve();

    return swRegistration.pushManager.getSubscription()
      .then(subscription => {
        if (subscription) {
          fetch('/api/push/unsubscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: subscription.endpoint })
          }).catch(() => {});
          return subscription.unsubscribe();
        }
      })
      .then(() => {
        pushSubscribed = false;
        updateControlsUI();
      })
      .catch(err => console.warn("Unsubscribe push error:", err));
  }

  function syncPushSubscriptionOnServer(subscription) {
    if (!subscription) return Promise.resolve();
    const subJson = subscription.toJSON();
    return fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subJson)
    })
    .then(res => res.json())
    .then(data => {
      updateControlsUI();
    })
    .catch(err => console.warn("Sync push subscription notice:", err));
  }

  // 5. Socket.IO Gateway Setup (Active Tab Real-Time Push)
  function initSocketIO() {
    if (typeof io !== 'function') {
      console.warn("Socket.IO client library not loaded. Falling back to background polling.");
      setInterval(fetchNotifications, 15000);
      return;
    }

    try {
      socket = io();
      socket.on('connect', () => {
        socket.emit('join_notification_channel');
      });

      socket.on('new_notification', (data) => {
        const exists = cachedNotifications.some(n => n.id === data.id && data.id !== 0);
        if (!exists) {
          cachedNotifications.unshift({
            id: data.id,
            title: data.title,
            message: data.message,
            category: data.category,
            action_url: data.action_url,
            is_read: false,
            timestamp: data.timestamp,
            time_display: data.timestamp
          });
        }

        updateBadgeUI(data.unread_count);
        renderNotificationsList();

        // Sound trigger for in-page active session
        if (data.sound && soundEnabled) {
          playNotificationChime(currentVolume);
        }

        // In-page Desktop OS Notification (if tab is hidden)
        if (browserEnabled && ('Notification' in window) && Notification.permission === 'granted') {
          if (document.hidden || data.is_test) {
            new Notification(data.title || "BMS College ERP", {
              body: data.message,
              icon: "/static/bms_logo.png"
            });
          }
        }
      });

      socket.on('unread_count_updated', (data) => {
        updateBadgeUI(data.unread_count);
      });
    } catch (err) {
      console.warn("Socket.IO initialization notice:", err);
      setInterval(fetchNotifications, 15000);
    }
  }

  // 6. Public Controller Interface
  window.BMSNotifications = {
    toggleDropdown: function (e) {
      if (e) e.stopPropagation();
      unlockAudioContext();
      const dropdown = document.getElementById('notifications-dropdown');
      if (!dropdown) return;

      const isHidden = dropdown.style.display === 'none' || !dropdown.style.display;
      if (isHidden) {
        dropdown.style.display = 'flex';
        fetchNotifications();
        document.getElementById('notifications-btn')?.setAttribute('aria-expanded', 'true');
      } else {
        dropdown.style.display = 'none';
        document.getElementById('notifications-btn')?.setAttribute('aria-expanded', 'false');
      }
    },

    setTab: function (tab) {
      activeTab = tab;
      document.getElementById('notif-tab-all')?.classList.toggle('active', tab === 'all');
      document.getElementById('notif-tab-unread')?.classList.toggle('active', tab === 'unread');
      renderNotificationsList();
    },

    toggleSettings: function () {
      const drawer = document.getElementById('notif-settings-drawer');
      if (drawer) {
        const isHidden = drawer.style.display === 'none' || !drawer.style.display;
        drawer.style.display = isHidden ? 'flex' : 'none';
      }
    },

    toggleSound: function () {
      unlockAudioContext();
      soundEnabled = !soundEnabled;
      savePreferences();
      if (soundEnabled) {
        playNotificationChime(currentVolume, true);
      }
    },

    toggleBrowser: function () {
      if (!('Notification' in window)) {
        alert("Desktop / background notifications are not supported by your current browser.");
        return;
      }

      if (Notification.permission === 'granted') {
        browserEnabled = !browserEnabled;
        savePreferences();
        if (browserEnabled) {
          subscribeToPush();
        } else {
          unsubscribeFromPush();
        }
      } else if (Notification.permission === 'denied') {
        alert("Desktop notifications are blocked in your browser settings. Please click the padlock or settings icon in your browser address bar to allow notifications.");
      } else {
        Notification.requestPermission().then(permission => {
          if (permission === 'granted') {
            browserEnabled = true;
            savePreferences();
            subscribeToPush().then(() => {
              new Notification("BMS College ERP", {
                body: "Background push notifications and sound alerts enabled!",
                icon: "/static/bms_logo.png"
              });
            });
          } else {
            browserEnabled = false;
            savePreferences();
          }
        });
      }
    },

    testSound: function () {
      unlockAudioContext();
      playNotificationChime(currentVolume, true);
      fetch('/api/notifications/test_sound', { method: 'POST' }).catch(() => {});
    },

    testBackgroundPush: function () {
      unlockAudioContext();
      fetch('/api/push/test_push', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          if (data.status === 'warning') {
            alert(data.message);
            window.BMSNotifications.toggleBrowser();
          } else {
            alert(data.message + "\n\nMinimize or close this browser window now to experience the native background push alert with sound!");
          }
        })
        .catch(err => {
          alert("Could not trigger background test push: " + err);
        });
    },

    setVolume: function (val) {
      currentVolume = Math.max(0.05, Math.min(1.0, parseInt(val, 10) / 100));
      savePreferences();
    },

    markAllRead: function () {
      markAllAsRead();
    },

    handleItemClick: function (e, id, url) {
      if (e) e.stopPropagation();
      markSingleAsRead(id);
      if (url) {
        window.location.href = url;
      }
    }
  };

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.notifications-wrapper');
    const dropdown = document.getElementById('notifications-dropdown');
    if (dropdown && wrapper && !wrapper.contains(e.target)) {
      dropdown.style.display = 'none';
      document.getElementById('notifications-btn')?.setAttribute('aria-expanded', 'false');
    }
  });

  // Initialization on DOM Ready
  document.addEventListener('DOMContentLoaded', () => {
    loadPreferences();
    fetchNotifications();
    initSocketIO();
    initServiceWorkerAndPush();
    updateAudioStatusUI();
  });
})();
