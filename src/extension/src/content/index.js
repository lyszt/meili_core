/**
 * Dannazione di Providenza - Content Script
 * Selection -> translation overlay. No chat, no page-content storage.
 */

import DannazioneAPI from '../dannazione/index.js';
import config from '../config/index.js';

const api = new DannazioneAPI(config.api.baseUrl);

console.log('[Dannazione] Content script loaded on', window.location.href);

let overlayEnabled = true;
let translationOverlay = null;
let isTranslating = false;

// Load overlay state from storage
chrome.storage.local.get('overlayEnabled').then((result) => {
  overlayEnabled = result.overlayEnabled !== undefined ? result.overlayEnabled : true;
  if (overlayEnabled) {
    attachSelectionListener();
  }
});

// Handle messages from background/popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case 'GET_SELECTED_TEXT':
      sendResponse({ text: getSelectedText() });
      break;

    case 'OVERLAY_TOGGLE':
      overlayEnabled = message.enabled;
      if (overlayEnabled) {
        attachSelectionListener();
      } else {
        detachSelectionListener();
        hideOverlay();
      }
      break;
  }

  return false;
});

// Get selected text from page
function getSelectedText() {
  return window.getSelection()?.toString().trim() || '';
}

// Attach selection listener
function attachSelectionListener() {
  document.addEventListener('mouseup', handleTextSelection);
}

// Detach selection listener
function detachSelectionListener() {
  document.removeEventListener('mouseup', handleTextSelection);
}

// Handle text selection
async function handleTextSelection(event) {
  if (!overlayEnabled) return;

  const selectedText = getSelectedText();

  if (!selectedText) {
    hideOverlay();
    return;
  }

  if (isTranslating) return;

  // Send selection to backend (in-memory context only)
  try {
    await api.sendSelection(selectedText);
  } catch (error) {
    console.error('[Dannazione] Failed to send selection:', error);
  }

  // Get selection coordinates
  const selection = window.getSelection();
  if (!selection.rangeCount) return;

  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();

  // Show overlay with loading state
  showOverlay(rect, selectedText, 'Translating...');

  // Request translation from background script
  isTranslating = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: 'TRANSLATE_TEXT',
      text: selectedText,
    });
    showOverlay(rect, selectedText, response.translation);
  } catch (error) {
    console.error('Translation failed:', error);
    showOverlay(rect, selectedText, 'Translation failed');
  } finally {
    isTranslating = false;
  }
}

// Show translation overlay
function showOverlay(rect, original, translation) {
  // Remove existing overlay
  if (translationOverlay) {
    translationOverlay.remove();
  }

  // Create overlay
  translationOverlay = document.createElement('div');
  translationOverlay.className = 'dannazione-translation-overlay';
  translationOverlay.innerHTML = `
    <div class="dannazione-overlay-close">×</div>
    <div class="dannazione-overlay-section">
      <strong>Original:</strong>
      <p>${escapeHtml(original)}</p>
    </div>
    <div class="dannazione-overlay-section translation">
      <strong>Translation:</strong>
      <p>${escapeHtml(translation)}</p>
    </div>
  `;

  // Position overlay
  const top = rect.bottom + window.scrollY + 10;
  const left = rect.left + window.scrollX;

  translationOverlay.style.top = `${top}px`;
  translationOverlay.style.left = `${left}px`;

  // Add to page
  document.body.appendChild(translationOverlay);

  // Add close button handler
  const closeBtn = translationOverlay.querySelector('.dannazione-overlay-close');
  closeBtn.addEventListener('click', hideOverlay);

  // Close on click outside
  setTimeout(() => {
    document.addEventListener('click', handleOutsideClick);
  }, 100);
}

// Hide overlay
function hideOverlay() {
  if (translationOverlay) {
    translationOverlay.remove();
    translationOverlay = null;
  }
  document.removeEventListener('click', handleOutsideClick);
}

// Handle click outside overlay
function handleOutsideClick(event) {
  if (translationOverlay && !translationOverlay.contains(event.target)) {
    hideOverlay();
  }
}

// Escape HTML
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Inject overlay styles
const style = document.createElement('style');
style.textContent = `
  .dannazione-translation-overlay {
    position: absolute;
    z-index: 2147483647;
    background: rgba(26, 26, 26, 0.98);
    border: 1px solid rgba(102, 126, 234, 0.5);
    border-radius: 8px;
    padding: 12px;
    min-width: 300px;
    max-width: 500px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #e0e0e0;
    backdrop-filter: blur(10px);
  }

  .dannazione-overlay-close {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    border-radius: 4px;
    font-size: 20px;
    color: #9ca3af;
    transition: all 0.2s;
  }

  .dannazione-overlay-close:hover {
    background: rgba(255, 255, 255, 0.1);
    color: white;
  }

  .dannazione-overlay-section {
    margin-bottom: 12px;
  }

  .dannazione-overlay-section:last-child {
    margin-bottom: 0;
  }

  .dannazione-overlay-section.translation {
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%);
    padding: 8px;
    border-radius: 4px;
  }

  .dannazione-overlay-section strong {
    display: block;
    margin-bottom: 4px;
    color: #9ca3af;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .dannazione-overlay-section p {
    margin: 0;
    color: #e0e0e0;
    font-size: 14px;
    line-height: 1.5;
  }
`;
document.head.appendChild(style);
