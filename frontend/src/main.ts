import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import ElementPlus from 'element-plus'
import router from './router'
import 'element-plus/dist/index.css'
import './styles/main.css'

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')

