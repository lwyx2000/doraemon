import { createApp } from 'vue'
import naive from 'naive-ui'
import router from './router'
import App from './App.vue'
import './style.css'

const app = createApp(App)
app.use(router)
app.use(naive)
app.mount('#app')
