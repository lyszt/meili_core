import { LitElement, css, html } from 'lit';
import config from '../config/index.js';
import '@material/web/button/outlined-button.js';
import '@material/web/checkbox/checkbox.js';

/**
 * Dannazione di Providenza - Popup
 */
export class DannazionePopup extends LitElement {
  static get properties() {
    return {
      selectedText: { type: String },
      translatedText: { type: String },
      isTranslating: { type: Boolean },
      overlayEnabled: { type: Boolean },
      fromLang: { type: String },
      toLang: { type: String },
    };
  }

  constructor() {
    super();
    this.selectedText = '';
    this.translatedText = '';
    this.isTranslating = false;
    this.overlayEnabled = true;
    this.fromLang = 'auto';
    this.toLang = 'en';
    this.languages = [
      { code: 'auto', name: 'Auto Detect' },
      { code: 'en', name: 'English' },
      { code: 'es', name: 'Spanish' },
      { code: 'fr', name: 'French' },
      { code: 'de', name: 'German' },
      { code: 'it', name: 'Italian' },
      { code: 'pt', name: 'Portuguese' },
      { code: 'ru', name: 'Russian' },
      { code: 'ja', name: 'Japanese' },
      { code: 'zh-CN', name: 'Chinese (Simplified)' },
      { code: 'ko', name: 'Korean' },
      { code: 'ar', name: 'Arabic' },
      { code: 'hi', name: 'Hindi' },
      { code: 'tr', name: 'Turkish' },
      { code: 'pl', name: 'Polish' },
      { code: 'nl', name: 'Dutch' },
    ];
  }

  connectedCallback() {
    super.connectedCallback();
    this.loadSettings();
    this.getSelectedText();
  }

  async loadSettings() {
    try {
      const result = await chrome.storage.local.get(['overlayEnabled', 'fromLang', 'toLang']);
      this.overlayEnabled = result.overlayEnabled !== undefined ? result.overlayEnabled : true;
      this.fromLang = result.fromLang || 'auto';
      this.toLang = result.toLang || 'en';
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  }

  async toggleOverlay() {
    this.overlayEnabled = !this.overlayEnabled;
    try {
      await chrome.storage.local.set({ overlayEnabled: this.overlayEnabled });

      // Notify all tabs about the change
      const tabs = await chrome.tabs.query({});
      for (const tab of tabs) {
        if (tab.id) {
          chrome.tabs.sendMessage(tab.id, {
            type: 'OVERLAY_TOGGLE',
            enabled: this.overlayEnabled,
          }).catch(() => {}); // Ignore errors for tabs that don't have content script
        }
      }
    } catch (error) {
      console.error('Failed to toggle overlay:', error);
    }
  }

  async handleFromLangChange(e) {
    this.fromLang = e.target.value;
    try {
      await chrome.storage.local.set({ fromLang: this.fromLang });
      // Re-translate if there's selected text
      if (this.selectedText) {
        this.translateText();
      }
    } catch (error) {
      console.error('Failed to save from language:', error);
    }
  }

  async handleToLangChange(e) {
    this.toLang = e.target.value;
    try {
      await chrome.storage.local.set({ toLang: this.toLang });
      // Re-translate if there's selected text
      if (this.selectedText) {
        this.translateText();
      }
    } catch (error) {
      console.error('Failed to save to language:', error);
    }
  }

  async getSelectedText() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

      if (!tab || !tab.url || (!tab.url.startsWith('http://') && !tab.url.startsWith('https://'))) {
        this.selectedText = '';
        return;
      }

      if (tab.id) {
        try {
          const response = await chrome.tabs.sendMessage(tab.id, {
            type: 'GET_SELECTED_TEXT',
          });
          this.selectedText = response?.text || '';

          if (this.selectedText) {
            this.translateText();
          }
        } catch (msgError) {
          // Content script not loaded yet, inject it
          if (msgError.message.includes('Receiving end does not exist')) {
            try {
              await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ['content.js']
              });

              // Wait a bit for injection
              await new Promise(resolve => setTimeout(resolve, 100));

              // Try again
              const response = await chrome.tabs.sendMessage(tab.id, {
                type: 'GET_SELECTED_TEXT',
              });
              this.selectedText = response?.text || '';

              if (this.selectedText) {
                this.translateText();
              }
            } catch (injectError) {
              // Page can't be scripted, silently ignore
              this.selectedText = '';
            }
          } else {
            throw msgError;
          }
        }
      }
    } catch (error) {
      console.error('Failed to get selected text:', error);
    }
  }

  async translateText() {
    if (!this.selectedText) return;

    this.isTranslating = true;
    try {
      // Route through the background script, which calls the local backend (/translate)
      const response = await chrome.runtime.sendMessage({
        type: 'TRANSLATE_TEXT',
        text: this.selectedText,
      });
      this.translatedText = response?.translation || 'No translation available';
    } catch (error) {
      console.error('Translation failed:', error);
      this.translatedText = 'Translation failed: ' + (error.message || error);
    } finally {
      this.isTranslating = false;
    }
  }

  render() {
    return html`
      <div class="popup-container min-w-[400px] w-[450px] min-h-[500px] font-sans bg-gray-900 text-gray-100">
        <header class="popup-header">
          <h1>Dannazione di Providenza</h1>
        </header>

        <div class="settings-section">
                <div class="setting-item">
                  <label>
                    <span>From Language</span>
                    <select class="lang-select" @change=${this.handleFromLangChange} .value=${this.fromLang}>
                      ${this.languages.map(lang => html`
                        <option value=${lang.code} ?selected=${lang.code === this.fromLang}>
                          ${lang.name}
                        </option>
                      `)}
                    </select>
                  </label>
                </div>

                <div class="setting-item">
                  <label>
                    <span>To Language</span>
                    <select class="lang-select" @change=${this.handleToLangChange} .value=${this.toLang}>
                      ${this.languages.filter(l => l.code !== 'auto').map(lang => html`
                        <option value=${lang.code} ?selected=${lang.code === this.toLang}>
                          ${lang.name}
                        </option>
                      `)}
                    </select>
                  </label>
                </div>

                <div class="setting-item">
                  <label>
                    <span>Auto-translate on selection</span>
                    <input
                      type="checkbox"
                      class="toggle"
                      ?checked=${this.overlayEnabled}
                      @change=${this.toggleOverlay}
                    />
                  </label>
                </div>
              </div>

              <div class="popup-content">
                ${this.selectedText
                  ? html`
                      <div class="text-section">
                        <div class="text-block">
                          <strong>Original:</strong>
                          <p>${this.selectedText}</p>
                        </div>

                        <div class="text-block translation">
                          <strong>Translation:</strong>
                          ${this.isTranslating
                            ? html`<p class="loading">Translating...</p>`
                            : html`<p>${this.translatedText || 'No translation available'}</p>`}
                        </div>
                      </div>
                    `
                  : html`<p class="hint">Select text on the page</p>`}
              </div>
      </div>
    `;
  }
}

window.customElements.define('dannazione-popup', DannazionePopup);
