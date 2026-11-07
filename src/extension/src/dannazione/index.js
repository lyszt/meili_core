class DannazioneAPI {
  constructor(base_url) {
    this.base_url = base_url;
    this.initialize();
  }

  initialize() {
    console.log('[Dannazione] Initializing...');
  }

  async sendContext(contextData) {
    const payload = {
      url: contextData.url,
      title: contextData.title,
      html: contextData.body || '',
      type: contextData.type || 'default'
    };

    const response = await fetch(`${this.base_url}/context`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    console.log('[Dannazione] Context sent successfully:', data);
    return data;
  }

  async sendSelection(text) {
    const response = await fetch(`${this.base_url}/context/select`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    console.log('[Dannazione] Selection sent successfully:', data);
    return data;
  }
}

export default DannazioneAPI;
