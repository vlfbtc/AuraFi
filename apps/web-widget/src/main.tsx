import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { captureAttribution } from './attribution';
import './styles.css';

// Before the first render, so the address bar is already clean when React mounts.
captureAttribution();

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Elemento raiz do Web Widget não encontrado.');
}

createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
