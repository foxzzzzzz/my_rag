import { defineConfig } from 'vite';
import react from 'react';
export default defineConfig({server:{proxy:{'/api':'http://127.0.0.1:8765'}}});
