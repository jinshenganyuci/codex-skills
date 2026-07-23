const bridge = document.querySelector('#bridge');

bridge.textContent = typeof window.ksu !== 'undefined'
  ? 'KernelSU bridge detected. Add only fixed, audited module actions.'
  : 'Open through KernelSU Manager for native APIs.';
