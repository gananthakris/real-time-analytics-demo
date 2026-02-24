/**
 * Real-Time Analytics JavaScript SDK
 * Lightweight client-side event tracking
 */

class AnalyticsTracker {
  constructor(config) {
    this.config = {
      apiUrl: config.apiUrl || 'http://localhost:8000',
      customerId: config.customerId,
      batchSize: config.batchSize || 10,
      flushInterval: config.flushInterval || 5000, // 5 seconds
      debug: config.debug || false
    };

    // Initialize
    this.eventQueue = [];
    this.visitorId = this._getOrCreateVisitorId();
    this.sessionId = this._getOrCreateSessionId();
    this.userId = null;

    // Start auto-flush timer
    this._startAutoFlush();

    // Track page views automatically
    if (config.autoTrackPageViews !== false) {
      this._trackPageView();
      this._setupPageViewTracking();
    }

    this._log('Analytics tracker initialized', {
      visitorId: this.visitorId,
      sessionId: this.sessionId
    });
  }

  /**
   * Track an event
   */
  track(eventType, eventName, properties = {}) {
    const event = {
      customer_id: this.config.customerId,
      visitor_id: this.visitorId,
      user_id: this.userId,
      session_id: this.sessionId,
      event_type: eventType,
      event_name: eventName,
      properties: properties,
      page_url: window.location.href,
      referrer: document.referrer || null,
      timestamp: new Date().toISOString()
    };

    this._log('Event tracked', event);

    // Add to queue
    this.eventQueue.push(event);

    // Flush if batch size reached
    if (this.eventQueue.length >= this.config.batchSize) {
      this.flush();
    }

    return this;
  }

  /**
   * Track page view
   */
  page(properties = {}) {
    return this.track('page_view', 'Page View', {
      page: window.location.pathname,
      title: document.title,
      url: window.location.href,
      ...properties
    });
  }

  /**
   * Track button click
   */
  click(buttonId, properties = {}) {
    return this.track('button_click', 'Button Click', {
      button_id: buttonId,
      ...properties
    });
  }

  /**
   * Track form submission
   */
  formSubmit(formId, properties = {}) {
    return this.track('form_submit', 'Form Submit', {
      form_id: formId,
      ...properties
    });
  }

  /**
   * Identify a user (after login)
   */
  identify(userId, traits = {}) {
    this.userId = userId;
    this._log('User identified', { userId, traits });

    return this.track('identify', 'User Identified', {
      user_id: userId,
      traits: traits
    });
  }

  /**
   * Flush queued events to server
   */
  async flush() {
    if (this.eventQueue.length === 0) {
      return;
    }

    const events = [...this.eventQueue];
    this.eventQueue = [];

    try {
      const response = await fetch(`${this.config.apiUrl}/track/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ events })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      this._log('Events flushed', result);

    } catch (error) {
      this._log('Error flushing events', error, 'error');
      // Re-queue events on failure
      this.eventQueue = [...events, ...this.eventQueue];
    }
  }

  /**
   * Reset session (e.g., after logout)
   */
  reset() {
    this.userId = null;
    this.sessionId = this._generateId();
    sessionStorage.setItem('analytics_session_id', this.sessionId);
    this._log('Session reset');
  }

  // Private methods

  _getOrCreateVisitorId() {
    let visitorId = localStorage.getItem('analytics_visitor_id');
    if (!visitorId) {
      visitorId = this._generateId();
      localStorage.setItem('analytics_visitor_id', visitorId);
    }
    return visitorId;
  }

  _getOrCreateSessionId() {
    let sessionId = sessionStorage.getItem('analytics_session_id');
    if (!sessionId) {
      sessionId = this._generateId();
      sessionStorage.setItem('analytics_session_id', sessionId);
    }
    return sessionId;
  }

  _generateId() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  _trackPageView() {
    this.page();
  }

  _setupPageViewTracking() {
    // Track page views on navigation (for SPAs)
    let lastUrl = window.location.href;

    const observer = new MutationObserver(() => {
      const currentUrl = window.location.href;
      if (currentUrl !== lastUrl) {
        lastUrl = currentUrl;
        this._trackPageView();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    // Also track on popstate (back/forward)
    window.addEventListener('popstate', () => {
      this._trackPageView();
    });
  }

  _startAutoFlush() {
    setInterval(() => {
      if (this.eventQueue.length > 0) {
        this.flush();
      }
    }, this.config.flushInterval);

    // Flush on page unload
    window.addEventListener('beforeunload', () => {
      if (this.eventQueue.length > 0) {
        // Use sendBeacon for reliable delivery on page unload
        const data = JSON.stringify({ events: this.eventQueue });
        navigator.sendBeacon(`${this.config.apiUrl}/track/batch`, data);
      }
    });
  }

  _log(message, data = null, level = 'info') {
    if (this.config.debug) {
      const prefix = '[Analytics]';
      if (level === 'error') {
        console.error(prefix, message, data);
      } else {
        console.log(prefix, message, data);
      }
    }
  }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AnalyticsTracker;
}

// Global variable for script tag usage
if (typeof window !== 'undefined') {
  window.AnalyticsTracker = AnalyticsTracker;
}
